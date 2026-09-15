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

Six services indépendants définis dans `docker-compose.yml`, qui récupèrent
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
  (bind mount, ignoré par git — contient les identifiants WebUI). Pointe vers
  un répertoire local d'images de VM (`IMAGES_VM_PATH` dans `.env`,
  spécifique à la machine hôte — compose refuse de démarrer si la variable
  est absente) afin de pouvoir diffuser sans étape séparée de
  téléchargement/surveillance ; les fichiers `.torrent` générés à partir de ce
  contenu correspondent directement par hachage. **Pas en lecture seule** :
  même pour un torrent complet et jamais modifié, libtorrent ouvre les
  fichiers en lecture-écriture (préallocation, pièces à corriger
  éventuellement) — en `:ro`, l'ouverture échoue et le torrent reste bloqué
  en état `error` malgré une vérification des pièces à 100 % (piège constaté
  en pratique, détaillé dans `docs/torrents.md`). `torrents-http`, lui, reste
  en lecture seule sur ce même contenu : il ne fait que le servir en HTTP.
  Les `.torrent` eux-mêmes sont stockés
  dans `./torrents` (bind mount, ignoré par git), d'où **torrents-http** les
  publie (voir ci-dessous). La chaîne de préparation et d'import est décrite
  dans `docs/torrents.md`, qui documente aussi ses invariants et le
  vocabulaire BitTorrent du projet. Elle tient en deux temps :
  `make_torrent.py` prépare hors du labo (manifeste SHA-256 puis `.torrent`
  « nu », sans tracker ni webseed), `import_seed.py` importe sur la machine
  du labo (copie, revérification après copie, apposition des trackers et de
  la webseed d'après `LAB_HOST_IP`, publication, mise en seed). Ce découpage
  tient au fait que l'info-hash ne dépend que du dictionnaire `info`, donc du
  contenu : trackers et webseeds s'ajoutent après coup sans casser le swarm,
  et l'IP du labo n'est écrite que dans `.env`. `edit_torrent.py` couvre les
  corrections ultérieures, `add_torrent.py` la seule mise en seed ; le
  bencode et les briques communes sont dans `torrent_lib.py`. Tous ces
  scripts sont à la racine du dépôt et sans dépendance externe, sauf pour
  dialoguer avec l'API WebUI (`requests`, importé à l'appel) — ce qui
  nécessite qu'un mot de passe WebUI **fixe** soit défini au préalable, sinon
  échec d'authentification : il se définit dans la WebUI puis se reporte dans
  `QBITTORRENT_WEBUI_PASSWORD` (`.env`) — voir `docs/qbittorrent.md`.
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
- **git-daemon** (`build: ./git-daemon`, Dockerfile sur `alpine:latest`) —
  dépôts Git bare accessibles en `git://` (sans authentification ni
  chiffrement), pour du push/clone de scripts de maintenance depuis les
  machines du labo. Port `9418`. Dépôts stockés sous `./git-daemon/repos`
  par défaut (bind mount, ignoré par git), ou sous `GIT_DAEMON_REPOS_PATH`
  (`.env`, optionnelle) pour les stocker hors de ce dépôt — voir
  `docs/git-daemon.md`, qui documente aussi un piège de permissions : ce
  répertoire doit être créé par l'utilisateur hôte *avant* le premier
  `docker compose up`, sinon Docker le crée en tant que `root` (le conteneur
  ne tourne pas avec un `PUID`/`PGID` comme qBittorrent).

**docker-registry-cache** a `HTTP_PROXY`/`HTTPS_PROXY` positionnés vers le
proxy Squid amont, et `NO_PROXY` positionné pour qu'il ne se proxyfie pas
lui-même (ni localhost) — lors de l'ajout d'un nouveau service proxyfié via
variables d'environnement, suivre le même schéma et ajouter le nom du service
lui-même à son `NO_PROXY`. **apt-cache** ne suit plus ce schéma depuis son
passage en build maison : son proxy amont est configuré directement dans
`acng.conf` (voir ci-dessus), pas via l'environnement.

Les valeurs d'environnement (`SQUID_PROXY_ADDR`, `SQUID_NO_PROXY`) sont dans
`.env` et spécifiques au site (actuellement `172.16.0.1:3128`) ; ne pas
supposer qu'elles sont portables d'un déploiement à l'autre. Même remarque
pour `LAB_HOST_IP` (actuellement `172.25.1.111`) : c'est l'adresse de la
machine du labo telle que les postes étudiants la joignent, et la source
unique des URL de tracker et de webseed inscrites dans les `.torrent` — elle
n'est lue que par les scripts de torrents, jamais par `docker-compose.yml`.

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

### Clé de préparation des images de VM

La préparation des images se fait hors du labo (typiquement à la maison), sur
une clé USB, et l'outillage qui y tourne est **déployé depuis ce dépôt** par
`provision_usb.py` : `make_torrent.py` + `torrent_lib.py` + un lanceur
`build.bat` et un `LISEZMOI.txt`. La clé ne contient donc aucune copie de
référence à maintenir séparément, et aucune adresse du labo — voir
`docs/torrents.md`. Ne rien y modifier directement : modifier le script dans
le dépôt, puis redéployer.

Cet outillage remplace un projet séparé et non versionné (« prof-seed »), qui
dépendait de `py3createtorrent` (via pip) et embarquait un binaire
`rhash.exe`. Les deux ont disparu : le hachage SHA-256 et la création du
`.torrent` sont faits en Python pur dans `torrent_lib.py`, de sorte que la clé
ne demande rien d'autre que Python 3.7+. La création reproduit l'info-hash de
`py3createtorrent` à l'identique (vérifié sur une image de 4,67 Gio), donc les
`.torrent` produits par l'ancien outillage restent valables.

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
