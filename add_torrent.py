#!/usr/bin/env python3
"""Ajoute un .torrent à qBittorrent (WebUI API) en seed sur les données déjà présentes.

Outil d'appoint : dans le flux normal, c'est import_seed.py qui enchaîne
copie, vérification, trackers/webseed, publication et mise en seed en une
commande. Ce script ne fait que la dernière étape, pour un .torrent dont les
données sont déjà en place sous IMAGES_VM_PATH.

Prérequis : un mot de passe WebUI FIXE doit avoir été défini au moins une fois
(dans qBittorrent : Outils > Options > WebUI > Authentification), puis reporté
dans QBITTORRENT_WEBUI_PASSWORD du fichier .env (cf. docs/qbittorrent.md). Par
défaut, l'image Docker génère un mot de passe temporaire DIFFÉRENT à chaque
démarrage du conteneur (visible via `docker compose logs qbittorrent`) tant
qu'aucun mot de passe fixe n'est enregistré. Avec le mot de passe temporaire,
ce script échoue à l'authentification — sans lien avec le script lui-même.

Usage : python3 add_torrent.py chemin/vers/fichier.torrent
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from torrent_lib import (  # noqa: E402
    QBIT_DEFAULT_URL, QBIT_SAVE_PATH, load_dotenv, qbit_login,
)


def main(torrent_path: str) -> None:
    load_dotenv()
    session = qbit_login(QBIT_DEFAULT_URL)

    with open(torrent_path, "rb") as f:
        r = session.post(
            f"{QBIT_DEFAULT_URL}/api/v2/torrents/add",
            files={"torrents": f},
            data={"savepath": QBIT_SAVE_PATH},
        )
    r.raise_for_status()
    print("Torrent ajouté." if r.text.strip() == "Ok." else f"Réponse inattendue : {r.text}")

    # Vérification immédiate : sans ça, une erreur silencieuse (mauvais savepath,
    # fichiers manquants dans /data) ne se verrait qu'une fois en salle.
    r = session.get(f"{QBIT_DEFAULT_URL}/api/v2/torrents/info")
    for t in r.json():
        print(f"{t['name']!r} -> état: {t['state']}, progression: {t['progress'] * 100:.0f}%")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"Usage : {sys.argv[0]} chemin/vers/fichier.torrent")
    main(sys.argv[1])
