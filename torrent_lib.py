#!/usr/bin/env python3
"""Briques communes aux scripts de gestion des torrents de ce dépôt.

Volontairement sans aucune dépendance externe (stdlib uniquement) : ces
scripts tournent aussi bien sur la machine du labo que sur la clé USB de
préparation, y compris sous Windows, où l'on ne veut ni `pip install` ni
binaire à trimballer.

Sommaire :
  - bencode          : encodage/décodage du format BitTorrent, info-hash
  - .env             : lecture du fichier de configuration du dépôt
  - URL du labo      : dérivation tracker/webseed depuis LAB_HOST_IP
  - MANIFEST.sha256  : génération et vérification d'intégrité
  - création torrent : découpage en pièces et construction du .torrent
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

MANIFEST_NAME = "MANIFEST.sha256"

# Taille du tampon de lecture. Les images de VM se comptent en gigaoctets :
# on lit par gros blocs pour ne pas payer un appel système par kilo-octet.
CHUNK = 1024 * 1024


# --- bencode : décodage ---------------------------------------------------

def bdecode(data: bytes):
    def decode_bytes(index):
        colon = data.index(b":", index)
        length = int(data[index:colon])
        start = colon + 1
        return data[start:start + length], start + length

    def decode(index):
        marker = data[index:index + 1]
        if marker == b"d":
            index += 1
            d = {}
            while data[index:index + 1] != b"e":
                key, index = decode_bytes(index)
                val, index = decode(index)
                d[key] = val
            return d, index + 1
        if marker == b"l":
            index += 1
            items = []
            while data[index:index + 1] != b"e":
                val, index = decode(index)
                items.append(val)
            return items, index + 1
        if marker == b"i":
            end = data.index(b"e", index)
            return int(data[index + 1:end]), end + 1
        return decode_bytes(index)

    result, index = decode(0)
    if index != len(data):
        raise ValueError("Données superflues après la structure bencode racine")
    return result


# --- bencode : encodage ----------------------------------------------------

def bencode(obj) -> bytes:
    if isinstance(obj, bool):
        raise TypeError("bencode ne supporte pas bool (utiliser int)")
    if isinstance(obj, int):
        return b"i" + str(obj).encode("ascii") + b"e"
    if isinstance(obj, bytes):
        return str(len(obj)).encode("ascii") + b":" + obj
    if isinstance(obj, str):
        return bencode(obj.encode("utf-8"))
    if isinstance(obj, list):
        return b"l" + b"".join(bencode(item) for item in obj) + b"e"
    if isinstance(obj, dict):
        normalized = {(k.encode("utf-8") if isinstance(k, str) else k): v for k, v in obj.items()}
        return b"d" + b"".join(
            bencode(key) + bencode(normalized[key]) for key in sorted(normalized)
        ) + b"e"
    raise TypeError(f"Type non supporté pour bencode : {type(obj)}")


def infohash(info: dict) -> str:
    """Empreinte SHA-1 du dictionnaire `info` : l'identifiant du swarm."""
    return hashlib.sha1(bencode(info)).hexdigest()


# --- configuration (.env) --------------------------------------------------

def load_dotenv(path: Path | None = None) -> None:
    """Charge les variables de .env dans l'environnement (sans écraser l'existant)."""
    if path is None:
        path = Path(__file__).parent / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


# --- URL du labo -----------------------------------------------------------
#
# L'info-hash ne dépend que du contenu : trackers et webseeds vivent en dehors
# du dictionnaire `info`. C'est ce qui permet à la clé de préparation de
# produire un .torrent « nu », que la machine du labo tamponne ensuite avec
# SES adresses — sans changer l'info-hash, donc sans casser le swarm. L'IP du
# labo n'est donc écrite qu'ici, via LAB_HOST_IP dans .env.

def lab_host() -> str:
    """Retourne LAB_HOST_IP, ou termine le programme avec un message clair."""
    host = os.environ.get("LAB_HOST_IP", "").strip()
    if not host or host.startswith("à-"):
        raise SystemExit(
            "LAB_HOST_IP n'est pas renseigné dans .env (cf. .env.sample).\n"
            "C'est l'adresse de CETTE machine sur le réseau du labo, celle que\n"
            "les postes étudiants doivent joindre pour le tracker et la webseed.\n"
            "Repérez-la avec :  ip -4 -o addr show scope global"
        )
    return host


def tracker_urls() -> list[str]:
    """Les URL d'annonce d'opentracker (HTTP puis UDP, cf. docker-compose.yml)."""
    host = lab_host()
    return [f"http://{host}:6969/announce", f"udp://{host}:6969/announce"]


