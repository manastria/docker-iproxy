## Diagnostic

L'erreur `BADSIG` sur les fichiers `InRelease` est un classique avec apt-cacher-ng : le cache a servi une version **corrompue ou périmée** du fichier `InRelease` (dont la signature ne correspond plus au contenu).

C'est typiquement ce qui arrive quand Ubuntu signe une nouvelle release d'un fichier `InRelease` mais qu'apt-cacher-ng a en cache une version intermédiaire incohérente (contenu partiellement mis à jour, headers corrompus, etc.).

---

## Solution : vider le cache des fichiers InRelease corrompus

### Option 2 — Supprimer manuellement les fichiers `InRelease` en cache

C'est le moyen le plus ciblé. Dans ton volume `./apt-cache` (qui correspond à `/var/cache/apt-cacher-ng` dans le conteneur) :

```bash
# Sur l'hôte, dans le dossier du projet
find ./apt-cache -name "InRelease" -delete
find ./apt-cache -name "*.InRelease" -delete

# Ou via docker exec si tu préfères
docker exec apt-cache-server find /var/cache/apt-cacher-ng -name "InRelease" -delete
```

Ensuite sur les clients :

```bash
sudo apt clean
sudo apt update
```

---

### Option 3 — Forcer le re-téléchargement via l'URL de purge d'apt-cacher-ng

apt-cacher-ng expose une API de purge :

```bash
# Purge tout ce qui concerne ubuntu (adapte le pattern)
curl "http://localhost:3142/acng-report.html?doExpire=Start+Expiration&bofbExpire=0&offerChanged=1"
```
