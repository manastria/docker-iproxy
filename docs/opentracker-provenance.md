# Note — provenance de l'image `opentracker`

## Contexte

Le service `opentracker` du `docker-compose.yml` utilise l'image :

```
wiltonsr/opentracker:open
```

Contrairement à `registry:2` (image officielle Docker) ou à des images maintenues par un éditeur identifiable, il n'existe pas d'image Docker "officielle" du projet opentracker. Celle utilisée ici vient d'un dépôt communautaire individuel sur Docker Hub.

**Historique** : le dépôt s'appelait initialement `wiltonsr/opentracker-docker`. Le
27/08/2026, un `docker compose pull` a échoué avec *pull access denied* sur ce
nom — le mainteneur a en réalité renommé le dépôt Docker Hub en
`wiltonsr/opentracker` (même image, même tag `open`, digest
`sha256:d6c1e60c58c3c9f6e72daff3faf271ecd2dfb79f9e66ab0d7fe69e7611476e7f`
confirmé actif et toujours poussé/pull par d'autres). Le compose a été mis à
jour en conséquence. Ce n'est donc pas (encore) la disparition évoquée
ci-dessous, mais un signal concret que ce risque est réel : un renommage de
dépôt suffit à casser un `pull` sans qu'on ait touché à quoi que ce soit
côté labo.

## Pourquoi ce n'est pas bloquant

Le protocole d'annonce HTTP/UDP d'opentracker n'a pas évolué depuis des années — l'absence de mise à jour récente de l'image ne signifie pas un logiciel défaillant ou obsolète. Une fois l'image tirée (`docker pull`) et fonctionnelle, elle continue de fonctionner indépendamment de l'activité du mainteneur.

## Le risque réel

Le point de fragilité n'est pas fonctionnel mais logistique : si ce compte Docker Hub disparaît, est supprimé, ou si l'image est retirée, un futur `docker pull` (nouvelle machine, réinstallation, changement de matériel) échouera — sans que rien n'ait changé côté labo.

## Mitigation retenue

Le compose contient déjà un service `docker-registry-cache` (registry local sur le port 5000). Une fois l'image opentracker validée en conditions réelles :

```
docker tag wiltonsr/opentracker:open localhost:5000/opentracker:open
docker push localhost:5000/opentracker:open
```

Puis faire pointer le service `opentracker` du compose vers `localhost:5000/opentracker:open` plutôt que vers l'image Docker Hub d'origine. Le labo devient alors indépendant de la disponibilité du dépôt tiers.

## Alternative de repli

Si l'image communautaire pose un jour un souci de disponibilité ou d'architecture (ex. build non fourni pour une plateforme donnée), opentracker se compile trivialement depuis les sources (binaire statique, peu de dépendances) — une image maison via un Dockerfile minimal reste une option simple. `chihaya` (Go, images officielles sur Docker Hub) est également une alternative si la question de provenance devient prioritaire sur la simplicité de configuration.

## Sauvegarde de secours (kDrive)

En plus du push vers le registry local (qui sert au fonctionnement quotidien du
labo), l'image est aussi exportée en fichier autonome et archivée sur kDrive —
au cas où le compte Docker Hub communautaire disparaîtrait avant que le
registry local ait pu être alimenté (nouvelle install, changement de
matériel...). Ce tarball ne doit **pas** être ajouté à ce dépôt git : c'est un
binaire de plusieurs Mo qui n'a rien à faire dans l'historique d'un repo de
configuration (poids définitif, pas de diff utile, retéléchargé à chaque
clone).

Procédure d'export :

```bash
docker pull wiltonsr/opentracker:open
docker save wiltonsr/opentracker:open | gzip > opentracker-open_$(date +%Y-%m-%d).tar.gz
```

Noter le digest de l'image au moment de l'export, pour pouvoir vérifier
l'intégrité au moment d'un `docker load` :

```bash
docker inspect --format='{{index .RepoDigests 0}}' wiltonsr/opentracker:open
```

Déposer le fichier `.tar.gz` (et le digest associé) sur kDrive, dans un
emplacement de sauvegarde du labo. Pour restaurer :

```bash
docker load -i opentracker-open_2026-08-27.tar.gz
```

À refaire à chaque fois que l'image est retirée du registry local (nouvelle
version validée, changement de tag...), pour ne pas se retrouver avec une
sauvegarde périmée le jour où elle est nécessaire.
