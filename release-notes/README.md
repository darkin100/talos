# Release-Notes Generator

Generates human-readable release notes from a merged PR's title, body and
commit messages. Always writes to `/workspace/RELEASE_NOTES.md` if that
directory is mounted; optionally creates a GitHub Release when `RELEASE_TAG`
is provided.

## Inputs (environment)

| Variable             | Required | Description                                |
|----------------------|----------|--------------------------------------------|
| `GITHUB_TOKEN`       | yes      | Token with `releases:write` access          |
| `GITHUB_REPOSITORY`  | yes      | `owner/repo`                               |
| `PR_NUMBER`          | yes      | Merged PR number                            |
| `OPENROUTER_API_KEY` | yes      | OpenRouter API key                         |
| `MODEL`              | no       | Model id (default `deepseek/deepseek-v4-flash`) |
| `RELEASE_TAG`        | no       | Tag to attach the release to                |

## Run locally

```bash
docker build -t talos/release-notes:v1 .
docker run --rm \
  -v "$PWD:/workspace" \
  -e GITHUB_TOKEN -e GITHUB_REPOSITORY=darkin100/talos -e PR_NUMBER=1 \
  -e OPENROUTER_API_KEY -e RELEASE_TAG=v0.1.0 \
  talos/release-notes:v1
```
