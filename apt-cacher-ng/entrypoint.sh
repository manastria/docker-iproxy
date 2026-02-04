#!/bin/sh
set -eu

mkdir -p /run/apt-cacher-ng /var/cache/apt-cacher-ng /var/log/apt-cacher-ng
chown -R apt-cacher-ng:apt-cacher-ng /run/apt-cacher-ng /var/cache/apt-cacher-ng /var/log/apt-cacher-ng

# démarre ACNG
gosu apt-cacher-ng apt-cacher-ng -c /etc/apt-cacher-ng ForeGround=1 &

# envoie les logs fichiers vers stdout
tail -F /var/log/apt-cacher-ng/*.log /var/log/apt-cacher-ng/*.err
