# CLAUDE.md

Ce fichier fournit des indications à Claude Code (claude.ai/code) pour travailler sur le code de ce dépôt.

## Contexte

Ce dépôt fait fonctionner le laboratoire informatique d'une section de BTS informatique.
Il déploie une pile de conteneurs Docker fournissant des services de
cache/proxy locaux, afin que les nombreuses machines clientes du labo (PC/VM des
étudiants) n'aient pas chacune à passer directement par le proxy Squid de
l'établissement pour accéder à internet. Il n'y a pas de code applicatif à
compiler, linter ou tester ici — il s'agit uniquement de configuration
d'infrastructure.

## Commandes

Démarrer/arrêter les services (depuis la racine du dépôt, là où se trouve
`docker-compose.yml`) :
```
docker compose up -d
docker compose down
docker compose logs -f <service>   # ex. docker-registry-cache, apt-cache
docker compose restart <service>
```

Il n'y a ni build, ni linter, ni suite de tests. Les modifications se font
directement dans le fichier compose et les fichiers de configuration des
services qu'il monte, puis sont appliquées avec `docker compose up -d` (ce qui
ne recrée que les services modifiés).

## Architecture

Cinq services indépendants définis dans `docker-compose.yml`, qui récupèrent
tous le contenu distant via le proxy Squid amont du labo (`SQUID_PROXY_ADDR` /
`SQUID_NO_PROXY` dans `.env`, ou en dur dans sa propre config pour apt-cache —
voir plus bas) :

- **docker-registry-cache** (`registry:2`) — cache/miroir pull-through pour
  Docker Hub. Configuré via `config.yml`, monté en lecture seule dans le
  conteneur ; son `proxy.remoteurl` pointe vers `https://registry-1.docker.io`.
  Les couches d'images mises en cache persistent dans `./docker-cache` (bind
  mount, ignoré par git). Écoute sur le port `5000`.
- **apt-cache** — proxy de cache pour les téléchargements de paquets APT
  Debian/Ubuntu. Build maison (`build: ./apt-cacher-ng`, Dockerfile sur
  `debian:trixie-slim`) plutôt qu'une image publique — remplace l'image
  `sameersbn/apt-cacher-ng` utilisée initialement. Configuré via
  `apt-cacher-ng/conf/acng.conf`/`security.conf` (montés en lecture seule) ;
  le proxy amont y est renseigné en dur (`Proxy: http://172.16.0.1:3128`)
  plutôt que via `HTTP_PROXY`/`HTTPS_PROXY` — un fichier de conf monté dans le
  conteneur n'a pas accès aux variables du `.env`, d'où le bloc `environment`
  laissé en commentaire dans `docker-compose.yml`. Persiste dans `./apt-cache`
  et journalise dans `./apt-logs` (bind mounts, ignorés par git). Healthcheck
  sur `acng-report.html`. Écoute sur le port `3142`. En cas d'erreur `BADSIG`
  sur les `InRelease` (cache corrompu/périmé), voir `docs/error-badsig.md`.
- **qbittorrent** (`linuxserver/qbittorrent`) — diffuse les images de VM vers
  les machines des étudiants via BitTorrent, en alternative à LPD (jugé trop
  lent dans ce labo). WebUI sur le port `8080` ; port BT fixe `6881` (tcp+udp)
  pour éviter la découverte. Config persistante dans `./qbittorrent/config`
  (bind mount, ignoré par git — contient les identifiants WebUI). Pointe en
  lecture seule vers un répertoire local d'images de VM (`IMAGES_VM_PATH`
  dans `.env`, spécifique à la machine hôte — compose refuse de démarrer si
  la variable est absente) afin de pouvoir diffuser sans étape séparée de
  téléchargement/surveillance ; les fichiers `.torrent` générés à partir de ce contenu
  correspondent directement par hachage. Les `.torrent` eux-mêmes sont stockés
  dans `./torrents` (bind mount, ignoré par git) : créés là (Créateur de
  torrent de qBittorrent ou un autre outil) ; leurs trackers et webseeds
  peuvent être ajoutés/remplacés après coup avec `edit_torrent.py` (script à
  la racine du dépôt, sans dépendance externe, ne modifie jamais l'info-hash
  — voir `docs/torrents.md`, qui documente aussi le vocabulaire BitTorrent
  du projet). Ajoutés en seed via `add_torrent.py` (script à la racine du
  dépôt, utilise l'API WebUI — nécessite qu'un mot de passe WebUI **fixe**
  soit défini au préalable, sinon échec d'authentification ; ce mot de passe
  se définit dans la WebUI puis se reporte dans `QBITTORRENT_WEBUI_PASSWORD`
  (`.env`), lu automatiquement par le script — voir `docs/qbittorrent.md`),
  puis publiés par **torrents-http** (voir ci-dessous).
