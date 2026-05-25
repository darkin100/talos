# Code-Review Agent

Reviews a pull request diff with an LLM (via OpenRouter) and comments on the PR.

## Inputs (environment)

| Variable             | Required | Description                                |
|----------------------|----------|--------------------------------------------|
| `GITHUB_TOKEN`       | yes      | Token with PR write access                 |
| `GITHUB_REPOSITORY`  | yes      | `owner/repo`                               |
| `PR_NUMBER`          | yes      | Pull request number                        |
| `OPENROUTER_API_KEY` | yes      | OpenRouter API key                         |
| `MODEL`              | no       | Model id (default `deepseek/deepseek-v4-flash`) |

## Outputs

- Posts a single comment on the PR tagged `<!-- talos:code-review -->`.
- Exits with `0` on pass, `1` on fail (blocks the workflow).

## Run locally

```bash
docker build -t talos/code-review:v1 .
docker run --rm \
  -e GITHUB_TOKEN \
  -e GITHUB_REPOSITORY=darkin100/talos \
  -e PR_NUMBER=1 \
  -e OPENROUTER_API_KEY \
  talos/code-review:v1
```
