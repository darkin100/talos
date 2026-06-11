# Code Agent

Picks up a GitHub issue, runs the [Pi coding agent](https://pi.dev) to
implement the change, then commits the result, pushes a branch, and opens a
pull request. Triggered by an `@talos` mention in a comment on an issue.

## Inputs (environment)

| Variable             | Required | Description                                                |
|----------------------|----------|------------------------------------------------------------|
| `GITHUB_TOKEN`       | yes      | Default Actions token with `contents:write`, `issues:write`, `pull-requests:write`. Used for push, PR creation, comments/reactions, and firing the `repository_dispatch` that wakes up the SDLC workflow. |
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
- Emits an OpenInference-compliant trace to Arize AX (see `docs/openinference-spec/`): a root `talos.code.run` AGENT span (issue prompt as input, Pi's summary as output, plus repo/issue/model/verdict attributes), a CHAIN span per Pi turn, an LLM span per assistant message (input/output messages, tool calls, token counts reconstructed from Pi's JSON event stream), and a TOOL span per tool execution.

## Exit codes

- `0` — PR opened, or no changes were needed.
- `1` — Pi failed, push failed, or the PR could not be opened.

## Run locally

```bash
docker build -t talos/code:v1 .
docker run --rm \
  -v "$PWD/..:/workspace" \
  -e GITHUB_TOKEN \
  -e GITHUB_REPOSITORY=darkin100/talos \
  -e ISSUE_NUMBER=42 \
  -e OPENROUTER_API_KEY \
  talos/code:v1
```

## How the SDLC handoff works

GitHub deliberately suppresses downstream `pull_request` workflow runs for
PRs created by the default `GITHUB_TOKEN` (loop-prevention). Rather than
pay for that with a long-lived push PAT, the agent:

1. Pushes the branch and opens the PR with `GITHUB_TOKEN`.
2. Calls `POST /repos/{owner}/{repo}/dispatches` with
   `event_type=talos-pr-ready` and `client_payload.pr_number=<N>`.
3. `talos-sdlc.yml` listens on `repository_dispatch: [talos-pr-ready]`
   and runs code-review / security-review / auto-merge against that PR.

`contents: write` on the workflow's `GITHUB_TOKEN` is enough to fire the
dispatch — no PAT required.

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
