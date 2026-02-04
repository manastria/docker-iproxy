FROM debian:trixie-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends apt-cacher-ng ca-certificates curl gosu \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/cache/apt-cacher-ng /var/log/apt-cacher-ng /etc/apt-cacher-ng \
 && chown -R apt-cacher-ng:apt-cacher-ng /var/cache/apt-cacher-ng /var/log/apt-cacher-ng

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 3142
ENTRYPOINT ["/entrypoint.sh"]
CMD ["apt-cacher-ng","-c","/etc/apt-cacher-ng","ForeGround=1"]
