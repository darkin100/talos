# Security-Review Agent

Scans a pull request diff for security issues with an LLM (via OpenRouter)
and comments on the PR only when problems are found.

## Inputs (environment)

| Variable             | Required | Description                                |
|----------------------|----------|--------------------------------------------|
| `GITHUB_TOKEN`       | yes      | Token with PR write access                 |
| `GITHUB_REPOSITORY`  | yes      | `owner/repo`                               |
| `PR_NUMBER`          | yes      | Pull request number                        |
| `OPENROUTER_API_KEY` | yes      | OpenRouter API key                         |
| `MODEL`              | no       | Model id (default `anthropic/claude-sonnet-4-6`) |

## V1 pass criteria

A "pass" means no comment is posted on the PR at all — i.e. the model
returned `verdict: pass` and zero findings.

## Run locally

```bash
docker build -t talos/security-review:v1 .
docker run --rm \
  -e GITHUB_TOKEN \
  -e GITHUB_REPOSITORY=darkin100/talos \
  -e PR_NUMBER=1 \
  -e OPENROUTER_API_KEY \
  talos/security-review:v1
```
