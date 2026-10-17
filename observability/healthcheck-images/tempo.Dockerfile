FROM busybox:1.37.0-musl AS healthcheck

FROM grafana/tempo:2.8.2

# Tempo's upstream image is distroless. Add a tiny static HTTP probe so
# Compose checks the readiness endpoint instead of only starting the binary.
COPY --from=healthcheck /bin/busybox /busybox-bin
