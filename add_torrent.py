#!/usr/bin/env python3
"""Ajoute un .torrent à qBittorrent (WebUI API) en seed sur les données déjà présentes.

Prérequis : un mot de passe WebUI FIXE doit avoir été défini au moins une fois
(dans qBittorrent : Outils > Options > WebUI > Authentification). Par défaut,
l'image Docker génère un mot de passe temporaire DIFFÉRENT à chaque démarrage
du conteneur (visible via `docker logs qbittorrent`) tant qu'aucun mot de passe
fixe n'est enregistré. Avec le mot de passe temporaire, ce script échoue à
l'authentification — sans lien avec le script lui-même.

Usage : python3 add_torrent.py chemin/vers/fichier.torrent
"""
import sys
import requests

QBIT_URL = "http://localhost:8080"  # à adapter si le script ne tourne pas sur la machine prof
USERNAME = "admin"
PASSWORD = "à-remplacer-par-le-mot-de-passe-fixe-défini-dans-la-WebUI"
SAVE_PATH = "/data"  # chemin vu par le conteneur, correspond au volume .../images-vm:/data


def main(torrent_path: str) -> None:
    session = requests.Session()

    r = session.post(
        f"{QBIT_URL}/api/v2/auth/login",
        data={"username": USERNAME, "password": PASSWORD},
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
