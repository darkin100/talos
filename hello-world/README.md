# Hello World: Go Todo API

A minimal in-memory REST API used as the demonstration application for the
Talos agentified SDLC. The application is intentionally simple so that the
focus of the demo remains on the agent harness, not the business logic.

## Endpoints

| Method | Path           | Description           |
|--------|----------------|-----------------------|
| GET    | `/healthz`     | Health check          |
| GET    | `/todos`       | List all todos        |
| POST   | `/todos`       | Create a new todo     |
| GET    | `/todos/{id}`  | Get a single todo     |
| PUT    | `/todos/{id}`  | Update a todo         |
| DELETE | `/todos/{id}`  | Delete a todo         |

## Run locally

```bash
go run .                       # http://localhost:8080
go test ./...                  # run unit tests
docker build -t talos/todo .   # build container image
docker run -p 8080:8080 talos/todo
```

## Logs

All logs are emitted as single-line JSON on stdout. Each log entry includes
`timestamp`, `level`, `message`, and `service: todo-api`, plus request-scoped
fields where applicable. This format is consumed by Arize Phoenix (see
`../observ/`) and the RCA agent (see `../rca-agent/`).
