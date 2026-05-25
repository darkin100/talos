# Todo API

A minimal in-memory REST API used as the demonstration application for the
Talos agentified SDLC. Deployed as a single [Vercel Function](https://vercel.com/docs/functions)
under `api/handler.js`, with a `vercel.json` rewrite mapping every `/api/*`
request to it.

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
todo-api/
├── api/
│   └── handler.js    # single Vercel function — internal router by `slug`
├── lib/
│   ├── logging.js
│   └── store.js
├── test/
│   └── store.test.js
├── dev-server.js     # local-only HTTP server, not used by Vercel
├── package.json
└── vercel.json       # rewrites /api/:path* -> /api/handler?slug=:path*
```

### Why one function instead of one per route?

Vercel deploys each `api/*.js` file as a separate serverless function with
its own process. Per-route files therefore can never share in-memory state
— `POST /api/todos` (in `todos.js`) and `GET /api/todos/:id` (in `[id].js`)
would each see an empty store. A single function plus a rewrite keeps CRUD
intact within a warm function instance.

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
request-scoped fields where applicable. The RCA agent's `scan_log_file`
heuristic relies on this shape.

In production the workflow captures these via `vercel logs` and feeds
them to the RCA agent (see `../agents/rca/`).
