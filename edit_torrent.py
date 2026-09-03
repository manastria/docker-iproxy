#!/usr/bin/env python3
"""Modifie les trackers et les webseeds (BEP 19) d'un fichier .torrent existant.

Ne touche jamais au dictionnaire `info` : l'info-hash du torrent reste
identique après édition (vérifié par une assertion à l'écriture), donc le
swarm BitTorrent n'est pas affecté par ce script, seuls les métadonnées
d'annonce/de secours le sont.

Implémentation bencode maison (lecture/écriture), sans dépendance externe —
même logique que le petit parseur .env de add_torrent.py.

Usage :
  python3 edit_torrent.py fichier.torrent --show
  python3 edit_torrent.py fichier.torrent --add-tracker udp://tracker:6969/announce
  python3 edit_torrent.py fichier.torrent --set-webseeds http://host:8081/images-vm/ --in-place
"""
import argparse
import hashlib
import sys
from pathlib import Path


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
    return hashlib.sha1(bencode(info)).hexdigest()


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
    print(f"Info-hash : {infohash(torrent[b'info'])}")

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
    parser.add_argument("--add-tracker", action="append", default=[], metavar="URL",
                         help="Ajoute un tracker dans un nouveau tier (répétable)")
    parser.add_argument("--set-trackers", metavar="URL[,URL...]",
                         help="Remplace tous les trackers (un tier par URL, la première devient announce)")
    parser.add_argument("--add-webseed", action="append", default=[], metavar="URL",
                         help="Ajoute une URL webseed (BEP 19, répétable)")
    parser.add_argument("--set-webseeds", metavar="URL[,URL...]",
                         help="Remplace toutes les webseeds")
    args = parser.parse_args()

    modifying = bool(args.set_trackers or args.add_tracker or args.set_webseeds or args.add_webseed)
    if not modifying and not args.show:
        parser.error("Rien à faire : utilisez --show et/ou une option de modification.")

    in_path = Path(args.torrent)
    torrent = bdecode(in_path.read_bytes())
    original_infohash = infohash(torrent[b"info"])

    if args.set_trackers:
        set_trackers(torrent, parse_csv(args.set_trackers))
    if args.add_tracker:
        add_trackers(torrent, args.add_tracker)
    if args.set_webseeds:
        set_webseeds(torrent, parse_csv(args.set_webseeds))
    if args.add_webseed:
        add_webseeds(torrent, args.add_webseed)

    if modifying:
        assert infohash(torrent[b"info"]) == original_infohash, \
            "L'info-hash a changé : le dictionnaire info a été modifié par erreur."

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
