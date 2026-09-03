#!/usr/bin/env python3
"""Ajoute un .torrent à qBittorrent (WebUI API) en seed sur les données déjà présentes.

Prérequis : un mot de passe WebUI FIXE doit avoir été défini au moins une fois
(dans qBittorrent : Outils > Options > WebUI > Authentification), puis reporté
dans QBITTORRENT_WEBUI_PASSWORD du fichier .env (cf. docs/qbittorrent.md). Par
défaut, l'image Docker génère un mot de passe temporaire DIFFÉRENT à chaque
démarrage du conteneur (visible via `docker logs qbittorrent`) tant qu'aucun
mot de passe fixe n'est enregistré. Avec le mot de passe temporaire, ce script
échoue à l'authentification — sans lien avec le script lui-même.

Usage : python3 add_torrent.py chemin/vers/fichier.torrent
"""
import os
import sys
from pathlib import Path

import requests

QBIT_URL = "http://localhost:8080"  # à adapter si le script ne tourne pas sur la machine prof
USERNAME = "admin"
SAVE_PATH = "/data"  # chemin vu par le conteneur, correspond au volume .../images-vm:/data


def load_dotenv(path: Path = Path(__file__).parent / ".env") -> None:
    """Charge les variables de .env dans l'environnement (sans écraser l'existant)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main(torrent_path: str) -> None:
    load_dotenv()
    password = os.environ.get("QBITTORRENT_WEBUI_PASSWORD")
    if not password or password == "à-définir":
        sys.exit(
            "QBITTORRENT_WEBUI_PASSWORD n'est pas défini dans .env.\n"
            "Définissez un mot de passe fixe dans la WebUI (Outils > Options > WebUI),\n"
            "puis reportez-le dans .env (cf. docs/qbittorrent.md)."
        )

    session = requests.Session()

    r = session.post(
        f"{QBIT_URL}/api/v2/auth/login",
        data={"username": USERNAME, "password": password},
    )
    r.raise_for_status()
    if r.text != "Ok.":
        sys.exit(
            "Échec de connexion à l'API qBittorrent.\n"
            "Vérifiez qu'un mot de passe FIXE est bien défini dans la WebUI\n"
            "(sinon le mot de passe change à chaque redémarrage du conteneur)."
        )

    with open(torrent_path, "rb") as f:
        r = session.post(
            f"{QBIT_URL}/api/v2/torrents/add",
            files={"torrents": f},
            data={"savepath": SAVE_PATH},
        )
    r.raise_for_status()
    print("Torrent ajouté." if r.text == "Ok." else f"Réponse inattendue : {r.text}")

    # Vérification immédiate : sans ça, une erreur silencieuse (mauvais savepath,
    # fichiers manquants dans /data) ne se verrait qu'une fois en salle.
    r = session.get(f"{QBIT_URL}/api/v2/torrents/info")
    for t in r.json():
        print(f"{t['name']!r} -> état: {t['state']}, progression: {t['progress'] * 100:.0f}%")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"Usage : {sys.argv[0]} chemin/vers/fichier.torrent")
    main(sys.argv[1])
