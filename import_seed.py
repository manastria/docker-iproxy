#!/usr/bin/env python3
"""Importe une image de VM préparée (clé USB) et la met en seed sur qBittorrent.

C'est le chaînon entre la phase « préparation » (make_torrent.py, typiquement
sur une clé USB) et la pile docker de ce dépôt. À lancer sur la machine du
labo, depuis la racine du dépôt.

Enchaîne, pour chaque image :
  1. vérifie l'intégrité sur la source d'après MANIFEST.sha256 ;
  2. copie le dossier vers IMAGES_VM_PATH/<nom>/ ;
  3. re-vérifie l'intégrité APRÈS copie — une clé USB fatiguée ou un câble
     douteux se voient ici, pas devant trente étudiants ;
  4. appose trackers et webseed d'après LAB_HOST_IP (l'info-hash ne change
     pas : ces clés sont hors du dictionnaire `info`) ;
  5. publie le .torrent dans ./torrents (servi par torrents-http) ;
  6. ajoute le torrent à qBittorrent en seed sur les données déjà copiées ;
  7. confirme que qBittorrent le voit bien à 100 % et en train de seeder.

Usage :
  python3 import_seed.py /run/media/<user>/<CLE>
  python3 import_seed.py /run/media/<user>/<CLE> --only "Xubuntu 2026-09-14"
  python3 import_seed.py /run/media/<user>/<CLE> --dry-run
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from torrent_lib import (  # noqa: E402
    ERR, HDR, INFO, OK, STEP, WARN,
    QBIT_DEFAULT_URL, QBIT_SAVE_PATH, bdecode, bencode, human, infohash,
    load_dotenv, qbit_login, tracker_urls, verify_manifest, webseed_url,
)

REPO = Path(__file__).resolve().parent
PUBLISHED_TORRENTS = REPO / "torrents"   # monté dans torrents-http (/torrents/)


# --- étapes ----------------------------------------------------------------

def copy_tree(src: Path, dest: Path) -> None:
    """Copie src vers dest en affichant la progression globale."""
    total = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
    copied = 0
    started = time.time()
    tty = sys.stdout.isatty()

    for item in sorted(src.rglob("*")):
        rel = item.relative_to(src)
        target = dest / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied += item.stat().st_size
        if tty and total:
            rate = copied / max(time.time() - started, 0.001)
            print(f"      {copied / total * 100:5.1f} %  {human(copied)} / {human(total)}"
                  f"  ({human(rate)}/s)", end="\r", flush=True)
    if tty:
        print(" " * 78, end="\r")


def stamp_torrent(torrent_path: Path, out_path: Path) -> str:
    """Écrit dans out_path le .torrent muni des trackers/webseed du labo.

    Le dictionnaire `info` n'est jamais touché : l'info-hash reste celui
    calculé à la préparation, donc un .torrent déjà distribué reste compatible
    avec celui-ci (même swarm).
    """
    torrent = bdecode(torrent_path.read_bytes())
    before = infohash(torrent[b"info"])

    trackers = tracker_urls()
    torrent[b"announce"] = trackers[0].encode("utf-8")
    torrent[b"announce-list"] = [[t.encode("utf-8")] for t in trackers]
    torrent[b"url-list"] = [webseed_url().encode("utf-8")]

    after = infohash(torrent[b"info"])
    if before != after:
        raise SystemExit(
            f"L'info-hash a changé ({before} -> {after}) : le dictionnaire "
            "info a été modifié par erreur. Import interrompu."
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bencode(torrent))
    return after


# --- client qBittorrent ----------------------------------------------------

def qbit_add(session, base_url: str, torrent_path: Path, name: str) -> bool:
    """Ajoute le .torrent en seed, puis confirme son état. False si échec.

    Là encore (cf. qbit_login dans torrent_lib.py), le contrat de cette route
    a changé avec les versions récentes de qBittorrent (5.2.3, observé ici) :
    un ajout réussi répond 200 avec un corps JSON
    (`{"added_torrent_ids": [...], "success_count": 1, "failure_count": 0, ...}`)
    et non plus le texte `"Ok."`. Un doublon (import relancé sur un torrent déjà
    présent) répond 409 Conflict : ce n'est pas un échec, `import_seed.py` doit
    rester rejouable sans planter. Un fichier .torrent invalide répond 415.
    """
    with torrent_path.open("rb") as f:
        r = session.post(
            f"{base_url}/api/v2/torrents/add",
            files={"torrents": (torrent_path.name, f, "application/x-bittorrent")},
            data={"savepath": QBIT_SAVE_PATH, "skip_checking": "false"},
        )

    if r.status_code == 409:
        INFO("Déjà présent dans qBittorrent (import rejoué) — pas un échec")
    elif r.status_code == 200:
        try:
            result = r.json()
        except ValueError:
            result = None
        added = result is not None and result.get("success_count", 0) >= 1
        if not added:
            ERR(f"qBittorrent a refusé le torrent : {r.text.strip()!r}")
            return False
    else:
        detail = f"HTTP {r.status_code}"
        if r.text.strip():
            detail += f", {r.text.strip()!r}"
        ERR(f"qBittorrent a refusé le torrent : {detail}")
        return False

    # Vérification effective : qBittorrent doit retrouver les données dans
    # /data et passer en seed. Il commence par vérifier les pièces, ce qui
    # prend un moment sur plusieurs gigaoctets — on lui laisse le temps.
    STEP("Contrôle des pièces par qBittorrent (peut durer quelques minutes)")
    deadline = time.time() + 900
    last_state = ""
    while time.time() < deadline:
        info = session.get(f"{base_url}/api/v2/torrents/info").json()
        entry = next((t for t in info if t["name"] == name), None)
        if entry is None:
            time.sleep(2)
            continue
        state, progress = entry["state"], entry["progress"]
        if state != last_state:
            last_state = state
            INFO(f"état : {state} — {progress * 100:.0f} %")
        # « ...UP » = torrent complet, en phase d'envoi, quelle que soit la
        # nuance (en pause, en file d'attente, sans pair connecté...).
        # `stoppedUP` a remplacé `pausedUP` à partir de qBittorrent 5, d'où le
        # test sur le suffixe plutôt qu'une liste figée. `checkingUP` fait
        # exception : le contrôle des pièces est encore en cours.
        if state.endswith("UP") and state != "checkingUP":
            OK(f"En seed ({progress * 100:.0f} %) — état {state}")
            return True
        if state in ("error", "missingFiles"):
            ERR(f"qBittorrent signale : {state}")
            ERR("Les données ne correspondent pas au torrent, ou sont introuvables")
            ERR(f"dans {QBIT_SAVE_PATH}/{name} vu du conteneur.")
            return False
        time.sleep(3)

    WARN("Toujours pas en seed après 15 minutes — à vérifier dans la WebUI")
    return False


# --- traitement d'une image ------------------------------------------------

def import_one(src: Path, torrent_src: Path, images_dir: Path, args, session, base_url) -> bool:
    HDR(src.name)
    dest = images_dir / src.name

    # 1. Intégrité à la source
    STEP(f"Vérification de l'intégrité sur la source ({src})")
    if not verify_manifest(src, report=lambda m: print(f"    {m}")):
        ERR("Intégrité non conforme à la source : import abandonné")
        return False
    OK("Intégrité conforme à la source")

    total = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())

    if args.dry_run:
        INFO(f"[essai] copierait {human(total)} vers {dest}")
        INFO(f"[essai] publierait {torrent_src.name} dans {PUBLISHED_TORRENTS}")
        INFO(f"[essai] trackers : {', '.join(tracker_urls())}")
        INFO(f"[essai] webseed  : {webseed_url()}")
        return True

    # 2. Copie
    if dest.exists() and not args.force:
        INFO(f"{dest} existe déjà — copie ignorée (--force pour recopier)")
    else:
        STEP(f"Copie de {human(total)} vers {dest}")
        if dest.exists():
            shutil.rmtree(dest)
        copy_tree(src, dest)
        OK("Copie terminée")

    # 3. Re-vérification après copie
    STEP("Vérification de l'intégrité APRÈS copie")
    if not verify_manifest(dest, report=lambda m: print(f"    {m}")):
        ERR("La copie est altérée : ne pas mettre en seed dans cet état.")
        ERR(f"Supprimez {dest} et relancez l'import.")
        return False
    OK("Copie conforme à la source")

    # 4-5. Trackers/webseed, puis publication
    published = PUBLISHED_TORRENTS / torrent_src.name
    STEP("Apposition des trackers et de la webseed du labo")
    ih = stamp_torrent(torrent_src, published)
    for t in tracker_urls():
        INFO(f"tracker : {t}")
    INFO(f"webseed : {webseed_url()}")
    OK(f"Publié dans {published} — info-hash inchangé ({ih})")

    # 6-7. Mise en seed
    if args.no_seed:
        INFO("--no-seed : mise en seed non effectuée")
        return True
    STEP("Ajout à qBittorrent en seed")
    return qbit_add(session, base_url, published, src.name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path,
                        help="Racine de la clé de préparation (contenant seed/ et torrents/)")
    parser.add_argument("--only", metavar="NOM", action="append", default=[],
                        help="N'importe que cette image (répétable)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Montre ce qui serait fait, sans rien copier ni ajouter")
    parser.add_argument("--force", action="store_true",
                        help="Recopie même si la destination existe déjà")
    parser.add_argument("--no-seed", action="store_true",
                        help="Copie et publie, mais n'ajoute rien à qBittorrent")
    parser.add_argument("--qbit-url", default=QBIT_DEFAULT_URL,
                        help="URL de la WebUI qBittorrent (défaut : http://localhost:8080)")
    args = parser.parse_args()

    load_dotenv()

    images_path = os.environ.get("IMAGES_VM_PATH", "").strip()
    if not images_path or images_path.startswith("/chemin/"):
        ERR("IMAGES_VM_PATH n'est pas renseigné dans .env (cf. .env.sample).")
        return 1
    images_dir = Path(images_path)
    if not images_dir.is_dir():
        ERR(f"IMAGES_VM_PATH pointe vers {images_dir}, qui n'existe pas.")
        ERR("Créez ce répertoire avant de lancer l'import (il est monté en")
        ERR("lecture seule dans qbittorrent et torrents-http).")
        return 1

    seed_dir = args.source / "seed"
    torrents_dir = args.source / "torrents"
    if not seed_dir.is_dir() or not torrents_dir.is_dir():
        ERR(f"{args.source} ne ressemble pas à une clé de préparation :")
        ERR("elle doit contenir seed/ et torrents/ (cf. make_torrent.py --init).")
        return 1

    INFO(f"Source       : {args.source}")
    INFO(f"Destination  : {images_dir}  (IMAGES_VM_PATH)")
    INFO(f"Publication  : {PUBLISHED_TORRENTS}")
    INFO(f"Hôte du labo : {os.environ.get('LAB_HOST_IP', '(non défini)')}  (LAB_HOST_IP)")

    # Une image est importable si elle a À LA FOIS un dossier source et son
    # .torrent : sans le .torrent, rien à publier ; sans le dossier, rien à seeder.
    sources = sorted(p for p in seed_dir.iterdir() if p.is_dir())
    if args.only:
        wanted = set(args.only)
        sources = [p for p in sources if p.name in wanted]
        missing = sorted(wanted - {p.name for p in sources})
        for name in missing:
            ERR(f"Image introuvable dans {seed_dir} : {name}")
        if missing:
            return 1

    pairs = []
    for src in sources:
        torrent = torrents_dir / f"{src.name}.torrent"
        if not torrent.exists():
            WARN(f"{src.name} : pas de .torrent dans {torrents_dir} — ignoré")
            WARN("  (lancez make_torrent.py sur la clé pour le créer)")
            continue
        pairs.append((src, torrent))

    if not pairs:
        ERR("Aucune image importable.")
        return 1

    session = base_url = None
    if not args.no_seed and not args.dry_run:
        base_url = args.qbit_url.rstrip("/")
        session = qbit_login(base_url)
        OK(f"Authentifié sur la WebUI qBittorrent ({base_url})")

    failed = [src.name for src, torrent in pairs
              if not import_one(src, torrent, images_dir, args, session, base_url)]

    HDR("Récapitulatif")
    print(f"  Images traitées : {len(pairs)}")
    print(f"  En échec        : {len(failed)}")
    for name in failed:
        ERR(f"  {name}")
    if not failed and not args.dry_run:
        port = os.environ.get("TORRENTS_HTTP_PORT", "8081")
        host = os.environ.get("LAB_HOST_IP", "<ip>")
        print()
        print("  Les postes étudiants récupèrent les .torrent sur :")
        print(f"    http://{host}:{port}/torrents/")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
