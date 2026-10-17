FROM busybox:1.37.0-musl AS healthcheck

FROM otel/opentelemetry-collector-contrib:0.136.0

# The upstream Collector image is scratch-based. Add a tiny static HTTP probe
# so Compose checks the health endpoint instead of only validating config.
COPY --from=healthcheck /bin/busybox /busybox
