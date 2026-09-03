## Présentation

Le service `git-daemon` héberge des dépôts Git bare accessibles via le
protocole `git://` (`git daemon`), sans authentification ni chiffrement.
Réservé au réseau interne du labo, pour du push/clone de scripts de
maintenance — pas pour du code sensible.

---

## Emplacement des dépôts

Par défaut, les dépôts bare sont stockés sous `./git-daemon/repos`, dans ce
dépôt git (bind mount, ignoré par git). `GIT_DAEMON_REPOS_PATH` (`.env`,
optionnelle) permet de les stocker ailleurs sur l'hôte — un disque ou point
de montage séparé, avec un cycle de vie/backup indépendant du clone de ce
dépôt de configuration.

**Avant le tout premier `docker compose up` du service**, créez vous-même ce
répertoire (par défaut ou via `GIT_DAEMON_REPOS_PATH`) :

```bash
mkdir -p ./git-daemon/repos   # ou le chemin de GIT_DAEMON_REPOS_PATH
```

Le `Dockerfile` du service ne fait tourner `git daemon` que sous `root`
(pas de `PUID`/`PGID` comme pour qBittorrent) : si ce répertoire n'existe pas
encore au premier démarrage, Docker le crée automatiquement en tant que
bind mount, appartenant à `root` — votre utilisateur ne peut alors plus y
créer de dépôt sans `sudo`. Le créer vous-même au préalable évite le
problème (le répertoire garde votre propriétaire). Si le problème est déjà
là (répertoire existant appartenant à `root`), corrigez-le une fois avec :

```bash
sudo chown -R "$(id -u):$(id -g)" ./git-daemon/repos   # ou GIT_DAEMON_REPOS_PATH
```

---

## Créer un nouveau dépôt

Chaque dépôt est un sous-dossier `*.git` sous ce répertoire (par défaut
`./git-daemon/repos`, ou `GIT_DAEMON_REPOS_PATH` si renseignée) :

```bash
mkdir -p ./git-daemon/repos/maintenance.git
git init --bare ./git-daemon/repos/maintenance.git
```

Le dépôt est immédiatement servable, aucun redémarrage du conteneur
n'est nécessaire (`--export-all` rend tous les dépôts du `base-path`
accessibles automatiquement).

---

## Cloner un dépôt

Depuis une machine du labo :

```bash
git clone git://<ip-serveur>/maintenance.git
```

---

## Pousser vers un dépôt existant

Sur un dépôt déjà cloné localement, ou en ajoutant le remote à un dépôt
existant :

```bash
git remote add origin git://<ip-serveur>/maintenance.git
git push origin main
```

`--enable=receive-pack` est activé dans le `Dockerfile` du service : sans
cette option, `git daemon` refuse tout `push` par défaut.

---

## Vérifications

```bash
docker compose up -d git-daemon
docker compose logs git-daemon
```

Les logs ne doivent afficher aucune erreur au démarrage. Un `git clone`
puis un `git push` réussis depuis une autre machine du labo confirment
que le service fonctionne.

---

## Limites volontaires

- Pas d'authentification ni de contrôle d'accès : quiconque atteint le
port `9418` peut cloner et pousser sur n'importe quel dépôt exporté.
- Pas de chiffrement du transport (pas de SSH/HTTPS) : à ne pas exposer
hors du réseau du labo.
- Pas d'interface web de consultation des dépôts.
- Pour des besoins avancés (hooks CI/CD, notifications), utiliser les
hooks Git classiques dans le dépôt bare concerné, par exemple
`repos/maintenance.git/hooks/post-receive`.
