# Gestion des torrents

Ce document décrit le flux complet de diffusion des images de VM par
BitTorrent dans ce projet : la phase de *préparation* (hors du labo,
typiquement sur une clé USB), la phase d'*import* (sur la machine du labo),
les scripts qui les outillent, les invariants à respecter, et un glossaire du
vocabulaire BitTorrent employé ici.

## Le principe : la clé ne connaît pas le labo

L'info-hash d'un torrent est l'empreinte SHA-1 du seul dictionnaire `info`,
c'est-à-dire du **contenu** (noms, tailles, découpage en pièces). Les trackers
(`announce` / `announce-list`) et les webseeds (`url-list`) vivent **en dehors**
de ce dictionnaire.

Conséquence exploitée par toute cette chaîne : on peut ajouter ou corriger
trackers et webseeds d'un `.torrent` **sans changer son info-hash**, donc sans
casser le swarm ni invalider les `.torrent` déjà distribués.

D'où le partage des rôles :

- la **clé de préparation** produit des `.torrent` « nus », sans aucune adresse.
  Elle n'a pas besoin de savoir sur quel réseau ils seront diffusés ;
- la **machine du labo** y appose *ses* adresses au moment de l'import, d'après
  `LAB_HOST_IP` dans `.env`.

Une clé préparée à la maison reste donc valable même si le labo change
d'adressage, et l'IP du labo n'est écrite qu'à un seul endroit.

## Configuration préalable

Deux variables de `.env` (cf. `.env.sample`) gouvernent la diffusion :

- **`IMAGES_VM_PATH`** — répertoire hôte contenant les images de VM à
  diffuser. Monté en lecture seule dans `qbittorrent` (`/data`) et dans
  `torrents-http` (`/images-vm/`). Sans lui, `docker compose up` refuse de
  démarrer ces deux services.
- **`LAB_HOST_IP`** — adresse de la machine du labo telle que les postes
  étudiants doivent la joindre. Source unique des URL inscrites dans les
  `.torrent` : tracker (`opentracker`, port 6969, HTTP et UDP) et webseed
  (`torrents-http`, port `TORRENTS_HTTP_PORT`). À repérer avec :

  ```bash
  ip -4 -o addr show scope global
  ```

## Vue d'ensemble du flux

```
   [ à la maison / clé USB ]              [ machine du labo ]

   seed/<nom>/                                IMAGES_VM_PATH/<nom>/
     └─ image.ova            ──copie──>         └─ image.ova
     └─ MANIFEST.sha256                         └─ MANIFEST.sha256
          │                                          │
    make_torrent.py                                  │ (monté :ro)
          │                                          ├─> qbittorrent /data
          v                                          └─> torrents-http /images-vm/
   torrents/<nom>.torrent    ──tampon──>       ./torrents/<nom>.torrent
   (nu : ni tracker                            (+ trackers + webseed)
    ni webseed)                                       │
                                                      ├─> qBittorrent (seed)
                                                      └─> torrents-http /torrents/
```

### 1. Préparation (clé USB)

Déployer l'outillage sur la clé, depuis ce dépôt :

```bash
python3 provision_usb.py /run/media/<user>/<CLE>
```

Cela y installe `make_torrent.py`, `torrent_lib.py`, un lanceur `build.bat`
pour Windows et un `LISEZMOI.txt`, puis crée `seed/` et `torrents/`. Aucune
dépendance à installer sur la clé : Python 3.7+ suffit, ni `pip`, ni `rhash`.

Déposer ensuite **un dossier par image** dans `seed/` — le nom du dossier
devient le nom du torrent — puis lancer la préparation :

```bash
# Sur la clé
python3 make_torrent.py          # Linux
build.bat                        # Windows (double-clic)
```

Pour chaque dossier, le script :

1. calcule `MANIFEST.sha256` s'il est absent (et le vérifie s'il est présent) ;
2. crée `torrents/<nom>.torrent` s'il est absent.

Les deux étapes lisent l'intégralité des données : comptez quelques minutes
par image. `--verify-only` se contente de contrôler l'intégrité, `--force`
recrée un `.torrent` existant, `--only <nom>` restreint à une image.

### 2. Import (machine du labo)

Depuis la racine de ce dépôt, une seule commande :

```bash
python3 import_seed.py /run/media/<user>/<CLE>
```

Elle enchaîne, pour chaque image de la clé :

1. **vérifie l'intégrité à la source** d'après `MANIFEST.sha256` ;
2. **copie** le dossier vers `IMAGES_VM_PATH/<nom>/` ;
3. **re-vérifie l'intégrité après copie** — une clé fatiguée ou un câble
   douteux se voient ici, pas devant trente étudiants ;
