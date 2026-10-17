FROM busybox:1.37.0-musl AS healthcheck

FROM grafana/loki:3.5.3

# The upstream Loki image is minimal and does not include a network client.
# Embed BusyBox so Compose can check Loki's readiness endpoint from the container.
COPY --from=healthcheck /bin/busybox /busybox
