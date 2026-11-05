#!/usr/bin/env python3
"""Supprime un torrent devenu obsolète : seed qBittorrent, données et .torrent.

Usage : python3 remove_torrent.py NOM [--dry-run] [--yes]

NOM est le nom du fichier `.torrent` sans son extension (ex. `debian-12` pour
`torrents/debian-12.torrent`). C'est aussi, par construction, le nom du dossier
d'images sous IMAGES_VM_PATH. Trois choses sont supprimées, dans cet ordre :

  1. le torrent dans qBittorrent, avec ses données (l'arrêt du seed passe
     AVANT l'effacement des fichiers, sinon qBittorrent passerait en erreur) ;
  2. ce qui reste des données sous IMAGES_VM_PATH (filet de sécurité si
     qBittorrent ne connaissait pas ce torrent ou n'a pas tout effacé) ;
  3. le .torrent publié dans ./torrents (il disparaît de torrents-http).

Irréversible : sans --yes, une confirmation est demandée. Les postes qui
possèdent déjà l'image ne sont pas touchés ; ils ne pourront simplement plus
la récupérer depuis ce labo.
"""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from torrent_lib import (  # noqa: E402
    ERR, HDR, INFO, OK, QBIT_DEFAULT_URL, STEP, WARN,
    bdecode, human, infohash, load_dotenv, qbit_login,
)

REPO = Path(__file__).resolve().parent
PUBLISHED_TORRENTS = REPO / "torrents"   # monté dans torrents-http (/torrents/)


def dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def qbit_delete(session, base_url: str, ih: str) -> bool:
    """Supprime le torrent + ses fichiers côté qBittorrent. False si inconnu."""
    r = session.get(f"{base_url}/api/v2/torrents/info", params={"hashes": ih})
    r.raise_for_status()
    if not r.json():
        WARN("Torrent absent de qBittorrent (déjà retiré ?) — rien à y supprimer.")
        return False

    r = session.post(f"{base_url}/api/v2/torrents/delete",
                     data={"hashes": ih, "deleteFiles": "true"})
    r.raise_for_status()

    # La suppression est asynchrone : on attend que le torrent disparaisse.
    for _ in range(20):
        r = session.get(f"{base_url}/api/v2/torrents/info", params={"hashes": ih})
        if not r.json():
            OK("Retiré de qBittorrent (données effacées par qBittorrent).")
            return True
        time.sleep(0.5)
    ERR("qBittorrent n'a pas retiré le torrent à temps ; rien d'autre n'est supprimé.")
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", metavar="NOM",
                        help="Nom du .torrent sans l'extension")
    parser.add_argument("--dry-run", action="store_true",
                        help="Montre ce qui serait supprimé, sans rien toucher")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Ne demande pas de confirmation")
    parser.add_argument("--qbit-url", default=QBIT_DEFAULT_URL,
                        help="URL de la WebUI qBittorrent (défaut : http://localhost:8080)")
    args = parser.parse_args()

    load_dotenv()
    name = args.name

    # Le nom sert à construire des chemins qu'on va effacer : aucun séparateur,
    # aucun composant spécial n'est toléré.
    if name in ("", ".", "..") or "/" in name or "\\" in name or "\0" in name:
        ERR(f"Nom invalide : {name!r} (attendu : nom de fichier sans .torrent, sans '/').")
        return 2
    if name.endswith(".torrent"):
        name = name[: -len(".torrent")]

    torrent_file = PUBLISHED_TORRENTS / f"{name}.torrent"
    if not torrent_file.is_file():
        ERR(f"{torrent_file} introuvable.")
        available = sorted(p.stem for p in PUBLISHED_TORRENTS.glob("*.torrent"))
        if available:
            INFO("Torrents publiés : " + ", ".join(available))
        return 1

    try:
        meta = bdecode(torrent_file.read_bytes())
        info = meta[b"info"]
        ih = infohash(info)
        content_name = info[b"name"].decode("utf-8")
    except (ValueError, KeyError, UnicodeDecodeError) as e:
        ERR(f"{torrent_file.name} n'est pas un .torrent valide : {e}")
        return 1

    images_path = os.environ.get("IMAGES_VM_PATH", "").strip()
    if not images_path:
        ERR("IMAGES_VM_PATH n'est pas renseigné dans .env (cf. .env.sample).")
        return 1
    images_dir = Path(images_path).resolve()
    if not images_dir.is_dir():
        ERR(f"IMAGES_VM_PATH pointe vers {images_dir}, qui n'existe pas.")
        return 1

    # Les données se trouvent sous le nom interne du torrent, qui devrait
    # égaler le nom du fichier ; sinon on suit le torrent, pas le fichier.
    if content_name != name:
        WARN(f"Le nom interne du torrent ({content_name!r}) diffère du nom du fichier.")
    if content_name in ("", ".", "..") or "/" in content_name or "\\" in content_name:
        ERR(f"Nom interne du torrent suspect ({content_name!r}) : abandon.")
        return 1
    data = (images_dir / content_name)
    if data.resolve().parent != images_dir:
        ERR(f"{data} sort de IMAGES_VM_PATH : abandon.")
        return 1

    HDR(f"Suppression de {name}")
    INFO(f"Info-hash    : {ih}")
    INFO(f".torrent     : {torrent_file}")
    if data.exists():
        INFO(f"Données      : {data}  ({human(dir_size(data))})")
    else:
        INFO(f"Données      : {data}  (absentes)")

    if args.dry_run:
        INFO("[essai] supprimerait le torrent de qBittorrent, ses données et le .torrent")
        return 0

    if not args.yes:
        try:
            answer = input("Supprimer définitivement ? [o/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("o", "oui", "y", "yes"):
            INFO("Abandon, rien n'a été supprimé.")
            return 1

    # 1. qBittorrent d'abord : un échec d'authentification ou de connexion
    #    arrête tout avant qu'on ait touché aux fichiers.
    STEP("Retrait de qBittorrent")
    session = qbit_login(args.qbit_url)
    qbit_delete(session, args.qbit_url, ih)

    # 2. Reliquat éventuel des données.
    # qBittorrent efface les fichiers de façon asynchrone : le dossier peut
    # encore exister quand on le teste, puis disparaître en cours de route.
    # Un fichier déjà absent n'est donc pas une erreur ici.
    def ignore_missing(func, path, exc):
        if not isinstance(exc, FileNotFoundError):
            raise exc

    if data.exists() or data.is_symlink():
        STEP("Suppression des données restantes")
        if data.is_dir() and not data.is_symlink():
            shutil.rmtree(data, onexc=ignore_missing)
        else:
            data.unlink(missing_ok=True)
        OK(f"{data} supprimé (ou déjà effacé par qBittorrent).")

    # 3. Le .torrent publié.
    STEP("Retrait du .torrent publié")
    torrent_file.unlink()
    OK(f"{torrent_file} supprimé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
