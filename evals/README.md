# Talos evals

Phase 0 of [docs/EVAL_STRATEGY.md](../docs/EVAL_STRATEGY.md): a plain-pytest
runner (no DeepEval — TODO.md #7) that replays the agents against the
harvested tasks in `datasets/` and grades the outcome with the code-based
graders from §2. Datasets are produced by working
[docs/EVAL_BACKLOG.md](../docs/EVAL_BACKLOG.md) items through the real
pipeline and harvesting the artefacts.

## Running locally

Requires docker, node 20+, and `OPENROUTER_API_KEY` (read from the repo-root
`.env` if present, like `scripts/local-demo.sh`). No GitHub token is needed:
replays run with `DRY_RUN=1` and hermetic inputs, so nothing is ever posted.

```bash
pip install -r evals/requirements.txt
pytest evals                          # regression suites, all agents, docker
pytest evals --agent code-review      # one agent
pytest evals --trials 3               # majority-of-3 per task (TODO.md #5)
pytest evals --mode direct            # host python instead of docker (faster,
                                      # but skips packaging-gap coverage)
pytest evals --suite capability       # the nightly hill instead of the gate
python evals/report.py                # render .results/results.json as markdown
```

`--mode docker` (default) builds and runs the real agent images, so it also
catches packaging gaps like the missing `COPY suppressions.json` that shipped
issue #42 — keep CI on docker mode.

## How a task replays

| agent | hermetic input in task dir | graded on |
|---|---|---|
| code-review | `diff.patch` | exit code vs `label.category` (clean categories must exit 0) |
| security-review | `diff.patch` | exit code vs `label.expected_verdict`; CWE mentions reported as info |
| rca | `app.log` | incident detection vs `label.incident`, plus `label.evidence_tokens` cited in the diagnosis |
| contract-test | `mutation.patch` (applied to `todo-api`, served locally) | mutation killed on `label.endpoint`; clean runs must hold |
| release-notes | `input.json` (`pr_title`, `pr_body`, `commit_messages`) | ≤300-word hard rule + every `#PR`/sha/tag reference grounded in the input |
| code (talos-bench) | — | not replayed here; runs in the nightly harness |

## Harvesting from Arize (§3.5)

`scripts/harvest_arize.py` turns the root spans Talos agents emit to Arize AX
into hermetic eval tasks under `datasets/<agent>/` (EVAL_STRATEGY.md §3.5). It
keeps one root span per trace (`name == "talos.<agent>.run"`), drops spans whose
output matches an `InfraFailure` signature (reusing `runner.INFRA_PATTERNS`),
scrubs secrets/PII, and writes a `NEEDS_LABEL` placeholder for the maintainer to
fill from the Arize human annotation. Tasks default to the **capability** suite
and carry `source_window` as a contamination guard so prompt-tuning can hold
them out.

```bash
# Live export from Arize (needs the harvest deps below)
pip install -r evals/scripts/requirements-harvest.txt
python evals/scripts/harvest_arize.py --agent code-review \
    --space-id SPACE --start 2026-06-01T00:00:00Z --end 2026-06-08T00:00:00Z

# Offline: harvest a previously exported parquet/json/jsonl/csv (json/jsonl need
# no extra deps); --dry-run reports without writing.
python evals/scripts/harvest_arize.py --agent rca --from-file traces.json \
    --start 2026-06-01 --end 2026-06-08 --dry-run
```

Only **live** export (or reading parquet/csv) needs `arize`/`pandas` — kept in
`scripts/requirements-harvest.txt`, deliberately out of `requirements.txt` so CI
stays lean. Two limitations are inherent to the traces, not bugs: (1) the raw
hermetic payload (`diff.patch` / `app.log` / `input.json` commit_messages /
`mutation.patch`) is **not** in a root span, so harvested inputs are written with
a `NEEDS_HYDRATION` marker for manual hydration; contract-test is skipped with a
reason. (2) The reviewed SHA for the code-review `source/` snapshot freeze is not
on the root span, so it falls back to `NEEDS_SHA` plus a `capture_snapshot.sh`
reminder. The harvester never overwrites an existing task dir (skip + warn).

## Infra vs agent failure

Trials that never meaningfully executed (docker build/pull flakes, upstream
5xx, timeouts, missing hermetic inputs) raise `InfraFailure` and surface as
pytest **skips**, never failures — pass rates only count executed trials.
This is a hard lesson from the harness-failure log in EVAL_BACKLOG.md.

## Outputs

- pytest exit code: the gate.
- `evals/.results/results.json`: per-task outcomes; `report.py` renders the
  per-category markdown table the CI workflow posts on PRs (never a single
  aggregate number — see EVAL_STRATEGY.md anti-patterns).
