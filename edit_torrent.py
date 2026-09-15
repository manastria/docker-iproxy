#!/usr/bin/env python3
"""Modifie les trackers et les webseeds (BEP 19) d'un fichier .torrent existant.

Ne touche jamais au dictionnaire `info` : l'info-hash du torrent reste
identique après édition (vérifié à l'écriture), donc le swarm BitTorrent n'est
pas affecté par ce script — seules les métadonnées d'annonce et de secours le
sont.

Outil d'appoint : dans le flux normal, c'est import_seed.py qui appose
trackers et webseed au moment de l'import. Ce script sert aux corrections
après coup (tracker déplacé, port changé, webseed oubliée) et à l'inspection
d'un .torrent avec --show.

Le bencode vient de torrent_lib.py (implémentation maison, sans dépendance).

Usage :
  python3 edit_torrent.py fichier.torrent --show
  python3 edit_torrent.py fichier.torrent --lab --in-place
  python3 edit_torrent.py fichier.torrent --add-tracker udp://tracker:6969/announce
  python3 edit_torrent.py fichier.torrent --set-webseeds http://host:8081/images-vm/ --in-place
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from torrent_lib import (  # noqa: E402
    bdecode, bencode, infohash, load_dotenv, tracker_urls, webseed_url,
)


# --- manipulation des trackers / webseeds ----------------------------------

def enc(url: str) -> bytes:
    return url.encode("utf-8")


def set_trackers(torrent: dict, urls: list[str]) -> None:
    torrent[b"announce"] = enc(urls[0])
    torrent[b"announce-list"] = [[enc(u)] for u in urls]


def add_trackers(torrent: dict, urls: list[str]) -> None:
    tiers = torrent.get(b"announce-list")
    if not tiers:
        existing = torrent.get(b"announce")
        tiers = [[existing]] if existing else []
    tiers.extend([enc(u)] for u in urls)
    torrent[b"announce-list"] = tiers
    torrent.setdefault(b"announce", tiers[0][0])


def set_webseeds(torrent: dict, urls: list[str]) -> None:
    torrent[b"url-list"] = [enc(u) for u in urls]


def add_webseeds(torrent: dict, urls: list[str]) -> None:
    current = torrent.get(b"url-list", [])
    if isinstance(current, bytes):  # forme historique : une seule URL en chaîne
        current = [current]
    torrent[b"url-list"] = current + [enc(u) for u in urls]


# --- affichage ---------------------------------------------------------

def show(torrent: dict) -> None:
    info = torrent[b"info"]
    print(f"Nom       : {info[b'name'].decode()}")
    print(f"Info-hash : {infohash(info)}")

    if b"files" in info:
        total = sum(f[b"length"] for f in info[b"files"])
        print(f"Contenu   : {len(info[b'files'])} fichier(s), {total / 1024**3:.2f} Gio")
    elif b"length" in info:
        print(f"Contenu   : 1 fichier, {info[b'length'] / 1024**3:.2f} Gio")

    tiers = torrent.get(b"announce-list")
    if tiers:
        print("Trackers (par tier, ordre de repli) :")
        for i, tier in enumerate(tiers, 1):
            print(f"  Tier {i}: {', '.join(u.decode() for u in tier)}")
    elif torrent.get(b"announce"):
        print(f"Tracker : {torrent[b'announce'].decode()}")
    else:
        print("Trackers : aucun")

    webseeds = torrent.get(b"url-list")
    if isinstance(webseeds, bytes):
        webseeds = [webseeds]
    if webseeds:
        print("Webseeds (BEP 19) :")
        for u in webseeds:
            print(f"  {u.decode()}")
    else:
        print("Webseeds : aucune")


# --- CLI --------------------------------------------------------------

def parse_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("torrent", help="Fichier .torrent à lire")
    parser.add_argument("-o", "--output", help="Fichier de sortie (défaut : <nom>.edited.torrent)")
    parser.add_argument("--in-place", action="store_true", help="Écrase directement le fichier d'entrée")
    parser.add_argument("--show", action="store_true", help="Affiche l'état actuel (trackers/webseeds)")
    parser.add_argument("--lab", action="store_true",
                        help="Remplace trackers et webseed par ceux du labo (LAB_HOST_IP dans .env)")
    parser.add_argument("--add-tracker", action="append", default=[], metavar="URL",
                        help="Ajoute un tracker dans un nouveau tier (répétable)")
    parser.add_argument("--set-trackers", metavar="URL[,URL...]",
                        help="Remplace tous les trackers (un tier par URL, la première devient announce)")
    parser.add_argument("--add-webseed", action="append", default=[], metavar="URL",
                        help="Ajoute une URL webseed (BEP 19, répétable)")
    parser.add_argument("--set-webseeds", metavar="URL[,URL...]",
                        help="Remplace toutes les webseeds")
    args = parser.parse_args()

    modifying = bool(args.lab or args.set_trackers or args.add_tracker
                     or args.set_webseeds or args.add_webseed)
    if not modifying and not args.show:
        parser.error("Rien à faire : utilisez --show et/ou une option de modification.")

    in_path = Path(args.torrent)
    torrent = bdecode(in_path.read_bytes())
    original_infohash = infohash(torrent[b"info"])

    if args.lab:
        load_dotenv()
        set_trackers(torrent, tracker_urls())
        set_webseeds(torrent, [webseed_url()])
    if args.set_trackers:
        set_trackers(torrent, parse_csv(args.set_trackers))
    if args.add_tracker:
        add_trackers(torrent, args.add_tracker)
    if args.set_webseeds:
        set_webseeds(torrent, parse_csv(args.set_webseeds))
    if args.add_webseed:
        add_webseeds(torrent, args.add_webseed)

    if modifying and infohash(torrent[b"info"]) != original_infohash:
        sys.exit("L'info-hash a changé : le dictionnaire info a été modifié par erreur.")

    show(torrent)

    if not modifying:
        return

    if args.output:
        out_path = Path(args.output)
    elif args.in_place:
        out_path = in_path
    else:
        out_path = in_path.with_name(f"{in_path.stem}.edited{in_path.suffix}")

    out_path.write_bytes(bencode(torrent))
    print(f"\nÉcrit : {out_path}")


if __name__ == "__main__":
    main()
