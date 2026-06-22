# Talos — evaluation architecture

How the eval system actually works end to end: where tasks come from, how a run
is executed and graded, and how the result becomes a per-PR signal. This is the
"bring it to life" companion to [`EVAL_STRATEGY.md`](./EVAL_STRATEGY.md) (the
why) and [`ARCHITECTURE.md`](./ARCHITECTURE.md) (the platform).

## 1 · The big picture

The whole system in one loop: tasks are collected, run on every PR, and turned
into a signal — and real runs feed new tasks back in (the flywheel).

```mermaid
flowchart LR
  sources["Task sources<br/>seeded · pipeline · Arize"]
  datasets[("evals/datasets/<br/>tasks + ground-truth labels")]
  run["CI runner<br/>replay each agent in Docker<br/>× N trials → grade"]
  report["report.py<br/>pass@1 · majority pass@3<br/>Δ vs baseline"]
  comment["Sticky PR comment"]

  sources --> datasets --> run --> report --> comment
  run -.->|"flywheel: live traces → fresh tasks"| sources

  classDef store fill:#fff3cd,stroke:#b8860b,color:#000;
  class datasets store;
```

## 2 · Execution detail

How a PR run actually executes and grades, and how the committed baseline (a
separate manual job) gives the report something to diff against.

```mermaid
flowchart TB
  datasets[("evals/datasets/&lt;agent&gt;/&lt;id&gt;/<br/>task.json · hermetic input · source/ snapshot")]

  %% ---- the two suites ----
  regression["regression — the GATE<br/>per-PR · trials/task = 3"]
  capability["capability — the HILL<br/>nightly"]
  datasets --> regression
  datasets --> capability

  %% ---- execution ----
  regression --> trigger["talos-evals.yml (CI)<br/>on: PR touching agents/** or evals/**"]

  subgraph RUN["the evals/ runner"]
    direction TB
    replay["runner.replay()<br/>run agent in Docker · DRY_RUN · hermetic input<br/>repeated × N trials"]
    infra{"InfraFailure?<br/>(platform vs agent)"}
    skip["SKIP<br/>never counts as an agent fail"]
    grade["graders.py<br/>code-based verdict match"]
    majority["test_regression.py<br/>strict majority of graded trials"]
    replay --> infra
    infra -->|"yes — platform broke"| skip
    infra -->|no| grade --> majority
  end
  trigger --> replay

  %% ---- baseline (separate manual job) ----
  recast["talos-evals-recast.yml (CI)<br/>workflow_dispatch · full suite, all agents"]
  groundtruth[("ground-truth.json<br/>committed reference + provenance")]
  datasets -.->|"all agents"| recast -->|"commits"| groundtruth

  %% ---- results + reporting ----
  majority --> results[("results.json<br/>outcome · pass_rate k/N")]
  results --> report["report.py<br/>pass@1 + majority pass@3 · Δ vs ground truth"]
  groundtruth -.->|"--baseline (diffed by agent·task)"| report
  report --> comment["Sticky PR comment<br/>regressions · per-task vs-base · freshness"]

  classDef store fill:#fff3cd,stroke:#b8860b,color:#000;
  classDef gate fill:#d4edda,stroke:#1f8a4c,color:#000;
  class datasets,results,groundtruth store;
  class regression,capability gate;
  style RUN fill:#eef4fb,stroke:#08427b;
```

## Reading the diagram

1. **Task sources** — every eval task lands in `evals/datasets/<agent>/<id>/`
   the same way regardless of origin: *seeded* (a planted flaw on a fixture
   branch), *pipeline-harvested* (a real `@talos` run captured with its known
   ground truth), or *Arize-harvested* (`harvest_arize.py` turning live traces
   into draft tasks). The maintainer supplies the one thing a machine can't — the
   ground-truth label.
2. **Two suites** — the *same* tasks are read two ways: the **regression** suite
   is the gate that runs on every PR at 3 trials/task; the **capability** suite
   is the nightly hill being climbed. Tasks graduate capability → regression once
   solved reliably.
3. **Execution** — CI discovers the affected suite, then `runner.replay()` runs
   each agent **in Docker with `DRY_RUN`** (no real comments/issues/deploys) on
   the task's hermetic input, repeated for N trials. The key fork is
   **InfraFailure**: a run that broke for platform reasons (network, model
   outage, docker flake) is **skipped**, never scored against the agent. Surviving
   runs are graded by a deterministic **code-based grader**, and the task passes
   on a **strict majority** of its graded trials.
4. **Results → report** — outcomes are written to `results.json`, and `report.py`
   renders the per-PR comment: per-category, both **pass@1** (trial-level) and
   **majority pass@3** (task-level), and the **Δ vs the committed ground-truth
   baseline** (`evals/.baselines/ground-truth.json`) with a regressions callout.
   The baseline is **not** recomputed per-PR — it's a committed snapshot diffed by
   `(agent, task)`, so a PR only has to test the change, not re-test its base. Its
   `.meta.json` provenance (cast date, commit, trials) is surfaced in the comment
   so reviewers can judge freshness; once it drifts from the live grader/model,
   the Δ reads as indicative.
5. **Re-casting the baseline** — `talos-evals-recast.yml` is a manual
   (`workflow_dispatch`) job that re-runs the **full suite across all agents** and
   commits the result as the new ground truth. This decouples *establishing the
   reference* (deliberate, occasional) from *measuring a change* (every PR), and
   replaces the old per-PR base re-run that cost ~2× the work. Trade-off: that
   back-to-back base run controlled for model/grader drift; re-casting often
   enough keeps the drift small, and the comment's freshness line makes staleness
   visible.
6. **The flywheel** — while running, agents emit traces to Arize; `harvest_arize.py`
   feeds those back in as new tasks, so the suite grows from real usage.

## The one rule that makes the numbers trustworthy

Everything hinges on the **infra-failure vs agent-failure split** (the `infra?`
diamond). A green dashboard is only meaningful if "the platform broke" can never
masquerade as "the agent passed" — or vice versa. The runner enforces this in
code (`evals/runner.py` `INFRA_PATTERNS` → pytest skip), which is why the eval
results can be used as a real quality gate rather than noise.

---

**Related:** [`EVAL_STRATEGY.md`](./EVAL_STRATEGY.md) ·
[`EVAL_BACKLOG.md`](./EVAL_BACKLOG.md) · [`ARCHITECTURE.md`](./ARCHITECTURE.md)
