# Code Agent

Picks up a GitHub issue, runs the [Pi coding agent](https://pi.dev) to
implement the change, then commits the result, pushes a branch, and opens a
pull request. Triggered by an `@talos` mention in a comment on an issue.

## Inputs (environment)

| Variable             | Required | Description                                                |
|----------------------|----------|------------------------------------------------------------|
| `GITHUB_TOKEN`       | yes      | Token with `issues:write` (used for reactions/comments)    |
| `PUSH_TOKEN`         | yes      | PAT with `contents:write` + `pull-requests:write`. A separate token is needed so the resulting PR triggers downstream workflows (the default `GITHUB_TOKEN` suppresses `workflow_run` events). |
| `GITHUB_REPOSITORY`  | yes      | `owner/repo`                                                |
| `ISSUE_NUMBER`       | yes      | Issue number to resolve                                     |
| `COMMENT_ID`         | no       | Id of the triggering `@talos` comment (for the eyes/rocket reactions) |
| `TRIGGERED_BY`       | no       | Login of the user who invoked the agent (attached to traces) |
| `OPENROUTER_API_KEY` | yes      | OpenRouter API key, passed through to Pi                    |
| `MODEL`              | no       | Model id (default `anthropic/claude-haiku-4.5`)            |
| `WORKSPACE`          | no       | Path to the repo checkout the agent should edit (default `/workspace`) |
| `GITHUB_RUN_ID`      | no       | Used to disambiguate branch names across reruns             |
| `ARIZE_SPACE_ID`     | no       | Arize AX space id; enables tracing if set                   |
| `ARIZE_API_KEY`      | no       | Arize AX API key; required with `ARIZE_SPACE_ID`            |
| `ARIZE_PROJECT_NAME` | no       | Arize project name (default `talos-code`)                  |

## Outputs

- Opens a PR titled `talos: <issue title>` from a fresh `talos/issue-<N>-<run>` branch, with `Closes #<N>` in the body.
- Posts a single follow-up comment on the issue with the PR link or the failure reason.
- Reacts to the triggering comment: `eyes` on start, `rocket` on success, `confused` on no-op or Pi failure.
- Emits a `talos.code.run` span to Arize AX with attributes: repo, issue number, model, pi exit code, event count, verdict, pr url.

## Exit codes

- `0` — PR opened, or no changes were needed.
- `1` — Pi failed, push failed, or the PR could not be opened.

## Run locally

```bash
docker build -t talos/code:v1 .
docker run --rm \
  -v "$PWD/..:/workspace" \
  -e GITHUB_TOKEN \
  -e PUSH_TOKEN \
  -e GITHUB_REPOSITORY=darkin100/talos \
  -e ISSUE_NUMBER=42 \
  -e OPENROUTER_API_KEY \
  talos/code:v1
```

## How Pi is wired up

The orchestrator invokes:

```
pi --mode json --provider openrouter --model "$MODEL" --no-session \
   --append-system-prompt "<harness rules>" \
   "<composed prompt with issue title, body, and discussion>"
```

Pi discovers `.pi/skills/talos-coding.md` automatically from the workspace
root and pulls it into context. Tool calls (file reads/edits/bash) run
without prompting because Pi is configured for unattended use inside the
container — exactly the pattern the Pi docs recommend ("No permission
popups. Run in a container").
