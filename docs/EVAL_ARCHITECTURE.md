# Talos — evaluation architecture

How the eval system actually works end to end: where tasks come from, how a run
is executed and graded, and how the result becomes a per-PR signal. This is the
"bring it to life" companion to [`EVAL_STRATEGY.md`](./EVAL_STRATEGY.md) (the
why) and [`ARCHITECTURE.md`](./ARCHITECTURE.md) (the platform).

```mermaid
flowchart TB
  %% ---- where tasks come from ----
  subgraph SRC["1 · Task sources — how eval tasks are created"]
    direction LR
    seeded["Seeded fixtures<br/>planted flaws on eval-seed/* branches"]
    pipe["Pipeline harvest<br/>real @talos runs → labelled task"]
    arize["Arize harvest<br/>harvest_arize.py reads live traces"]
  end

  datasets[("evals/datasets/&lt;agent&gt;/&lt;id&gt;/<br/>task.json · hermetic input · source/ snapshot")]
  maintainer["👤 Maintainer<br/>supplies ground-truth label (NEEDS_LABEL)"]

  seeded --> datasets
  pipe --> datasets
  arize --> datasets
  maintainer -.->|labels| datasets

  %% ---- the two suites ----
  subgraph SUITES["2 · Two suites — same tasks, different cadence"]
    direction LR
    regression["regression — the GATE<br/>per-PR · trials/task = 3"]
    capability["capability — the HILL<br/>nightly"]
  end
  datasets --> regression
  datasets --> capability

  %% ---- execution ----
  trigger["talos-evals.yml (CI)<br/>on: PR touching agents/** or evals/**"]
  regression --> trigger

  subgraph RUN["3 · Execution — the evals/ runner"]
    direction TB
    discover["conftest.py<br/>discover tasks (--agent / --suite / --trials)"]
    replay["runner.replay()<br/>run agent in Docker · DRY_RUN · hermetic input<br/>repeated × N trials"]
    infra{"InfraFailure?<br/>(platform vs agent)"}
    skip["SKIP<br/>never counts as an agent fail"]
    grade["graders.py<br/>code-based verdict match (the gate)"]
    majority["test_regression.py<br/>strict majority of graded trials"]
    discover --> replay --> infra
    infra -->|"yes — platform broke"| skip
    infra -->|no| grade --> majority
  end
  trigger --> discover

  %% ---- results + reporting ----
  results[("results.json<br/>outcome · pass_rate k/N · detail")]
  majority --> results

  baseline["Baseline run<br/>same suite on the PR's base ref"]
  trigger -.-> baseline --> results

  report["report.py<br/>per-category · pass@1 + majority pass@3 · Δ vs base"]
  comment["Sticky PR comment<br/>regressions callout · per-task vs-base"]
  results --> report --> comment

  %% ---- the flywheel ----
  agentcall["agents call OpenRouter to reason<br/>+ emit OpenInference spans to Arize"]
  replay --> agentcall
  agentcall -.->|"flywheel: real traces → fresh tasks"| arize

  classDef store fill:#fff3cd,stroke:#b8860b,color:#000;
  classDef person fill:#08427b,color:#fff,stroke:#052e56;
  classDef gate fill:#d4edda,stroke:#1f8a4c,color:#000;
  class datasets,results store;
  class maintainer person;
  class regression,capability gate;
  style RUN fill:#eef4fb,stroke:#08427b;
  style SRC fill:#f7f7f7,stroke:#888;
  style SUITES fill:#f7f7f7,stroke:#888;
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
   **majority pass@3** (task-level), and — when CI also runs the **baseline** on
   the PR's base ref — the **Δ vs base** with a regressions callout.
5. **The flywheel** — while running, agents emit traces to Arize; `harvest_arize.py`
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
