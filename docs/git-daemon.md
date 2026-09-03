## Présentation

Le service `git-daemon` héberge des dépôts Git bare accessibles via le
protocole `git://` (`git daemon`), sans authentification ni chiffrement.
Réservé au réseau interne du labo, pour du push/clone de scripts de
maintenance — pas pour du code sensible.

---

## Créer un nouveau dépôt

Chaque dépôt est un sous-dossier `*.git` sous `./git-daemon/repos` :

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
