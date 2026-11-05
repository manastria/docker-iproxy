#!/usr/bin/env python3
"""Vérifie la cohérence entre les .torrent publiés, les données et qBittorrent.

Usage : python3 check_torrents.py [--no-qbit] [--qbit-url URL]

Trois inventaires sont croisés :
  - les .torrent publiés dans ./torrents (servis par torrents-http) ;
  - les données sous IMAGES_VM_PATH (une entrée par torrent, nommée d'après le
    nom interne du torrent) ;
  - les torrents connus de qBittorrent (identifiés par info-hash).

Anomalies recherchées :
  - .torrent sans données, ou dont les fichiers sont absents / de mauvaise taille ;
  - .torrent que qBittorrent ne connaît pas, ou qui n'est pas en seed ;
  - données sans .torrent (candidates à la suppression, cf. remove_torrent.py) ;
  - torrent qBittorrent sans .torrent publié.

Lecture seule : rien n'est modifié. Code de sortie 0 si tout est cohérent,
1 s'il y a au moins une anomalie. --no-qbit saute la partie qBittorrent
(utile si la WebUI n'est pas joignable).
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from torrent_lib import (  # noqa: E402
    ERR, HDR, INFO, OK, QBIT_DEFAULT_URL, WARN,
    bdecode, human, infohash, load_dotenv, qbit_login,
)

REPO = Path(__file__).resolve().parent
PUBLISHED_TORRENTS = REPO / "torrents"

# États qBittorrent où le torrent est complet et diffuse (ou peut diffuser).
SEEDING_STATES = {"uploading", "stalledUP", "queuedUP", "forcedUP"}
# Complet mais ne diffuse pas actuellement : à signaler sans être une panne.
IDLE_STATES = {"pausedUP", "stoppedUP", "checkingUP"}


def expected_files(info: dict) -> list[tuple[str, int]]:
    """Liste (chemin relatif au dossier de données, taille) attendue par le torrent."""
    name = info[b"name"].decode("utf-8")
    if b"files" not in info:
        return [(name, info[b"length"])]
    return [
        (name + "/" + "/".join(p.decode("utf-8") for p in f[b"path"]), f[b"length"])
        for f in info[b"files"]
    ]


def check_data(images_dir: Path, info: dict) -> list[str]:
    """Problèmes de données pour un torrent (liste vide si tout est en place)."""
    problems = []
    for rel, size in expected_files(info):
        path = images_dir / rel
        if not path.is_file():
            problems.append(f"fichier manquant : {rel}")
        elif path.stat().st_size != size:
            problems.append(
                f"taille différente : {rel} ({human(path.stat().st_size)} "
                f"au lieu de {human(size)})")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-qbit", action="store_true",
                        help="Ne contacte pas qBittorrent (contrôle des fichiers seul)")
    parser.add_argument("--qbit-url", default=QBIT_DEFAULT_URL,
                        help="URL de la WebUI qBittorrent (défaut : http://localhost:8080)")
    args = parser.parse_args()

    load_dotenv()
    images_path = os.environ.get("IMAGES_VM_PATH", "").strip()
    if not images_path:
        ERR("IMAGES_VM_PATH n'est pas renseigné dans .env (cf. .env.sample).")
        return 2
    images_dir = Path(images_path).resolve()
    if not images_dir.is_dir():
        ERR(f"IMAGES_VM_PATH pointe vers {images_dir}, qui n'existe pas.")
        return 2

    qbit = {}
    if not args.no_qbit:
        session = qbit_login(args.qbit_url)
        r = session.get(f"{args.qbit_url}/api/v2/torrents/info")
        r.raise_for_status()
        qbit = {t["hash"].lower(): t for t in r.json()}

    anomalies = 0

    def anomaly(msg: str) -> None:
        nonlocal anomalies
        anomalies += 1
        ERR(msg)

    HDR("Torrents publiés")
    known_hashes: set[str] = set()
    known_names: set[str] = set()
    for tf in sorted(PUBLISHED_TORRENTS.glob("*.torrent")):
        try:
            info = bdecode(tf.read_bytes())[b"info"]
            ih = infohash(info)
            content_name = info[b"name"].decode("utf-8")
        except (ValueError, KeyError, UnicodeDecodeError) as e:
            anomaly(f"{tf.name} : .torrent illisible ({e})")
            continue
        known_hashes.add(ih)
        known_names.add(content_name)

        problems = []
        if content_name != tf.stem:
            problems.append(
                f"nom interne {content_name!r} différent du nom du fichier")
        if not (images_dir / content_name).exists():
            problems.append(f"aucune donnée sous {images_dir / content_name}")
        else:
            problems += check_data(images_dir, info)

        if not args.no_qbit:
            t = qbit.get(ih)
            if t is None:
                problems.append("inconnu de qBittorrent (pas de seed)")
            elif t["state"] in SEEDING_STATES and t["progress"] >= 1:
                pass
            elif t["state"] in IDLE_STATES and t["progress"] >= 1:
                WARN(f"{tf.name} : complet mais état « {t['state']} » (ne diffuse pas)")
            else:
                problems.append(
                    f"qBittorrent : état « {t['state']} », "
                    f"progression {t['progress'] * 100:.0f} %")

        if problems:
            for p in problems:
                anomaly(f"{tf.name} : {p}")
        else:
            OK(f"{tf.name}")

    HDR("Données sans .torrent")
    orphans = [
        p for p in sorted(images_dir.iterdir())
        if not p.name.startswith(".") and p.name not in known_names
    ]
    if orphans:
        for p in orphans:
            anomaly(f"{p.name} : aucun .torrent publié "
                    f"(supprimable avec remove_torrent.py si obsolète)")
    else:
        OK("Aucune.")

    if not args.no_qbit:
        HDR("Torrents qBittorrent sans .torrent")
        stray = [t for h, t in qbit.items() if h not in known_hashes]
        if stray:
            for t in stray:
                anomaly(f"{t['name']!r} ({t['hash']}) : absent de {PUBLISHED_TORRENTS}")
        else:
            OK("Aucun.")

    print()
    if anomalies:
        ERR(f"{anomalies} anomalie(s).")
        return 1
    OK("Tout est cohérent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
