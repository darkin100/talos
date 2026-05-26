# Contract-Test Agent

Verifies the deployed Vercel API against the OpenAPI contract committed at
`todo-api/openapi.yaml`. Runs deterministic happy-path and negative tests
derived from the spec, plus a batch of LLM-generated edge cases grounded in
the same spec. Any contract violation opens a GitHub issue (labels
`talos-contract-test`, `incident`) and exits non-zero, pausing the route to
live.

## Inputs (environment)

| Variable             | Required | Description                                              |
|----------------------|----------|----------------------------------------------------------|
| `GITHUB_TOKEN`       | yes      | Token with `issues:write` access                          |
| `GITHUB_REPOSITORY`  | yes      | `owner/repo`                                              |
| `OPENROUTER_API_KEY` | yes      | OpenRouter API key                                        |
| `DEPLOYMENT_URL`     | yes      | Base URL of the deployed API (e.g. `https://x.vercel.app`) |
| `MODEL`              | no       | Model id (default `deepseek/deepseek-v4-flash`)          |
| `SPEC_FILE`          | no       | Path to OpenAPI YAML (default `/workspace/openapi.yaml`) |
| `COMMIT_SHA`         | no       | Commit being verified (added to issue body)               |
| `PR_NUMBER`          | no       | PR that introduced the change (added to issue body)       |
| `ARIZE_SPACE_ID`     | no       | Arize AX space id (enables tracing)                       |
| `ARIZE_API_KEY`      | no       | Arize AX API key (required with `ARIZE_SPACE_ID`)         |

## Exit codes

| Code | Meaning                                       |
|------|-----------------------------------------------|
| 0    | Contract holds; route to live clear           |
| 1    | Violation(s) found; issue raised, build red   |

## How tests are sourced

1. **Deterministic** — a hand-curated set covering each documented operation
   and its negative paths (missing fields, invalid ids, unknown ids, method
   not allowed). These must pass exactly.
2. **LLM-generated** — the model receives the OpenAPI document and produces
   5–8 edge cases. For LLM tests, any status code that is documented for the
   targeted operation is tolerated even when not in the model's
   `expected_status_codes` (the model is sometimes too narrow). Schema
   validation is always enforced.

Both groups feed into the same response-shape validation against the schemas
in the spec.

## Run locally

```bash
docker build -t talos/contract-test:v1 .
docker run --rm \
  -v "$PWD/todo-api:/workspace:ro" \
  -e GITHUB_TOKEN -e GITHUB_REPOSITORY=darkin100/talos \
  -e OPENROUTER_API_KEY \
  -e DEPLOYMENT_URL=https://your-preview.vercel.app \
  talos/contract-test:v1
```