- **torrents-http** (`nginx:alpine`) — serveur statique minimal, sans
  authentification, réservé au réseau du labo. Config dans
  `nginx/default.conf`. Deux routes en lecture seule : `/torrents/` (les
  fichiers `.torrent` à récupérer par les machines étudiantes) et
  `/images-vm/` (le même contenu que `/data` sur qbittorrent, via le même
  `IMAGES_VM_PATH` — sert de *webseed* HTTP, BEP 19, en secours si le
  BitTorrent ne fonctionne pas ; à déclarer comme `url-list` dans le
  `.torrent`, cf. `edit_torrent.py` ci-dessus). Port hôte configurable via
  `TORRENTS_HTTP_PORT` dans `.env` (défaut `8081`, volontairement pas `80`).
- **opentracker** — tracker BitTorrent minimal complétant LPD, sans
  authentification. Diagnostics sur `http://<host>:6969/stats`. Ports `6969`
  tcp+udp. Image communautaire non officielle (`wiltonsr/opentracker`) — voir
  `docs/opentracker-provenance.md` pour le contexte, le risque de disparition
  et la procédure de sauvegarde ; le nom du dépôt Docker Hub a déjà changé une
  fois (27/08/2026), cassant un `docker compose pull` sans rien changer côté
  labo.

**docker-registry-cache** a `HTTP_PROXY`/`HTTPS_PROXY` positionnés vers le
proxy Squid amont, et `NO_PROXY` positionné pour qu'il ne se proxyfie pas
lui-même (ni localhost) — lors de l'ajout d'un nouveau service proxyfié via
variables d'environnement, suivre le même schéma et ajouter le nom du service
lui-même à son `NO_PROXY`. **apt-cache** ne suit plus ce schéma depuis son
passage en build maison : son proxy amont est configuré directement dans
`acng.conf` (voir ci-dessus), pas via l'environnement.

Les valeurs d'environnement (`SQUID_PROXY_ADDR`, `SQUID_NO_PROXY`) sont dans
`.env` et spécifiques au site (actuellement `172.16.0.1:3128`) ; ne pas
supposer qu'elles sont portables d'un déploiement à l'autre.

`.env` contient un secret (`QBITTORRENT_WEBUI_PASSWORD`) : il est ignoré par
git. `.env.sample` est son pendant versionné (valeurs d'exemple, à copier en
`.env` sur une nouvelle installation) — toute variable ajoutée à `.env` doit
être répercutée dans `.env.sample`.

### apt-proxy-probe.sh/

Copie vendorisée d'un projet tiers
(https://github.com/foundObjects/apt-proxy-probe.sh), **non écrite dans ce
dépôt** — à traiter comme du code amont. C'est un installeur côté client pour
les machines du labo : un script de sonde (`apt-proxy-probe.sh`) qu'APT appelle
via `Acquire::http::Proxy-Auto-Detect` pour choisir le premier proxy
joignable dans `proxies.list` (avec repli sur `DIRECT`), plus `00proxy` (le
snippet apt.conf.d) et `install.sh` (installe/désinstalle les trois fichiers
sur une machine, nécessite root). Ceci est destiné à être déployé sur les
machines clientes pour qu'elles puissent découvrir `apt-cache`/
`docker-registry-cache` même en changeant de réseau — ce n'est pas exécuté
dans le cadre de la pile compose elle-même.

## Machine de dev vs machine du labo

Ce dépôt peut être lancé sur une machine de développement pour tester des
changements, sans rapport avec la machine qui fait réellement tourner le
labo. Sur une machine de dev, `docker-registry-cache`/`apt-cache` ne servent
de cache à personne — ne pas pousser d'images vers `localhost:5000` ou
considérer le contenu de `./docker-cache`/`./apt-cache` comme utile en dehors
du déploiement réel du labo.

## Remarque sur la langue

Les commentaires du compose/de la configuration et le contexte des commits
sont en français (ce dépôt gère un labo informatique en France) ; conserver
la langue existante lors de l'édition de ces fichiers.
