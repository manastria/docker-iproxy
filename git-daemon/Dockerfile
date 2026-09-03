FROM alpine:latest
RUN apk add --no-cache git
RUN mkdir -p /srv/git
EXPOSE 9418
CMD ["git", "daemon", "--reuseaddr", "--base-path=/srv/git", \
     "--export-all", "--enable=receive-pack", "/srv/git"]
