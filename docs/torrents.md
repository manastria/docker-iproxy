# Gestion des torrents

Ce document décrit le flux complet de diffusion des images de VM par
BitTorrent dans ce projet, les deux scripts qui l'outillent, et un glossaire
du vocabulaire BitTorrent employé ici.

## Configuration préalable

`IMAGES_VM_PATH` (dans `.env`, cf. `.env.sample`) doit pointer vers le
répertoire hôte contenant les images de VM à diffuser. Il est monté en
lecture seule dans `qbittorrent` (`/data`) et dans `torrents-http`
(`/images-vm/`) — sans cette variable renseignée, `docker compose up`
refuse de démarrer ces deux services.

## Vue d'ensemble du flux

1. Les images de VM sont déposées dans le répertoire hôte désigné par
   `IMAGES_VM_PATH`, monté en lecture seule dans `qbittorrent` (`/data`) et
   dans `torrents-http` (`/images-vm/`) — cf. `CLAUDE.md`.
2. Un `.torrent` est créé à partir de ce contenu (Créateur de torrent de
   qBittorrent, ou tout autre outil), avec le tracker `opentracker` déclaré
   et, idéalement, la webseed `torrents-http` renseignée dès la création.
3. Si les trackers ou la webseed doivent être ajoutés ou corrigés après
   coup (tracker changé, port modifié...), `edit_torrent.py` les modifie
   sans recréer le `.torrent` — l'info-hash ne change pas, le swarm n'est
   pas affecté.
4. Le `.torrent` est ajouté en seed sur qBittorrent via `add_torrent.py`
   (API WebUI) — cf. `docs/qbittorrent.md`.
5. Le fichier `.torrent` est publié par `torrents-http` (`/torrents/`) pour
   que les postes étudiants le récupèrent.
6. Chaque poste étudiant ouvre le `.torrent` dans son client BitTorrent, qui
   s'annonce auprès du tracker `opentracker` (HTTP/UDP, port `6969`) pour
   rejoindre le swarm. En secours (BitTorrent bloqué, aucun seed
   disponible...), le client peut récupérer le contenu directement en HTTP
   via la webseed `/images-vm/`.

## `edit_torrent.py` — trackers et webseeds

Modifie les trackers (`announce` / `announce-list`, BEP 12) et les webseeds
(`url-list`, BEP 19) d'un `.torrent` existant. Implémentation bencode
maison, sans dépendance externe. Ne touche jamais au dictionnaire `info` :
l'info-hash reste identique après édition (vérifié par une assertion à
l'écriture).

Par défaut, le résultat est écrit dans `<nom>.edited.torrent` — le fichier
d'origine n'est jamais modifié sans le demander explicitement. Utiliser
`--in-place` pour écraser directement le fichier d'entrée, ou `-o` pour
choisir un autre chemin de sortie.

```bash
# Consulter l'état actuel (trackers, webseeds, info-hash) sans modifier
python3 edit_torrent.py mon-image.torrent --show

# Ajouter un tracker de secours (nouveau tier, essayé après les trackers existants)
python3 edit_torrent.py mon-image.torrent \
  --add-tracker udp://opentracker:6969/announce

# Ajouter une webseed
python3 edit_torrent.py mon-image.torrent \
  --add-webseed http://<ip-serveur>:8081/images-vm/

# Remplacer entièrement les trackers (un tier par URL) et les webseeds, en place
python3 edit_torrent.py mon-image.torrent \
  --set-trackers "http://opentracker:6969/announce,udp://opentracker:6969/announce" \
  --set-webseeds "http://<ip-serveur>:8081/images-vm/" \
  --in-place
```

`--set-trackers`/`--set-webseeds` acceptent une liste d'URL séparées par des
virgules et remplacent l'existant ; `--add-tracker`/`--add-webseed` sont
répétables et s'ajoutent à l'existant. Un `.torrent` modifié doit être
republié dans `./torrents` (donc resservi par `torrents-http`) pour que les
postes étudiants récupèrent la version à jour — l'ancien fichier reste
utilisable pour rejoindre le même swarm (même info-hash), il n'offre
simplement pas les trackers/webseeds ajoutés depuis.

## `add_torrent.py` — mise en seed

Ajoute un `.torrent` à qBittorrent via l'API WebUI et le met en seed sur le
contenu déjà présent (pas de téléchargement). Nécessite un mot de passe
WebUI fixe défini au préalable — voir `docs/qbittorrent.md`.

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