4. **appose trackers et webseed** d'après `LAB_HOST_IP` (info-hash inchangé,
   contrôlé explicitement : le script s'interrompt si `info` a bougé) ;
5. **publie** le `.torrent` dans `./torrents`, servi par `torrents-http` ;
6. **ajoute le torrent à qBittorrent** en seed sur les données copiées ;
7. **attend la confirmation** que qBittorrent a contrôlé les pièces et est
   bien passé en seed — c'est là que se détecte un contenu qui ne correspond
   pas au torrent.

Options utiles : `--dry-run` (montre sans rien faire), `--only <nom>`,
`--force` (recopie même si la destination existe), `--no-seed` (tout sauf
l'ajout à qBittorrent), `--qbit-url` si la WebUI n'est pas sur `localhost`.

### 3. Côté postes étudiants

Les `.torrent` sont récupérés sur `http://<LAB_HOST_IP>:<TORRENTS_HTTP_PORT>/torrents/`.
Le client s'annonce auprès d'`opentracker` pour rejoindre le swarm ; si le
BitTorrent ne fonctionne pas (port bloqué, aucun seed), il bascule sur la
webseed HTTP `/images-vm/`.

Comme `MANIFEST.sha256` fait partie du contenu du torrent, chaque poste peut
vérifier sa copie sans outil supplémentaire :

```bash
sha256sum -c MANIFEST.sha256
```

## Invariants à respecter

Quatre règles qui, prises en défaut, se traduisent par un torrent qui ne
démarre jamais ou une webseed silencieusement inerte.

**La racine du torrent est un sous-dossier de `IMAGES_VM_PATH`, jamais
`IMAGES_VM_PATH` lui-même.** qBittorrent reçoit `savepath=/data` et y cherche
`/data/<nom-du-torrent>/`. Un torrent créé directement à partir de
`IMAGES_VM_PATH` chercherait donc `/data/<nom-de-IMAGES_VM_PATH>/` et ne
trouverait rien.

**`MANIFEST.sha256` se calcule avant le `.torrent`, et jamais après.** Il est
écrit *dans* le dossier source, donc il fait partie du contenu haché. Le
régénérer après coup change le contenu, donc l'info-hash : le `.torrent` déjà
distribué ne correspond plus. `make_torrent.py` ne le génère que s'il est
absent, précisément pour cette raison.

**L'URL webseed se termine par une barre.** Sur un torrent multi-fichiers, le
client ajoute `<nom-du-torrent>/<chemin>` à l'URL de `url-list`. Avec
`http://host:8081/images-vm/` il demande
`http://host:8081/images-vm/Xubuntu%202026-09-14/image.ova` (servi) ; sans la
barre finale, il demande `/images-vmXubuntu%20…` et reçoit un 404. L'échec est
silencieux : le torrent fonctionne quand même tant qu'un seed BitTorrent
répond, et ne se révèle que le jour où l'on comptait sur le secours.

**Un contenu modifié est un autre torrent.** Pour corriger une image déjà
diffusée, créer un nouveau dossier daté plutôt que de modifier l'ancien.

## Les scripts

| Script | Où | Rôle |
| --- | --- | --- |
| `provision_usb.py` | dépôt | Déploie l'outillage de préparation sur une clé USB |
| `make_torrent.py` | clé (ou dépôt) | `MANIFEST.sha256` + création des `.torrent` |
| `import_seed.py` | dépôt | Copie, vérifie, tamponne, publie et met en seed |
| `edit_torrent.py` | dépôt | Corrige trackers/webseeds d'un `.torrent`, inspecte |
| `add_torrent.py` | dépôt | Met en seed un `.torrent` seul (appoint) |
| `torrent_lib.py` | — | Briques communes (bencode, manifeste, création, API) |

Tous sont sans dépendance externe, à une exception près : les fonctions qui
dialoguent avec l'API WebUI de qBittorrent ont besoin de `requests`, importé
seulement à l'appel. La préparation sur la clé n'en a donc jamais besoin.

### `torrent_lib.py`

Module commun : bencode (encodage/décodage, info-hash), lecture de `.env`,
dérivation des URL du labo, génération/vérification de `MANIFEST.sha256`,
découpage en pièces et construction du dictionnaire `info`, client qBittorrent.

Le découpage en pièces reproduit le comportement des créateurs de torrents
usuels : taille de pièce en puissance de deux visant environ 1500 pièces
(bornée entre 256 Kio et 16 Mio), fichiers triés par chemin relatif, hachage
SHA-1 sur le flux concaténé sans tenir compte des frontières de fichiers. Sur
l'image de test de 4,67 Gio, il produit le même info-hash que
`py3createtorrent` — les `.torrent` créés par l'ancien outillage restent donc
valables tels quels.

La lecture d'un `MANIFEST.sha256` tolère les variantes rencontrées en
pratique : séparateur `  ` (deux espaces, format `sha256sum`) ou ` *` (mode
binaire), et fins de ligne CRLF. Sans cette tolérance, un manifeste préparé
sous Windows échoue à la vérification sous Linux.

### `edit_torrent.py` — trackers et webseeds

Outil d'appoint pour les corrections après coup (tracker déplacé, port
changé, webseed oubliée) et pour l'inspection. Ne touche jamais au
dictionnaire `info` : l'info-hash reste identique, contrôlé à l'écriture.

