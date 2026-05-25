# RCA Agent (Route-Course Analysis)

Monitors application logs and Arize Phoenix metrics after deployment. If any
error events are observed, it performs root-cause analysis with an LLM,
opens a GitHub issue, and exits non-zero to pause the route to live.

## Inputs (environment)

| Variable             | Required | Description                                              |
|----------------------|----------|----------------------------------------------------------|
| `GITHUB_TOKEN`       | yes      | Token with `issues:write` access                          |
| `GITHUB_REPOSITORY`  | yes      | `owner/repo`                                              |
| `OPENROUTER_API_KEY` | yes      | OpenRouter API key                                        |
| `MODEL`              | no       | Model id (default `deepseek/deepseek-v4-flash`)          |
| `LOG_FILE`           | no       | Path to JSON log file (default `/logs/app.log`)          |
| `SOURCE_DIR`         | no       | Source root for code context (default `/workspace`)       |
| `PHOENIX_URL`        | no       | Phoenix base URL (e.g. `http://phoenix:6006`)             |
| `COMMIT_SHA`         | no       | Commit being verified (added to issue body)               |
| `PR_NUMBER`          | no       | PR that introduced the change (added to issue body)       |

## Exit codes

| Code | Meaning                                  |
|------|------------------------------------------|
| 0    | No errors detected; route to live clear  |
| 1    | Errors detected; issue raised, build red |

## Run locally

```bash
docker build -t talos/rca:v1 .
docker run --rm \
  -v "$PWD/hello-world:/workspace:ro" \
  -v "$PWD/.logs:/logs:ro" \
  -e GITHUB_TOKEN -e GITHUB_REPOSITORY=darkin100/talos \
  -e OPENROUTER_API_KEY \
  -e PHOENIX_URL=http://phoenix:6006 \
  --network talos-net \
  talos/rca:v1
```
