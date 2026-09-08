FROM alpine:latest
RUN apk add --no-cache git git-daemon
RUN mkdir -p /srv/git
# git daemon tourne en root alors que les dépôts (bind mount) appartiennent à
# l'utilisateur hôte : sans ça, git refuse de servir les dépôts existants
# ("detected dubious ownership", depuis la CVE-2022-24765).
RUN git config --global --add safe.directory '*'
EXPOSE 9418
CMD ["git", "daemon", "--reuseaddr", "--base-path=/srv/git", \
     "--export-all", "--enable=receive-pack", "/srv/git"]