def webseed_url() -> str:
    """L'URL webseed (BEP 19) servie par torrents-http.

    La barre finale est significative : sur un torrent multi-fichiers, le
    client ajoute `<nom-du-torrent>/<chemin>` à cette URL. Sans elle, il
    demanderait une URL concaténée sans séparateur, et la webseed échouerait.
    """
    port = os.environ.get("TORRENTS_HTTP_PORT", "8081").strip() or "8081"
    return f"http://{lab_host()}:{port}/images-vm/"


# --- MANIFEST.sha256 -------------------------------------------------------
#
# Le manifeste est généré DANS le dossier source, donc il fait partie du
# contenu du torrent : les postes étudiants le reçoivent et peuvent vérifier
# leur copie eux-mêmes (`sha256sum -c MANIFEST.sha256`). Corollaire : il doit
# être écrit AVANT la création du .torrent et ne plus jamais être régénéré
# ensuite, sous peine de changer le contenu et donc l'info-hash.

def iter_files(root: Path) -> list[Path]:
    """Fichiers du dossier, triés, manifeste exclu (il ne s'auto-hache pas)."""
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.name != MANIFEST_NAME
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb", buffering=CHUNK) as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(root: Path) -> int:
    """Écrit MANIFEST.sha256 au format `sha256sum` (deux espaces, LF).

    Ce format est lisible tel quel par `sha256sum -c` sur les VM des
    étudiants, sans outil supplémentaire.
    """
    lines = [f"{sha256_file(f)}  {f.relative_to(root).as_posix()}" for f in iter_files(root)]
    (root / MANIFEST_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(lines)


def parse_manifest(text: str) -> list[tuple[str, str]]:
    """Analyse un manifeste en tolérant les variantes rencontrées en pratique.

    Deux séparateurs coexistent : `<hash>  <chemin>` (sha256sum, et rhash par
    défaut) et `<hash> *<chemin>` (mode binaire). Les manifestes produits sous
    Windows arrivent par ailleurs en CRLF. On accepte les deux formes et on
    retire le CR, sinon un manifeste préparé à la maison sous Windows échoue à
    la vérification sur la machine du labo.
    """
    entries = []
    for raw in text.splitlines():
        line = raw.strip("\r").strip()
        if not line or line.startswith("#"):
            continue
        digest, sep, rest = line.partition(" ")
        if not sep:
            raise ValueError(f"Ligne de manifeste invalide : {raw!r}")
        rel = rest[1:] if rest.startswith("*") else rest.lstrip()
        entries.append((digest.lower(), rel))
    return entries


def verify_manifest(root: Path, report=print) -> bool:
    """Vérifie l'intégrité du dossier contre son MANIFEST.sha256.

    Signale aussi les fichiers présents mais absents du manifeste : sur une
    copie, un fichier en trop change le contenu du torrent tout autant qu'un
    fichier manquant.
    """
    manifest = root / MANIFEST_NAME
    if not manifest.exists():
        report(f"MANIFEST absent : {manifest}")
        return False

    entries = parse_manifest(manifest.read_text(encoding="utf-8"))
    ok = True
    for expected, rel in entries:
        target = root / rel
        if not target.exists():
            report(f"  MANQUANT : {rel}")
            ok = False
            continue
        if sha256_file(target) != expected:
            report(f"  ALTÉRÉ   : {rel}")
            ok = False

    listed = {rel for _, rel in entries}
    for f in iter_files(root):
        rel = f.relative_to(root).as_posix()
        if rel not in listed:
            report(f"  EN TROP  : {rel} (absent du manifeste)")
            ok = False

    return ok


# --- création d'un .torrent ------------------------------------------------

def pick_piece_length(total: int) -> int:
    """Choisit une taille de pièce : puissance de deux visant ~1500 pièces.

    Bornée entre 256 Kio et 16 Mio. Trop de pièces alourdit le .torrent (20
    octets de SHA-1 chacune) ; trop peu rend les échanges entre pairs plus
    grossiers. Une image de VM de ~5 Gio tombe ainsi sur 4 Mio.
    """
    target = max(total // 1500, 1)
    size = 256 * 1024
    while size < target and size < 16 * 1024 * 1024:
        size *= 2
    return size


def build_info(root: Path, piece_length: int | None = None, progress=None) -> dict:
    """Construit le dictionnaire `info` d'un torrent multi-fichiers.

    Les pièces sont hachées sur le flux des fichiers concaténés dans l'ordre
    du torrent, sans tenir compte des frontières de fichiers : une pièce peut
    chevaucher deux fichiers. L'ordre des fichiers fait donc partie de
    l'identité du contenu — on le fige par tri sur le chemin relatif.
    """
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        raise ValueError(f"Aucun fichier à inclure dans {root}")

    total = sum(f.stat().st_size for f in files)
    if piece_length is None:
        piece_length = pick_piece_length(total)

    pieces = bytearray()
    buffer = bytearray()
    done = 0
    for path in files:
        with path.open("rb", buffering=CHUNK) as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                buffer.extend(chunk)
                done += len(chunk)
                while len(buffer) >= piece_length:
                    pieces.extend(hashlib.sha1(bytes(buffer[:piece_length])).digest())
                    del buffer[:piece_length]
                if progress:
                    progress(done, total)
    if buffer:  # dernière pièce, partielle
        pieces.extend(hashlib.sha1(bytes(buffer)).digest())

    return {
        b"name": root.name.encode("utf-8"),
        b"piece length": piece_length,
        b"pieces": bytes(pieces),
        b"files": [
            {
                b"length": f.stat().st_size,
                b"path": [part.encode("utf-8") for part in f.relative_to(root).parts],
            }
            for f in files
        ],
    }


# --- affichage -------------------------------------------------------------
#
# Les scripts de ce dépôt sont lancés à la main, souvent en salle et dans
# l'urgence : un peu de couleur aide à repérer une erreur au milieu d'une
# sortie longue. Désactivé hors terminal (redirection, journal) et si la
# variable d'environnement NO_COLOR est définie.

_COLOR = os.environ.get("NO_COLOR") is None and sys.stdout.isatty()


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def HDR(s: str) -> None:
    print("\n" + _c("1;35", f"=== {s} ==="))


def INFO(s: str) -> None:
    print(_c("36", "[INFO] ") + s)


def STEP(s: str) -> None:
    print(_c("34", "[ETAP] ") + s)


def OK(s: str) -> None:
    print(_c("32", "[ OK ] ") + s)


def WARN(s: str) -> None:
    print(_c("33", "[ATTN] ") + s)


def ERR(s: str) -> None:
    print(_c("31", "[ECHC] ") + s)


def human(n: float) -> str:
    """Taille lisible : 5017795584 -> '4.67 Gio'."""
    for unit in ("o", "Kio", "Mio", "Gio"):
        if abs(n) < 1024 or unit == "Gio":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} Gio"


# --- qBittorrent (API WebUI) -----------------------------------------------
#
# Seule partie du module à sortir de la bibliothèque standard : elle a besoin
# de `requests`. L'import est fait à l'appel, pas au chargement du module, pour
# que la préparation des torrents (make_torrent.py, sur la clé) reste utilisable
# sans aucune dépendance installée.

QBIT_DEFAULT_URL = "http://localhost:8080"
QBIT_USERNAME = "admin"
# IMAGES_VM_PATH vu de l'intérieur du conteneur (cf. docker-compose.yml).
QBIT_SAVE_PATH = "/data"


def qbit_login(base_url: str = QBIT_DEFAULT_URL):
    """Ouvre une session authentifiée sur l'API WebUI de qBittorrent."""
    try:
        import requests
    except ImportError:
        raise SystemExit(
            "Le module `requests` est requis pour piloter qBittorrent.\n"
            "Installez-le avec :  python3 -m pip install --user requests"
        )

    password = os.environ.get("QBITTORRENT_WEBUI_PASSWORD", "")
    if not password or password == "à-définir":
        raise SystemExit(
            "QBITTORRENT_WEBUI_PASSWORD n'est pas défini dans .env.\n"
            "Définissez un mot de passe FIXE dans la WebUI (Outils > Options >\n"
            "WebUI > Authentification), puis reportez-le dans .env\n"
            "(cf. docs/qbittorrent.md)."
        )

    session = requests.Session()
    r = session.post(f"{base_url}/api/v2/auth/login",
                     data={"username": QBIT_USERNAME, "password": password})

    # Deux contrats coexistent selon la version de qBittorrent. Les versions
    # récentes (5.x, observé en 5.2.3 — image linuxserver/qbittorrent) répondent
    # par un code HTTP standard : 204 sans corps sur succès, 401 sur échec. Les
    # versions historiques (et la documentation officielle de l'API, jamais mise
    # à jour sur ce point) répondaient toujours 200, avec un corps "Ok." ou
    # "Fails.". On accepte les deux formes plutôt que d'en figer un qui a déjà
    # changé une fois. Pas de raise_for_status() ici : un 401 le ferait échouer
    # avec une trace Python au lieu du message clair ci-dessous.
    ok = r.status_code == 204 or (r.status_code == 200 and r.text.strip() == "Ok.")
    if not ok:
        detail = f"HTTP {r.status_code}"
        if r.text.strip():
            detail += f", {r.text.strip()!r}"
        raise SystemExit(
            f"Authentification refusée par qBittorrent ({detail}).\n"
            "Causes habituelles :\n"
            "  - aucun mot de passe FIXE n'a été défini : l'image en génère un\n"
            "    nouveau à chaque démarrage (docker compose logs qbittorrent)\n"
            "  - le mot de passe de .env ne correspond plus à celui de la WebUI\n"
            "  - trop d'essais ratés : l'IP est bannie temporairement\n"
            "    (docker compose restart qbittorrent lève le bannissement)\n"
            "Procédure complète : docs/qbittorrent.md"
        )
    return session
