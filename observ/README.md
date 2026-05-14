# Observability Stack

A local Docker Compose stack that brings up:

- **Arize Phoenix** — agent and application observability at `http://localhost:6006`
- **Todo API** — the deployed `hello-world` service at `http://localhost:8080`

Both run on the `talos-net` bridge network so agents launched from the
workflow can reach Phoenix at `http://phoenix:6006` and the application
logs can be collected for the RCA agent.

## Usage

```bash
# Build & start
docker compose -f observ/docker-compose.yml up -d --build

# Wait for healthchecks, then smoke test
curl http://localhost:8080/healthz
curl http://localhost:6006/healthz

# Dump app logs for the RCA agent to scan
mkdir -p .logs
docker logs talos-todo > .logs/app.log 2>&1

# Tear down
docker compose -f observ/docker-compose.yml down -v
```

## What Phoenix sees

The Todo API is configured with the OpenTelemetry environment variables
(`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`) so that a future
iteration can wire OTLP traces straight into Phoenix. For V1 the RCA agent
primarily consumes the structured JSON logs the API emits to stdout and
that are captured by `docker logs`.
