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

Quatre services indépendants définis dans `docker-compose.yml`, qui récupèrent
tous le contenu distant via le proxy Squid amont du labo (`SQUID_PROXY_ADDR` /
`SQUID_NO_PROXY` dans `.env`) :

- **docker-registry-cache** (`registry:2`) — cache/miroir pull-through pour
  Docker Hub. Configuré via `config.yml`, monté en lecture seule dans le
  conteneur ; son `proxy.remoteurl` pointe vers `https://registry-1.docker.io`.
  Les couches d'images mises en cache persistent dans `./docker-cache` (bind
  mount, ignoré par git). Écoute sur le port `5000`.
- **apt-cache** (`sameersbn/apt-cacher-ng`) — proxy de cache pour les
  téléchargements de paquets APT Debian/Ubuntu. Persiste dans `./apt-cache`
  (bind mount, ignoré par git). Écoute sur le port `3142`.
- **qbittorrent** (`linuxserver/qbittorrent`) — diffuse les images de VM vers
  les machines des étudiants via BitTorrent, en alternative à LPD (jugé trop
  lent dans ce labo). WebUI sur le port `8080` ; port BT fixe `6881` (tcp+udp)
  pour éviter la découverte. Config persistante dans `./qbittorrent/config`
  (bind mount, ignoré par git — contient les identifiants WebUI). Pointe en
  lecture seule vers un répertoire local d'images de VM
  (`/chemin/vers/vos/images-vm:ro` — chemin d'exemple, à adapter par machine
  hôte) afin de pouvoir diffuser sans étape séparée de téléchargement/
  surveillance ; les fichiers `.torrent` générés à partir de ce contenu
  correspondent directement par hachage.
- **opentracker** — tracker BitTorrent minimal complétant LPD, sans
  authentification. Diagnostics sur `http://<host>:6969/stats`. Ports `6969`
  tcp+udp. Image communautaire non officielle (`wiltonsr/opentracker`) — voir
  `docs/opentracker-provenance.md` pour le contexte, le risque de disparition
  et la procédure de sauvegarde ; le nom du dépôt Docker Hub a déjà changé une
  fois (27/08/2026), cassant un `docker compose pull` sans rien changer côté
  labo.

Les deux services de cache ont `HTTP_PROXY`/`HTTPS_PROXY` positionnés vers le
proxy Squid amont, et `NO_PROXY` positionné pour qu'ils ne se proxyfient pas
mutuellement (ni vers localhost) — lors de l'ajout d'un nouveau service
proxyfié, suivre le même schéma et ajouter le nom du service lui-même à son
`NO_PROXY`.

Les valeurs d'environnement (`SQUID_PROXY_ADDR`, `SQUID_NO_PROXY`) sont dans
`.env` et spécifiques au site (actuellement `172.16.0.1:3128`) ; ne pas
supposer qu'elles sont portables d'un déploiement à l'autre.

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
