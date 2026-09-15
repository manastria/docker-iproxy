# qBittorrent — mot de passe WebUI

## Le problème du mot de passe temporaire

Tant qu'aucun mot de passe fixe n'a été enregistré, l'image
`linuxserver/qbittorrent` génère un mot de passe temporaire **différent à
chaque démarrage du conteneur** pour l'utilisateur `admin`, affiché une seule
fois dans les logs :

```bash
docker compose logs qbittorrent | grep "temporary password"
```

```
The WebUI administrator password was not set. A temporary password is provided for this session: NWgXKq22B
```

Ce mot de passe ne survit pas à un redémarrage du conteneur : à chaque `docker
compose restart qbittorrent`, un nouveau mot de passe est généré et il faut
retourner consulter les logs. C'est gênant pour un usage manuel, et
totalement bloquant pour `add_torrent.py`, qui a besoin d'un identifiant
stable pour s'authentifier à l'API WebUI.

L'image `linuxserver/qbittorrent` ne fournit **aucune variable
d'environnement** pour définir ou fixer ce mot de passe (vérifié dans sa
documentation officielle) — il n'y a pas de raccourci `WEBUI_PASSWORD` côté
`docker-compose.yml`. Le mot de passe doit être fixé une fois, manuellement,
via la WebUI elle-même.

## Définir un mot de passe fixe

1. Récupérer le mot de passe temporaire dans les logs (commande ci-dessus).
2. Se connecter à la WebUI (`http://<ip-serveur>:8080`) avec `admin` / ce
   mot de passe temporaire.
3. Aller dans **Outils > Options > WebUI > Authentification**, et définir un
   nouveau mot de passe.
4. Une fois enregistré, ce mot de passe devient permanent : il survit aux
   redémarrages du conteneur, et le message de mot de passe temporaire
   n'apparaît plus dans les logs.

## Le stocker dans `.env`

Le mot de passe n'étant pas consommé par le conteneur (l'image ne le permet
pas), il ne peut pas être injecté via `environment:` dans
`docker-compose.yml`. Il sert uniquement à `add_torrent.py`, qui
s'authentifie contre l'API WebUI — c'est donc là qu'il faut le stocker
plutôt qu'en dur dans le script.

Après l'avoir défini dans la WebUI (étape précédente), reportez-le dans
`.env` :

```
QBITTORRENT_WEBUI_PASSWORD=<le mot de passe défini dans la WebUI>
```

`add_torrent.py` le lit automatiquement au démarrage (petit parseur `.env`
intégré, pas de dépendance supplémentaire) et refuse de continuer si la
variable est absente ou laissée à sa valeur d'exemple.

### `.env` vs `.env.sample`

`.env` contient ce secret : il est ignoré par git (`.gitignore`) et ne doit
jamais être commité. `.env.sample`, lui, est versionné — c'est le template à
copier (`cp .env.sample .env`) sur une nouvelle installation, avec des
valeurs d'exemple à remplacer. Toute nouvelle variable ajoutée à `.env` doit
être répercutée dans `.env.sample` (sans sa valeur réelle) pour rester le
reflet fidèle de ce qu'un déploiement attend.

## Contrat de l'API de login : versions récentes vs historiques

La documentation officielle de l'API WebUI décrit `/api/v2/auth/login` comme
répondant toujours HTTP 200, avec un corps `Ok.` ou `Fails.` selon le
résultat. Ce n'est plus vrai à partir de qBittorrent 5.x (observé en 5.2.3,
image `linuxserver/qbittorrent`) : la connexion répond par un code HTTP
standard, `204 No Content` (corps vide) sur succès et `401 Unauthorized` sur
échec.

`torrent_lib.qbit_login()` (utilisé par `import_seed.py` et `add_torrent.py`)
accepte les deux contrats. Sans ça, un login qui a **réussi** (204, corps
vide) serait pris pour un échec — symptôme observé : le script affiche
`Authentification refusée par qBittorrent ('')`, avec des identifiants pourtant
corrects. Si ce message revient avec un `''` (et non `HTTP 401, 'Unauthorized'`
ou similaire), c'est ce contrat qui a probablement encore changé de forme
dans une version plus récente de qBittorrent.

## Réinitialiser le mot de passe (mot de passe fixe perdu)

Si le mot de passe fixe est perdu, le seul moyen de revenir à un mot de passe
temporaire (relisible dans les logs) est de supprimer la clé correspondante
du fichier de configuration persistant, puis de redémarrer le conteneur :

```bash
docker compose stop qbittorrent
grep -v '^WebUI\\Password_PBKDF2=' \
  qbittorrent/config/qBittorrent/qBittorrent.conf > /tmp/qbt.conf \
  && mv /tmp/qbt.conf qbittorrent/config/qBittorrent/qBittorrent.conf
docker compose up -d qbittorrent
docker compose logs qbittorrent | grep "temporary password"
```

Puis reprendre la procédure de définition d'un mot de passe fixe ci-dessus,
et mettre à jour `.env` en conséquence.