Par défaut le résultat est écrit dans `<nom>.edited.torrent` — le fichier
d'origine n'est jamais modifié sans le demander. `--in-place` écrase l'entrée,
`-o` choisit une autre sortie.

```bash
# Inspecter : nom, info-hash, taille, trackers, webseeds
python3 edit_torrent.py mon-image.torrent --show

# Réappliquer les adresses du labo (LAB_HOST_IP) après un changement d'IP
python3 edit_torrent.py torrents/mon-image.torrent --lab --in-place

# Ajouter un tracker de secours (nouveau tier, essayé après les existants)
python3 edit_torrent.py mon-image.torrent --add-tracker udp://autre:6969/announce

# Remplacer entièrement trackers et webseeds
python3 edit_torrent.py mon-image.torrent \
  --set-trackers "http://10.0.0.1:6969/announce,udp://10.0.0.1:6969/announce" \
  --set-webseeds "http://10.0.0.1:8081/images-vm/" \
  --in-place
```

`--set-*` remplacent l'existant et acceptent une liste séparée par des
virgules ; `--add-*` sont répétables et s'ajoutent. Un `.torrent` modifié doit
être republié dans `./torrents` pour que les postes récupèrent la version à
jour — l'ancien fichier reste utilisable pour rejoindre le même swarm (même
info-hash), il n'offre simplement pas les trackers/webseeds ajoutés depuis.

### `add_torrent.py` — mise en seed seule

Ajoute un `.torrent` à qBittorrent et le met en seed sur le contenu déjà
présent sous `IMAGES_VM_PATH`. `import_seed.py` fait cela et le reste ; ce
script sert quand les données sont déjà en place et qu'il n'y a que l'ajout à
refaire. Nécessite un mot de passe WebUI fixe — voir `docs/qbittorrent.md`.

## Dépannage

