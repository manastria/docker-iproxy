#!/usr/bin/env python3
"""Installe l'outillage de préparation des torrents sur une clé USB.

La clé n'est qu'un support de transport : tout l'outillage vit dans ce dépôt
et lui est déployé, pour qu'il n'existe qu'une seule version de référence. La
clé n'a besoin ni de `pip install`, ni de binaire tiers — seulement de Python
3.7+, présent d'origine sur Linux et installable en quelques clics sous
Windows.

Elle ne reçoit volontairement AUCUNE adresse du labo : les .torrent qu'elle
produit sont nus, et c'est import_seed.py qui y appose trackers et webseed à
l'arrivée, d'après LAB_HOST_IP (.env). Une clé préparée à la maison reste donc
valable même si le réseau du labo change d'adressage.

Usage :
  python3 provision_usb.py /run/media/<user>/<CLE>
  python3 provision_usb.py /run/media/<user>/<CLE> --dry-run
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from torrent_lib import ERR, HDR, INFO, OK, STEP, WARN  # noqa: E402

REPO = Path(__file__).resolve().parent

# Scripts déployés sur la clé. Volontairement minimal : ni edit_torrent.py ni
# import_seed.py, qui n'ont de sens que sur la machine du labo (ils lisent .env).
TOOLS = ("make_torrent.py", "torrent_lib.py")

# Lanceur Windows : sur la clé, un double-clic doit suffire.
BAT = """@echo off
REM Préparation des torrents — cf. LISEZMOI.txt
REM Usage : build.bat            (traite tous les dossiers de seed\\)
REM         build.bat --init     (crée l'arborescence)
py "%~dp0make_torrent.py" %*
pause
"""

README = """\
Clé de préparation des images de VM — labo BTS
==============================================

Cette clé prépare les images de VM à diffuser aux postes étudiants. Elle est
déployée depuis le dépôt docker-iproxy (provision_usb.py) : ne modifiez pas
les scripts ici, modifiez-les dans le dépôt et redéployez.

Prérequis : Python 3.7 ou plus. Rien d'autre à installer.


UTILISATION
-----------

1. Déposez chaque image dans son propre dossier sous seed/ :

       seed/Xubuntu 2026-09-14/Xubuntu 2026-09-14.ova

   Le nom du dossier devient le nom du torrent. Un dossier par image.

2. Lancez la préparation :

       Windows :  double-cliquez sur build.bat
       Linux   :  python3 make_torrent.py

   Pour chaque dossier, le script calcule les empreintes SHA-256 dans
   MANIFEST.sha256, puis crée torrents/<nom>.torrent. C'est long : il faut
   lire l'intégralité des données deux fois.

3. Sur la machine du labo, dans le dépôt docker-iproxy :

       python3 import_seed.py /chemin/vers/cette/cle

   Copie, revérification, trackers/webseed, publication et mise en seed sont
   enchaînés automatiquement.


À SAVOIR
--------

- Les .torrent produits ici n'ont ni tracker ni webseed : ces adresses
  dépendent du labo et sont ajoutées à l'arrivée, sans changer l'info-hash.
  C'est normal et voulu.

- MANIFEST.sha256 fait partie du contenu du torrent : les étudiants le
  reçoivent et peuvent vérifier leur copie avec

       sha256sum -c MANIFEST.sha256

  Il est calculé une seule fois, AVANT le .torrent. Ne le supprimez pas et ne
  le régénérez pas après coup : cela changerait le contenu, donc l'info-hash,
  et le torrent déjà distribué ne correspondrait plus.

- Pour modifier une image déjà diffusée, créez un nouveau dossier daté plutôt
  que de modifier l'ancien. Un contenu modifié est un autre torrent.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", type=Path, help="Point de montage de la clé USB")
    parser.add_argument("--dry-run", action="store_true",
                        help="Montre ce qui serait écrit, sans rien modifier")
    args = parser.parse_args()

    target: Path = args.target
    if not target.is_dir():
        ERR(f"{target} n'existe pas ou n'est pas un répertoire.")
        ERR("Vérifiez que la clé est bien montée.")
        return 1

    HDR(f"Déploiement vers {target}")

    for name in TOOLS:
        source = REPO / name
        if not source.exists():
            ERR(f"{source} introuvable dans le dépôt")
            return 1
        STEP(f"{name}")
        if not args.dry_run:
            shutil.copy2(source, target / name)

    STEP("build.bat (lanceur Windows)")
    if not args.dry_run:
        (target / "build.bat").write_text(BAT, encoding="utf-8", newline="\r\n")

    STEP("LISEZMOI.txt")
    if not args.dry_run:
        # CRLF : la clé sera lue sous Windows, où le Bloc-notes historique
        # affiche un fichier en LF sur une seule ligne.
        (target / "LISEZMOI.txt").write_text(README, encoding="utf-8", newline="\r\n")

    for sub in ("seed", "torrents"):
        d = target / sub
        if d.exists():
            INFO(f"{sub}/ existe déjà")
        else:
            STEP(f"{sub}/")
            if not args.dry_run:
                d.mkdir(parents=True, exist_ok=True)

    # Reliquats de l'outillage précédent : ils ne sont plus lus, mais laissés
    # en place ils font douter (quel script fait foi ? quel tracker s'applique ?).
    obsolete = [
        ("build_torrents.py", "remplacé par make_torrent.py"),
        ("build_torrents.bat", "remplacé par build.bat"),
        ("check_setup.py", "sans objet : plus aucune dépendance à vérifier"),
        ("rhash.exe", "sans objet : SHA-256 calculé par Python"),
        ("trackers.txt", "sans objet : trackers apposés par import_seed.py"),
    ]
    found = [(name, why) for name, why in obsolete if (target / name).exists()]
    if found:
        print()
        WARN("Fichiers de l'ancien outillage encore présents sur la clé :")
        for name, why in found:
            WARN(f"  {name} — {why}")
        WARN("À supprimer à la main une fois la nouvelle chaîne validée.")

    print()
    if args.dry_run:
        INFO("Essai à blanc : rien n'a été écrit.")
    else:
        OK("Clé prête.")
        print()
        print("  Sur la clé   : déposez vos images dans seed/, puis")
        print("                 build.bat (Windows) ou python3 make_torrent.py (Linux)")
        print(f"  Au labo      : python3 import_seed.py {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
