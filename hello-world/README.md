# Hello World: Node Todo API

A minimal in-memory REST API used as the demonstration application for the
Talos agentified SDLC. Deployed as vanilla [Vercel Functions](https://vercel.com/docs/functions)
— each route is its own file under `api/`.

The application is intentionally simple so that the focus of the demo
remains on the agent harness, not the business logic.

## Endpoints

| Method | Path                  | Description                                |
|--------|-----------------------|--------------------------------------------|
| GET    | `/api/healthz`        | Health check                               |
| GET    | `/api/todos`          | List all todos                             |
| POST   | `/api/todos`          | Create a new todo (body: `{ "title": "" }`) |
| GET    | `/api/todos/search?q=`| Case-insensitive title substring search    |
| GET    | `/api/todos/[id]`     | Get a single todo                          |
| PUT    | `/api/todos/[id]`     | Update a todo                              |
| DELETE | `/api/todos/[id]`     | Delete a todo                              |

## Layout

```
hello-world/
├── api/
│   ├── healthz.js
│   ├── todos.js
│   └── todos/
│       ├── [id].js
│       └── search.js
├── lib/
│   ├── logging.js
│   └── store.js
├── test/
│   └── store.test.js
├── dev-server.js     # local-only HTTP server, not used by Vercel
├── package.json
└── vercel.json
```

## Run locally

```bash
node dev-server.js          # serves on http://localhost:3000
npm test                    # runs node:test against the store
```

`dev-server.js` exists so contributors do not need the Vercel CLI or a
Vercel auth token. It mounts the same handlers Vercel uses in production
but reuses the host's `http` module instead.

## Deploy to Vercel

Production deploys are driven from `.github/workflows/talos-sdlc.yml`,
which runs `vercel deploy --prod` after PR merge using a linked Vercel
project. Required repository secrets:

| Secret              | Source                                  |
|---------------------|-----------------------------------------|
| `VERCEL_TOKEN`      | <https://vercel.com/account/tokens>     |
| `VERCEL_ORG_ID`     | `vercel link` populates `.vercel/project.json` |
| `VERCEL_PROJECT_ID` | same as above                           |

For a one-time manual deploy from your laptop:

```bash
npx vercel link                                          # link this dir to a Vercel project
npx vercel pull --yes --environment=production           # download project config
npx vercel build --prod                                  # build into .vercel/output
npx vercel deploy --prebuilt --prod --token=$VERCEL_TOKEN
```

## Persistence note

The in-memory store does **not** survive Vercel cold starts and is not
shared across function instances. That is acceptable for the harness
demo — the agents only verify the API responds 2xx. Upgrade to a
persistent store (e.g. [Vercel KV](https://vercel.com/docs/storage/vercel-kv))
if real persistence is needed.

## Logs

All logs are emitted as single-line JSON on stdout. Each entry includes
`timestamp`, `level`, `message`, and `service: todo-api`, plus
request-scoped fields where applicable. This is the same shape the Go
implementation emitted, so the RCA agent's heuristics (`scan_log_file`)
work without modification.

In production the workflow captures these via `vercel logs` and feeds
them to the RCA agent (see `../rca-agent/`).
