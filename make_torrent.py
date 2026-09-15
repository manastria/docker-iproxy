#!/usr/bin/env python3
"""Prépare les images de VM à diffuser : MANIFEST.sha256 puis fichier .torrent.

C'est l'outil de la phase « préparation », typiquement lancé depuis la clé USB
(cf. provision_usb.py et docs/torrents.md), à la maison ou sur la machine du
labo. Il ne dépend que de la bibliothèque standard : ni py3createtorrent, ni
rhash, ni pip.

Pour chaque sous-dossier de seed/ :
  1. génère MANIFEST.sha256 s'il est absent, sinon vérifie l'intégrité ;
  2. crée torrents/<nom>.torrent s'il est absent.

Les .torrent produits sont volontairement « nus » : ni tracker, ni webseed. Ces
adresses dépendent du labo, pas du contenu, et sont apposées à l'arrivée par
import_seed.py d'après LAB_HOST_IP (.env) — sans changer l'info-hash. Un
.torrent préparé à la maison reste donc valable même si l'IP du labo change.
Utilisez --tracker/--webseed pour les inscrire malgré tout dès la création.

Usage :
  python3 make_torrent.py                  # traite tous les dossiers de seed/
  python3 make_torrent.py --init           # crée l'arborescence seed/ + torrents/
  python3 make_torrent.py --verify-only    # vérifie l'intégrité, ne crée rien
  python3 make_torrent.py --force          # recrée les .torrent déjà présents
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from torrent_lib import (  # noqa: E402
    ERR, HDR, INFO, OK, STEP, WARN,
    MANIFEST_NAME, bencode, build_info, human, infohash,
    verify_manifest, write_manifest,
)


def build_one(src: Path, out: Path, trackers: list[str], webseeds: list[str]) -> str:
    """Crée le .torrent de `src` dans `out`. Retourne l'info-hash."""
    started = time.time()
    last = [started]

    def progress(done: int, total: int) -> None:
        now = time.time()
        if now - last[0] < 2:
            return
        last[0] = now
        rate = done / max(now - started, 0.001)
        pct = done / total * 100 if total else 100
        print(f"      {pct:5.1f} %  {human(done)} / {human(total)}  ({human(rate)}/s)",
              end="\r", flush=True)

    # Hors terminal (journal, redirection), le retour chariot n'efface rien :
    # on se tait plutôt que de noyer la sortie sous des lignes de progression.
    info = build_info(src, progress=progress if sys.stdout.isatty() else None)
    if sys.stdout.isatty():
        print(" " * 78, end="\r")  # efface la ligne de progression

    torrent: dict = {b"info": info}
    if trackers:
        torrent[b"announce"] = trackers[0].encode("utf-8")
        torrent[b"announce-list"] = [[t.encode("utf-8")] for t in trackers]
    if webseeds:
        torrent[b"url-list"] = [w.encode("utf-8") for w in webseeds]
    torrent[b"creation date"] = int(time.time())
    torrent[b"created by"] = b"make_torrent.py (docker-iproxy)"
    torrent[b"comment"] = f"Image de VM du labo - {src.name}".encode("utf-8")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bencode(torrent))
    return infohash(info)


def process(src: Path, torrents_dir: Path, args) -> bool:
    """Traite un dossier source. Retourne False en cas d'échec."""
    HDR(src.name)
    manifest = src / MANIFEST_NAME

    # 1. MANIFEST : généré une seule fois, avant le torrent.
    #    Le régénérer après coup changerait le contenu, donc l'info-hash.
    if not manifest.exists():
        STEP("MANIFEST.sha256 absent -> calcul des empreintes SHA-256")
        count = write_manifest(src)
        OK(f"MANIFEST.sha256 écrit ({count} fichier(s))")
    else:
        STEP("Vérification de l'intégrité d'après MANIFEST.sha256")
        if not verify_manifest(src, report=lambda m: print(f"    {m}")):
            ERR("Intégrité non conforme -> aucun torrent créé pour ce dossier")
            return False
        OK("Intégrité conforme")

    if args.verify_only:
        return True

    # 2. Torrent
    out = torrents_dir / f"{src.name}.torrent"
    if out.exists() and not args.force:
        OK(f"{out.name} existe déjà (--force pour le recréer)")
        return True

    total = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
    STEP(f"Création de {out.name} ({human(total)} à hacher)")
    ih = build_one(src, out, args.tracker, args.webseed)
    OK(f"{out.name} créé — info-hash {ih}")
    if not args.tracker and not args.webseed:
        INFO("Torrent nu : tracker et webseed seront apposés par import_seed.py")
    return True


def init_structure(seed_dir: Path, torrents_dir: Path) -> int:
    HDR("Initialisation de l'arborescence de préparation")
    for d in (seed_dir, torrents_dir):
        if d.exists():
            INFO(f"{d.name}/ existe déjà")
        else:
            d.mkdir(parents=True, exist_ok=True)
            OK(f"{d.name}/ créé")
    print()
    print("Étapes suivantes :")
    print(f"  1. Créez un dossier par image dans {seed_dir.name}/,")
    print(f"     par exemple : {seed_dir.name}/Xubuntu 2026-09-14/")
    print("     (le nom du dossier devient le nom du torrent)")
    print(f"  2. Lancez : python3 {Path(__file__).name}")
    print(f"  3. Les .torrent apparaissent dans {torrents_dir.name}/")
    print("  4. Sur la machine du labo : python3 import_seed.py <chemin de la clé>")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="Répertoire de travail contenant seed/ et torrents/ (défaut : dossier courant)")
    parser.add_argument("--init", action="store_true",
                        help="Crée l'arborescence seed/ + torrents/ puis quitte")
    parser.add_argument("--verify-only", action="store_true",
                        help="Vérifie l'intégrité des dossiers sans créer de .torrent")
    parser.add_argument("--force", action="store_true",
                        help="Recrée les .torrent même s'ils existent déjà")
    parser.add_argument("--only", metavar="NOM", action="append", default=[],
                        help="Ne traite que ce dossier de seed/ (répétable)")
    parser.add_argument("--tracker", metavar="URL", action="append", default=[],
                        help="Inscrit un tracker dès la création (répétable ; normalement inutile)")
    parser.add_argument("--webseed", metavar="URL", action="append", default=[],
                        help="Inscrit une webseed dès la création (répétable ; normalement inutile)")
    args = parser.parse_args()

    root: Path = args.root.resolve()
    seed_dir = root / "seed"
    torrents_dir = root / "torrents"

    if args.init:
        return init_structure(seed_dir, torrents_dir)

    INFO(f"Répertoire de travail : {root}")
    if not seed_dir.is_dir():
        ERR(f"{seed_dir} introuvable.")
        ERR(f"Créez l'arborescence avec : python3 {Path(__file__).name} --init")
        return 1

    sources = sorted(p for p in seed_dir.iterdir() if p.is_dir())
    if args.only:
        wanted = set(args.only)
        sources = [p for p in sources if p.name in wanted]
        missing = wanted - {p.name for p in sources}
        for name in sorted(missing):
            ERR(f"Dossier introuvable dans seed/ : {name}")
        if missing:
            return 1
    if not sources:
        WARN(f"Aucun dossier à traiter dans {seed_dir}")
        return 0

    torrents_dir.mkdir(parents=True, exist_ok=True)
    failed = [src.name for src in sources if not process(src, torrents_dir, args)]

    HDR("Récapitulatif")
    print(f"  Dossiers traités : {len(sources)}")
    print(f"  En échec         : {len(failed)}")
    for name in failed:
        ERR(f"  {name}")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