**`Authentification refusée par qBittorrent`** — le mot de passe de `.env` ne
correspond pas à celui de la WebUI, ou aucun mot de passe fixe n'a jamais été
défini (l'image en génère alors un nouveau à chaque démarrage). Après
plusieurs échecs, qBittorrent bannit temporairement l'IP :
`docker compose restart qbittorrent` lève le bannissement. Procédure complète
dans `docs/qbittorrent.md`.

**qBittorrent affiche `missingFiles` ou reste à 0 %** — les données ne sont pas
là où le torrent les attend. Vérifier que `IMAGES_VM_PATH/<nom-du-torrent>/`
existe bien sur l'hôte, `<nom-du-torrent>` étant le nom affiché par
`edit_torrent.py --show`.

**qBittorrent affiche `error` alors que la vérification des pièces atteint
100 %** — regarder le journal interne (WebUI : Journal, ou
`GET /api/v2/log/main`) : un message `File error alert ... Read-only file
system` signale que le moteur libtorrent n'a pas pu ouvrir les fichiers, même
en seed-only. C'est structurel : libtorrent ouvre toujours les fichiers en
lecture-écriture (préallocation, pièces à corriger éventuellement), donc le
montage `/data` de qBittorrent ne peut pas être `:ro` — voir le commentaire
dans `docker-compose.yml`. Si ça revient malgré tout, forcer une nouvelle
vérification suffit une fois le montage corrigé :

```bash
docker compose up -d qbittorrent   # recrée le conteneur avec le bon montage
# puis, dans la WebUI : clic droit sur le torrent > Forcer une recheck
```

**`import_seed.py` relancé sur une image déjà importée** — c'est un cas normal
(recheck après incident, deuxième passage sur la clé) et il est géré sans
erreur : qBittorrent répond `409 Conflict` à un ajout en double,
`import_seed.py` le reconnaît (`Déjà présent dans qBittorrent`) et enchaîne
directement sur la vérification de l'état, sans le retélécharger. Le script
est rejouable sans risque.

**Un `docker compose restart` ne change rien après avoir recréé
`IMAGES_VM_PATH` à la main** (`rmdir` + `mkdir`, ou tout outil qui remplace le
répertoire plutôt que d'écrire dedans) — un bind mount Docker est attaché à
l'inode monté au démarrage du conteneur, pas au chemin. Un nouveau répertoire
au même chemin n'est vu qu'après un redémarrage du conteneur concerné
(`docker compose restart qbittorrent torrents-http` suffit, pas besoin de
`up -d`). Pour éviter ce piège, préférer vider le contenu d'un
`IMAGES_VM_PATH` déjà monté plutôt que de le recréer.

**Le téléchargement démarre mais la webseed n'est jamais utilisée** — tester
l'URL à la main, en remplaçant les espaces par `%20` :

```bash
curl -sI "http://<LAB_HOST_IP>:8081/images-vm/<nom-du-torrent>/<fichier>"
```

Un 404 signale le plus souvent une `url-list` sans barre finale
(`edit_torrent.py --show` pour le confirmer, `--lab --in-place` pour corriger).

**`Intégrité non conforme`** — à la source, la clé ou l'image est abîmée : il
faut repartir de l'original. Après copie, supprimer
`IMAGES_VM_PATH/<nom>/` et relancer l'import.

## Glossaire

- **`.torrent`** — fichier de métadonnées (bencodées) décrivant un contenu
  (nom, taille, découpage en pièces et leurs empreintes) et où l'annoncer
  (trackers, webseeds). Ne contient jamais le contenu lui-même.
- **Bencode** — format de sérialisation binaire du protocole BitTorrent
  (entiers, chaînes, listes, dictionnaires à clés triées). Utilisé aussi
  bien pour le `.torrent` que pour les échanges avec le tracker.
- **Info-hash** — empreinte SHA-1 du dictionnaire `info` du `.torrent` (le
  contenu et son découpage, indépendamment des trackers/webseeds).
  Identifiant unique du swarm : c'est lui, et non le nom de fichier, que le
  tracker et les pairs utilisent pour se reconnaître.
- **Pièce (*piece*)** — le contenu est découpé en blocs de taille fixe
  (`piece length`), chacun vérifié par sa propre empreinte à la réception.
- **Essaim (*swarm*)** — l'ensemble des pairs échangeant un même contenu
  (même info-hash), qu'ils le possèdent entièrement ou partiellement.
- **Pair (*peer*)** — toute machine participant à un swarm.
- **Seed / seeder** — pair qui possède déjà l'intégralité du contenu et le
  partage sans plus rien télécharger. `qbittorrent` joue ce rôle initial
  dans ce projet.
- **Leecher** — pair encore en cours de téléchargement, ne détenant qu'une
  partie du contenu (typiquement, un poste étudiant en cours de
  récupération).
- **Tracker** — serveur qui coordonne un swarm : centralise l'annonce des
  pairs pour un info-hash donné et leur renvoie une liste d'autres pairs à
  contacter. N'héberge jamais le contenu (`opentracker` dans ce projet).
- **Annonce (*announce*)** — requête périodique (HTTP ou UDP) qu'un client
  envoie au tracker pour signaler sa présence dans le swarm et obtenir une
  liste de pairs.
- **`announce-list` / tier** (BEP 12) — liste de trackers de secours dans le
  `.torrent`, organisée en tiers (niveaux de repli) : le client essaie les
  trackers d'un même tier dans un ordre aléatoire, et ne passe au tier
  suivant qu'après échec de tous ceux du tier courant.
- **Webseed** (BEP 19, dite aussi *GetRight-style*) — une ou plusieurs URL
  HTTP(S) déclarées dans le `.torrent` (clé `url-list`) permettant de
  récupérer le contenu directement en HTTP, en secours si le swarm
  BitTorrent est indisponible ou insuffisant. `torrents-http` (`/images-vm/`)
  joue ce rôle dans ce projet.
- **`url-list`** — clé bencode du `.torrent` portant la ou les URL(s)
  webseed (BEP 19).
- **DHT** (*Distributed Hash Table*) — mécanisme de découverte de pairs sans
  tracker central. Non utilisé ici : `opentracker` suffit dans un labo au
  réseau fermé.
- **PEX** (*Peer Exchange*) — échange de listes de pairs directement entre
  clients déjà connectés, en complément du tracker.
- **LPD** (*Local Peer Discovery*) — découverte de pairs sur le réseau local
  par diffusion UDP. Alternative à BitTorrent jugée trop lente dans ce
  labo ; `opentracker` la complète plutôt qu'il ne la remplace.
- **Manifeste (`MANIFEST.sha256`)** — liste des empreintes SHA-256 des
  fichiers d'une image, au format `sha256sum`. Propre à ce projet (ce n'est
  pas du BitTorrent) : il fait partie du contenu diffusé, ce qui permet à
  chaque poste de contrôler sa copie avec `sha256sum -c MANIFEST.sha256`.
