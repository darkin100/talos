# Talos Evaluation Strategy

This document defines the evaluation strategy for the six agents in the Talos SDLC and for the harness as a whole. Vocabulary follows [`docs/GLOSSARY.md`](./GLOSSARY.md), which in turn follows Anthropic's [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents). If a term here is unfamiliar, the glossary is the source of truth.
## 0. Executive summary

For each of the six Talos agents (`code`, `code-review`, `security-review`, `contract-test`, `release-notes`, `rca`) we build two **eval suites**: a **regression suite** (~20 tasks) that runs on every PR that touches an agent at **trials/task = 3** with **strict-majority grading** (the runner's `--trials 3` default; a task passes only if a strict majority of its *graded* trials pass — an exact tie fails, and infra-failed trials are excluded, never counted against the agent), and a **capability suite** (~50 tasks, runs nightly, the hill we're climbing). Each task has **reference solutions** and is graded by a **code-based grader** (gate) plus a **model-based grader** (signal); human SMEs recalibrate the model-based grader quarterly.

Two numbers are reported everywhere, because they answer different questions: **pass@1** = the fraction of *individual* graded trials that passed (trial-level stability), and **majority pass@3** = the task-level outcome (a task passes if a strict majority of its 3 graded trials pass). The gate is the task-level majority pass@3; pass@1 is the variance check. Any threshold is stated in **units the suite size resolves**: on a suite of S tasks one task is worth `100/S` percentage points, so a regression suite of ~20 tasks moves in 5 pp steps and a threshold finer than one task (e.g. a literal "97%") cannot be expressed — actual per-suite sizes and their pp-per-task are given inline in each §2 gate.

We grade **outcomes** (the PR comment, the patch, the issue body, the release note) — never the path the agent took to produce them. The two grader families come from different model providers to avoid self-preference bias. Tasks graduate from capability → regression as they're solved reliably — operationally, *reliably* means sustained majority pass@3 across trials, not a single lucky pass (see §1 principle 5). The capability suite always has fresh hard tasks and is also run nightly at trials/task = 3, tracked as both pass@1 (trial-level) and majority pass@3 (task-level); on a ~50-task capability suite one task is 2 pp, so the climb is reported in 2 pp increments, not finer.

Above the per-agent layer, the harness is graded by **DORA + AI caveats** (deployment frequency vs change failure rate plotted together), plus Talos-specific cross-cutting metrics: **gate escape rate**, **override rate**, **cost per PR**, **trust-cost ratio**, and **harness drift**.

The whole thing rides on a trace store — **Arize AX** today (Phoenix is the API-compatible OSS equivalent): every agent's existing OpenInference span tree *is* the **transcript**. Online evaluators score those spans post-hoc; captured production flows are harvested back into dataset tasks (§3.5); dataset experiments re-run suites on prompt changes and post a diff to the PR.

**Minimum viable cut to demo this**: 5 tasks per agent + 1 code-based grader each + a per-PR comment showing pass/fail vs main. Everything else is incremental on that.

## 1. Design principles

These are direct applications of Anthropic's roadmap to Talos.

1. **Start with 20–50 tasks per agent, sourced from real failures.** Pull
   from this repo's PRs, closed issues, RCA incidents. Don't wait for a
   "complete" suite.
2. **Two grader types per agent.** A code-based grader (cheap, deterministic,
   the gate) plus a model-based grader (nuanced, calibrated against humans,
   the signal). Human graders calibrate the model-based grader on a quarterly
   cadence.
3. **Grade outcome, not path.** Anthropic's warning is direct: "We've found
   this approach too rigid… agents regularly find valid approaches that eval
   designers didn't anticipate." For Talos this means grade what the agent
   *produced* (the PR comment, the issue body, the release note, the patch) —
   not the tool-call sequence inside the trial.
4. **Two judges from different model families.** Self-preference bias is the
   most-replicated failure mode in LLM-as-judge literature. Never use the
   same model family for generator and grader.
5. **Capability suites graduate to regression suites — reliably means across
   trials, not a single lucky pass.** A capability task graduates to the
   regression suite once it passes **majority pass@3** (strict majority of its
   3 graded trials, the same `--trials 3` strict-majority grading the per-PR
   gate uses) on **N consecutive nightly runs** (recommend N = 3 nights, or a
   clean `3/3` pass@1 on the latest run). Then move it across and add a harder
   capability task. A single green trial never graduates a task — the whole
   point of trials/task is that one lucky pass is not evidence of reliability.
   This is Anthropic's Step 7.
6. **The trace store is the substrate.** Every agent already emits
   OpenInference spans to **Arize AX** (the **transcript** in glossary terms;
   Phoenix is the API-compatible OSS equivalent). Online evaluators score
   those spans post-hoc; captured flows are harvested into dataset tasks
   (§3.5); dataset experiments re-run task suites on prompt changes.

## 2. Per-agent strategy

Each agent gets the same six-field treatment:

- **Task suite** — capability and regression, what the tasks look like
- **Outcome** — what gets graded (the artefact, not the path)
- **Grader mix** — code-based + model-based + human cadence
- **Gate** — what blocks a prompt change or a PR
- **Saturation watch** — when to graduate tasks
- **Online signal** — the production-monitoring layer

### 2.1 Code agent (Pi code-gen)

| Field                   | Value                                                                                                                                                                                                                                                    |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Anthropic type          | Coding agent                                                                                                                                                                                                                                             |
| Task suite              | **Talos-bench**: 20 resolved issues from this repo, each with merged diff + the test suite at that SHA, runnable from a stable environment snapshot. Starts as a **capability suite**; tasks the agent solves reliably graduate to the regression suite. |
| Outcome                 | The patch (diff) produced for the issue, plus pass/fail of the hidden test suite.                                                                                                                                                                        |
| Code-based grader       | `tests_pass@1` on hidden tests (binary, primary), `cost_to_success` (Pi turns + tokens, threshold), file-overlap Jaccard vs merged diff (sanity, not gate)                                                                                               |
| Model-based grader      | Pairwise comparison against the merged diff on (correctness, minimality, maintainability). Two graders from different families; only fail on agreement.                                                                                                  |
| Human grader cadence    | Quarterly: SME re-grades 10 random trials to recalibrate the model-based grader.                                                                                                                                                                         |
| Gate                    | Nightly only — per-PR uses real downstream tests. Run at trials/task = 3. Block prompt promotion if **pass@1** (trial-level) drops more than one suite-resolution step from the 30-day baseline — on the at-scale Talos-bench (20 tasks) that is > 5 pp = ≥ 2 tasks regressing, on the current 5-task cut (`code/capability`, 20 pp/task) that is ≥ 1 task — **OR** if **majority pass@3** (task-level) regresses on any task, OR `cost_to_success` rises > 50%. Report both pass@1 (fraction of all graded trials passing) and majority pass@3.                                                                                                  |
| Saturation watch        | Measured at trials/task = 3: when Talos-bench reaches ≥ 80% pass@1 (≥ 16/20 of the graded-trial total at the 20-task scale, resolvable in 5 pp/task steps; on the current 5-task cut that is ≥ 4/5, 20 pp/task), graduate each instance that individually passes **majority pass@3 on 3 consecutive nights** to regression, and seed harder tasks (multi-file, cross-cutting refactors).                                                                                                                   |
| Online signal           | Existing `talos.code.run` span gets `eval.tests_pass` and `eval.judge_score` attached asynchronously by a Phoenix online evaluator after the PR merges.                                                                                                  |
| Nightly capability eval | SWE-bench Verified Lite (50 instances) — wide-net regression detector.                                                                                                                                                                                   |
| **MVP first cut**       | 5 trivial fix-a-bug tasks from this repo's closed issues. One grader: `tests_pass@1`. Run nightly; surface pass rate in a single Phoenix dashboard tile.                                                                                                 |

### 2.2 Code-review agent

| Field                | Value                                                                                                                                                                                                                                                                                                                                      |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Anthropic type       | Coding agent (review variant)                                                                                                                                                                                                                                                                                                              |
| Task suite           | 100 historical PRs from this repo, each with a **reference solution**: the labelled `{real_defect, missing_test, maintainability, style_only, none}` category and the expected verdict. **Balanced problem set** — must include PRs where the agent *should not* find issues (style-only, trivial), or one-sided optimisation will follow. |
| Outcome              | The PR comment posted (or not), plus the exit code (pass/fail).                                                                                                                                                                                                                                                                            |
| Code-based grader    | Verdict match (assertion on outcome). Per-category precision/recall/F1 — never averaged, always reported per bucket (one of the explicit anti-patterns: single-number summaries hide regressions in critical categories). FPR on `style_only` PRs (trust-collapse indicator).                                                              |
| Model-based grader   | A second LLM (different family) labels the agent's comment with one of the same categories; agreement required before flagging "fail".                                                                                                                                                                                                     |
| Human grader cadence | Monthly: SME re-labels a 10% sample from production to refresh task suite (Anthropic Step 8 — keep the suite alive).                                                                                                                                                                                                                       |
| Gate                 | Per-PR at trials/task = 3 (strict-majority verdict per PR, the workflow's `--trials 3` default): replay the regression suite and fail if any **per-category F1**, computed on the **majority pass@3** verdicts, drops by more than one bucket-resolution step vs main. State the per-bucket size and set the threshold to that step, not a finer 5 pp: at scale the 100-PR suite splits over 5 categories ≈ 20 PRs/bucket ≈ 5 pp granularity (and F1 combines precision and recall, so a single flip can move F1 ~5–10 pp); the current regression cut is 12 tasks (≈ 8 pp/task) split fewer ways, so a bucket step is coarser still. Also report **pass@1** verdict-match across all graded trials for stability. Never aggregate F1 across buckets. Nightly: replay [Martian code-review benchmark](https://github.com/withmartian/code-review-benchmark) for cross-tool comparability.                                                                                                                         |
| Saturation watch     | Measured at trials/task = 3 on majority pass@3 verdicts: when **every in-scope category's** F1 reaches ≥ 0.90 — expressed to the bucket's resolution (~20 PRs/category ≈ 0.05 steps at scale, coarser on the current 12-task cut) — graduate and add harder tasks (multi-file PRs, subtle correctness bugs, race conditions). Never aggregate F1 across buckets for this trigger.                                                                                                                                                                                                                            |
| Online signal        | **Override rate** — % of merger-overrode agent verdicts. Rises before F1 does.                                                                                                                                                                                                                                                             |
| **MVP first cut**    | 10 labelled PRs (5 with real defects, 5 style-only). One grader: verdict match. Per-PR comment shows the diff vs main on these 10.                                                                                                                                                                                                         |

### 2.3 Security-review agent

| Field                | Value                                                                                                                                                                                                                                                        |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Anthropic type       | Coding agent (security variant)                                                                                                                                                                                                                              |
| Task suite           | 30 [Juliet](https://samate.nist.gov/SARD/test-suites/) flows seeded into a small Node fixture, each labelled by CWE in scope (injection, auth, crypto, secret leak). 20 known-clean PRs from this repo (must produce zero findings — the **balanced** half). |
| Outcome              | The PR comment with findings (severity, title, detail), plus exit code.                                                                                                                                                                                      |
| Code-based grader    | **Per-CWE** precision/recall (never averaged), severity-weighted confusion matrix (medium/high/critical miscalls cost more), FPR on the clean half, suppression-list utilisation.                                                                            |
| Model-based grader   | Independent security-tuned LLM grades severity calibration (was a "high" really high?). SARIF diff vs Snyk Code / Semgrep on identical PRs as an external cross-check.                                                                                       |
| Human grader cadence | Quarterly: security SME re-grades severity on a 10-task sample.                                                                                                                                                                                              |
| Gate                 | At trials/task = 3 with strict-majority grading: block if any `high`/`critical` golden case fails its **majority pass@3** (truth missed in ≥ 2 of 3 graded trials) — a single flaky trial or one infra failure never trips the gate. Block if per-CWE recall, computed on majority pass@3 outcomes, falls below the threshold nearest 70% that the **bucket resolves**: with ~7–8 flows/CWE at scale the steps are 6/8 = 75% / 5/7 ≈ 71%, so set the gate at **< 71%** (≥ 1 missed flow in a 7-flow CWE); on the current 10-task regression cut (10 pp/task) state the equivalent per-task step. Also report per-CWE **pass@1** across all graded trials.                                                                                                                                                             |
| Saturation watch     | Measured at trials/task = 3 on majority pass@3 outcomes: graduate when every in-scope CWE's F1 reaches the resolvable step at or above 0.85 — with ~7–8 flows/CWE that is effectively ≥ 6/7 caught (the exact 0.85 value is unreachable on a 7–8-flow bucket; round to the nearest step) — then add CWE categories (e.g. SSRF, deserialisation).                                                                                                                                                            |
| Online signal        | Suppression-list utilisation — each new entry is a labelled example for the suite.                                                                                                                                                                           |
| **MVP first cut**    | 5 Juliet flows (one per CWE in scope) + 5 clean PRs. One grader: per-CWE recall ≥ 1 and clean-PR FPR = 0.                                                                                                                                                    |

### 2.4 Contract-test agent

| Field                | Value                                                                                                                                                                                                                                                                                               |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Anthropic type       | Coding agent (API-test variant)                                                                                                                                                                                                                                                                     |
| Task suite           | Two oracles, both formal: (a) [Schemathesis](https://schemathesis.readthedocs.io/) over the same OpenAPI as a property-based baseline — the agent's generated tests must match or beat it. (b) 10 **mutation seeds** — small handler bugs injected into `todo-api/api/handler.js` on a test branch. |
| Outcome              | The set of generated tests and the violations they discovered.                                                                                                                                                                                                                                      |
| Code-based grader    | **Mutation kill rate** (the headline grader — coverage without kill = tests don't assert). Schema validity % of generated requests. Operation / status-code coverage. Schemathesis-relative catch rate (caught ≥ X% of what Schemathesis caught).                                                   |
| Model-based grader   | Used only for **triage** (summarising violations into a GitHub issue body) — not for the pass/fail decision. The oracles are formal.                                                                                                                                                                |
| Human grader cadence | Per spec change: SME reviews the mutation seed set for relevance.                                                                                                                                                                                                                                   |
| Gate                 | At trials/task = 3 (a seed counts as **killed** only if killed in a strict majority of its 3 graded trials): block if mutation kill rate < 70%. With 10 seeds the rate resolves in 10 pp steps and 70% sits exactly on a step, so set the gate explicitly at **≤ 6/10 killed = block** (kill rate must be ≥ 7/10 to pass); on the current 4-seed regression cut (25 pp/seed) state the equivalent ≥ 3/4 step. Report **pass@1** kill rate (across all graded trials) alongside the majority pass@3 per-seed result. Schema validity is a per-request rate (large N), so 95% is resolvable as-is = block.                                                                                                                                                                                    |
| Saturation watch     | Measured at trials/task = 3 on per-seed majority pass@3 outcomes: when kill rate ≥ 9/10 (90%, the resolvable step on 10 seeds at scale; ≥ 4/4 on the current 4-seed cut), add harder mutants (semantic-preserving edits, mutation cascades).                                                                                                                                                                                                   |
| Online signal        | The "LLM-too-narrow-on-status-codes" tolerance fired in `agent.py:350-363` is the acknowledged eval-cheating surface — instrument *how often* it fires. Rising = prompt or spec drift.                                                                                                              |
| **MVP first cut**    | 3 mutation seeds (one obvious wrong-status, one schema break, one missing-field). One grader: mutation kill rate.                                                                                                                                                                                   |

### 2.5 Release-notes agent

| Field                | Value                                                                                                                                                                                                                               |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Anthropic type       | Research agent (summarisation variant)                                                                                                                                                                                              |
| Task suite           | 30 historical merged PRs, each with `(pr_title, pr_body, commits) → hand-edited ideal release note` as the **reference solution**.                                                                                                  |
| Outcome              | The generated markdown release note.                                                                                                                                                                                                |
| Code-based grader    | Length constraint (≤ 300 words, hard rule). Claim-grounding check: each atomic claim in the note must map to a commit / PR field via string-overlap heuristics (first pass).                                                        |
| Model-based grader   | **Faithfulness** ([RAGAS](https://docs.ragas.io/)-style: atomic claim → entailment judgement against the diff). **Hallucination rate**: % of notes with ≥ 1 ungrounded claim. Pairwise readability vs the hand-edited reference.    |
| Human grader cadence | Monthly: SME labels a 10% sample of production release notes for the model-based grader to recalibrate against.                                                                                                                     |
| Gate                 | At trials/task = 3 with strict-majority grading: block if any regression task produces a hallucinated claim in a strict majority of its 3 graded trials (**majority pass@3** fail) — one flaky generation never trips the gate. Also report **pass@1** hallucination rate = fraction of all graded trials with ≥ 1 ungrounded claim; on the at-scale 30-task suite the task-level rate resolves to 3.3 pp/task steps, on the current 5-task cut to 20 pp/task. **Not a gate**: ROUGE / BLEU — Anthropic's principle that "failures should seem fair" is violated when surface-level n-gram overlap rejects valid rewordings. |
| Saturation watch     | Measured at trials/task = 3: graduate when the **trial-level** hallucination rate is 0 (no ungrounded claim in *any* graded trial), which is stricter than 0 majority pass@3 failures — recommend requiring the trial-level 0. Then add adversarial tasks (PRs with misleading titles, fixup commits, no-op renames).                                                                                              |
| Online signal        | 10% of production release notes routed to human label queue monthly; new failures become regression tasks.                                                                                                                          |
| **MVP first cut**    | 5 historical PRs + hand-edited reference notes. One grader: hallucination rate (any claim not in `git log` → fail).                                                                                                                 |

### 2.6 RCA agent

| Field                | Value                                                                                                                                                                                                                                                                                                                                                                |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Anthropic type       | Research agent (incident triage)                                                                                                                                                                                                                                                                                                                                     |
| Task suite           | 10 **replay tasks** — past incidents (or seeded ones in `todo-api`) bundled as `{log bundle, source-tree state at incident time, labelled root cause, fix}`. Each runs in a clean environment per Anthropic's Step 4.                                                                                                                                                |
| Outcome              | The GitHub issue body the agent posts (title + diagnosis + cited evidence), plus the exit code.                                                                                                                                                                                                                                                                      |
| Code-based grader    | **Top-3 hypothesis accuracy** — was the truth in the agent's top 3? (RCA is rarely deterministic — one of Anthropic's grader-design principles.) **Evidence-citation rate** — % of hypotheses citing a specific `file:line` or log entry. **Cost-to-cause** — tokens / trials until correct. **FPR on clean logs** — must not raise issues when there are no errors. |
| Model-based grader   | Independent LLM grades whether the issue body's diagnosis matches the labelled cause. Given an explicit "Unknown" exit (Anthropic's recommendation to "give the LLM a way out").                                                                                                                                                                                     |
| Human grader cadence | When an RCA issue is closed in production, the closer labels `diagnosis_correct: y/n`. Forms the online flywheel.                                                                                                                                                                                                                                                    |
| Gate                 | At trials/task = 3 (a task counts correct if the truth is in the top-3 in a strict majority of its 3 trials): block if **top-3 majority pass@3 accuracy < 60%**. With 10 replay tasks at scale the rate resolves in 10 pp steps and 60% sits on a step, so set the gate at **≤ 5/10 = block** (pass needs ≥ 6/10); on the current 6-task regression cut (17 pp/task) state the equivalent ≤ 3/6 step. For clean logs, FPR > 5% is unreachable on a tiny clean set (one false incident on 2 clean logs is 50%, on 10 is 10%): the gate is **0 false incidents at the clean-set's resolution** — block if any clean-log task raises an issue in a strict majority of its 3 trials. State K (the clean-log count); the smallest non-zero FPR is 1/K, so gate at any majority-pass@3 false positive rather than an unreachable 5%. Report top-3 **pass@1** across all graded trials too. (False incidents destroy trust faster than missed ones — note the asymmetry per **balanced problem sets**.)                                                                                                                                                                               |
| Saturation watch     | Measured at trials/task = 3 on per-task majority pass@3 top-1 outcomes: graduate when top-1 accuracy ≥ 8/10 (80%, the resolvable step on 10 tasks at scale; ≥ 5/6 on the current 6-task cut), then add harder tasks (multi-cause incidents, latent bugs that surface days after deploy).                                                                                                                                                                                                                             |
| Online signal        | Time-from-deploy to correct-hypothesis on live incidents (when `diagnosis_correct=y`).                                                                                                                                                                                                                                                                               |
| **MVP first cut**    | 3 replay tasks (one seeded bug + 2 incidents from this repo's history) + 2 clean-log runs. One grader: top-3 accuracy + FPR = 0 on clean.                                                                                                                                                                                                                            |

## 3. SDLC-level strategy

Per-agent grader scores answer "is this agent good?" The harness-level
question is "is Talos getting better or worse?" — which the per-agent scores
cannot answer alone.

### 3.1 DORA + AI caveats

The four [DORA](https://dora.dev/) metrics, paired to specific Talos signals:

| DORA metric           | Talos signal                                                     | Source                                                                |
| --------------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------- |
| Deployment frequency  | Main pushes per week                                             | `gh api repos/.../commits` on main                                    |
| Lead time for changes | First `@talos` comment on issue → production promotion timestamp | `talos.code.run` span start + Vercel promote webhook                  |
| Change failure rate   | % of weekly deploys that triggered an RCA or contract-test issue | GitHub issues labelled `talos-rca` or `talos-contract-test` ÷ deploys |
| MTTR                  | Median wall-clock from RCA / contract-test issue opened → closed | GitHub issue `created_at` and `closed_at`                             |

**Critical pairing**: never report throughput (DF, lead time) without quality
(CFR, escape rate) on the same chart. The 2025 DORA report explicitly warns
that AI-generated code lifts deployment frequency while CFR quietly grows.

### 3.2 Harness-specific cross-cutting metrics

| Metric               | Definition                                                                             | Why                                                 |
| -------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------- |
| **Gate escape rate** | Merged PRs that later triggered RCA or contract-test, % passed by code/security review | Each escape = a new regression-suite task           |
| **Override rate**    | % of agent verdicts a human overrode                                                   | Leading indicator of trust collapse                 |
| **Cost per PR**      | Total OpenRouter $ across all six agents end-to-end                                    | ROI denominator                                     |
| **Stage cycle time** | Wall-clock per agent                                                                   | Bottleneck finder                                   |
| **Trust-cost ratio** | (1 − override_rate) / cost_per_PR                                                      | Single demoable harness-quality number              |
| **Harness drift**    | Per-agent regression score — defined as **majority pass@3** (task-level, trials/task = 3) — moving > 2σ from the 30-day rolling baseline, with the band **floored at the suite's one-task resolution** (5 pp on a 20-task suite, 10 pp on a 10-task suite, etc.) so a single-task flip isn't mistaken for drift; track pass@1 variance separately | Catches silent model swaps, prompt edits, dep bumps |

### 3.3 Trace substrate (Arize AX / Phoenix)

Already there — every agent emits OpenInference spans to **Arize AX**
(`arize-otel`'s `register()` + `OpenAIInstrumentor`; see
`agents/*/agent.py:_setup_arize_tracing`). Each run's root span is
`talos.<agent>.run` (kind `AGENT`) carrying `input.value` / `output.value` as
JSON plus `session.id`, `metadata`, and the propagated `pr_number`. The sketch
below is written against Phoenix's evaluator API; the same wiring runs on Arize
AX's online-evals surface. **Either way it must be pinned to a tested SDK
version or labelled pseudocode** (TODO.md #6) — treat the snippet as the shape,
not a tested call.

- **Trace tree per PR**: propagate `pr_number` as a span attribute so the full
  agent chain (code → code-review → security-review → contract-test → rca)
  appears as one trace.
- **Online evaluators**: register a Python function (or LLM-as-judge call)
  per agent that scores the span post-hoc. Score becomes a queryable metric
  in Phoenix.
- **Dataset experiments**: regression and capability suites live as
  versioned Phoenix datasets. CI re-runs them on each prompt change and
  posts a diff comment to the PR.

Sketch of an online evaluator for `code-review` — scores the agent's
comment against the eventually-merged diff, post-hoc:

```python
from phoenix.evals import create_evaluator
from phoenix.client import Client

@create_evaluator(name="code_review.verdict_accuracy", kind="LLM")
def grade_review(output: dict, expected: dict) -> dict:
    # output: the agent's PR comment + verdict, pulled from the span
    # expected: the merged diff + any human-labelled defect category
    judgement = judge_llm.chat(
        system="Did the reviewer flag the real defect, if any? Return JSON "
               "{verdict_correct: bool, category_match: bool, reason: str}. "
               "Return 'Unknown' if the diff is ambiguous.",
        user=f"Review: {output['comment']}\nDiff: {expected['merged_diff']}"
    )
    return {"score": float(judgement["verdict_correct"]),
            "label": judgement.get("reason", "")}

Client().evaluators.register(
    project="talos-code-review",
    evaluator=grade_review,
    sample_rate=1.0,  # score every span; drop to 0.1 if cost matters
)
```

Dataset experiments use the same evaluator against a versioned suite, so the
per-PR diff comment compares the **same grader** on main vs PR — no apples vs
oranges.

### 3.4 Tiered cadence

| Cadence                                              | What runs                                                                   | Budget       |
| ---------------------------------------------------- | --------------------------------------------------------------------------- | ------------ |
| Per PR (only if `agents/**` touched) | Regression suite for affected agent at trials/task = 3 (strict-majority grading, the workflow's `--trials 3` default); gate on majority pass@3 (task-level) and additionally report pass@1 (trial-level) in the PR comment; schema/lint of agent outputs | < $0.10 / PR |
| Nightly                                              | Capability suites, mutation sweep, SWE-bench Verified Lite, OWASP Benchmark | < $5 / night |
| Weekly                                               | Drift dashboard review, judge-agreement spot check                          | manual       |
| Monthly                                              | Human label of 10% production sample → suite refresh                        | ~2 hrs human |
| Quarterly                                            | Rotate judge model family; re-baseline against human grader                 | ~½ day SME   |

### 3.5 Harvesting Arize AX traces into eval datasets

The production→dataset flywheel, made concrete. Every agent run already lands
in Arize AX as an OpenInference trace (§3.3), so the trace store is a standing
pool of **real, already-executed agent flows** — exactly the "production
sample" the suite-refresh cadence (§3.4 monthly; anti-pattern *stale suites*)
calls for, but which this repo's short history can't otherwise supply. Up to
now every task was either *seeded* (a planted flaw on a fixture branch) or
*organically harvested by re-running the pipeline*. Arize traces add a third,
cheaper source: tasks that cost nothing to generate because the agent already
ran them in anger. It also closes the online→offline loop the strategy keeps
promising — the **Online signal** rows in §2 (override rate, suppression-list
utilisation, FPR-on-clean) stop being dashboards and become *labelled tasks*.

The harvest, step by step:

1. **Export the root spans** for a window with the Arize exporter (SDK ≥ 7.0.3):

   ```python
   from arize.exporter import ArizeExportClient
   from arize.utils.types import Environments

   df = ArizeExportClient().export_model_to_df(
       space_id=SPACE_ID,
       model_id="talos-code-review",            # = the agent's ARIZE_PROJECT_NAME
       environment=Environments.TRACING,
       start_time=..., end_time=...,
       columns=["context.span_id", "name", "attributes.openinference.span.kind",
                "attributes.input.value", "attributes.output.value",
                "attributes.metadata", "attributes.session.id"],
   )
   # keep one root span per trace: name == "talos.<agent>.run" and kind == "AGENT"
   ```

2. **Map to the task schema.** Each root span becomes one
   `evals/datasets/<agent>/<task-id>/`: `attributes.input.value` → the hermetic
   input the runner already understands (`diff.patch` / `input.json` /
   `logs.jsonl`), `attributes.output.value` → the `reference_trial` block (the
   verdict / comment / issue the agent actually produced). For code-review, also
   freeze the `source/` snapshot at the recorded SHA — the existing replay
   requirement (a `cr-*` task must review the tree it saw, not current `main`).

3. **Exclude non-runs.** Drop spans whose output matches an `InfraFailure`
   signature (`evals/runner.py` `INFRA_PATTERNS`) — they never meaningfully
   executed, so they must not become graded tasks. Same infra-vs-agent split the
   runner already enforces, applied at harvest time.

4. **Scrub before commit.** The suite is committed to git, so strip secrets /
   PII from the trace payload first (tokens, emails, internal URLs). Reuse the
   V3 lesson (harness-failure log #8): a real `sk_live_…` token in a trace would
   trip push protection — redact, don't commit-then-revert.

5. **Label (human-in-the-loop).** The maintainer assigns the one thing the trace
   can't carry — ground truth. Capture it as an **Arize annotation** on the span
   (`category`, `expected_verdict`, `diagnosis_correct`) and export the
   annotation alongside the span so the label travels with the task. This *is*
   the "maintainer re-grades a sample whenever a suite or judge model changes"
   mechanism (TODO.md #3) — performed on real traffic, not a fictional SME panel.

6. **Admit to capability, graduate to regression.** Harvested tasks enter the
   **capability** suite by default (fresh, possibly-hard, not yet reliably
   solved) and graduate under the existing rule once the agent passes them
   across trials. Harvest the high-signal traces first: **human overrides and
   suspected false positives** are precisely the failures the suite exists to
   catch (cr-005, cr-016, sec-012 all entered this way, by hand — this step
   automates that path).

**Contamination guard.** A task harvested from a production trace must be held
out from prompt-tuning the agent that produced it, or the gate measures
memorisation, not capability (the same discipline §5 applies to SWE-bench). Tag
each Arize-harvested task with its source window so a prompt change is only ever
evaluated against tasks that predate it.

**Platform-native option (keep it in Arize).** The offline path above (export →
`evals/datasets/` → pytest gate) is **primary**: durable, diffable, and runs in
CI with no live-SaaS dependency, so the per-PR gate never blocks on an Arize
call. Arize *also* runs the suite in-platform — curate the same spans into a
**Dataset** (`ArizeDatasetsClient.create_dataset(..., dataset_type=GENERATIVE,
data=df)`) and replay prompt changes with `run_experiment(space_id, dataset_id,
task, evaluators=[...])`. That is the Arize-native equivalent of §3.3's
dataset-experiment idea and the natural home for the **model-based
(LLM-as-judge)** grader and the nightly capability curve. Split of duties: gate
on the committed pytest suite; trend and judge in Arize.

## 4. Implementation phases

**Phase 0 is built** (2026-06-11). `evals/` holds a plain-pytest runner +
code-based graders + a per-PR CI workflow (`.github/workflows/talos-evals.yml`,
triggered on `agents/**`), and all six MVP cuts are populated in
`evals/datasets/` and replay green. We dropped DeepEval for plain pytest
(TODO.md #7 — nothing in the gate is materially cheaper with it) and deferred
Phoenix: the agents trace to Arize AX today, not self-hosted Phoenix, and the
per-PR diff comment needs neither. The runner enforces the infra-vs-agent
split (`InfraFailure` → skip, never fail), supports `--trials N` for the
gate-statistics fix (TODO.md #5), and runs in docker mode so it catches
packaging gaps (the missing-`COPY` class of bug, harness-failure log #5).

| Phase                    | Weeks | Deliverable                                                                                                                                                                 |
| ------------------------ | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 — Scaffolding ✅       | 1     | **Done.** `evals/` runner + graders + CI workflow on `agents/**`; six MVP cuts populated and green. Tooling: **plain pytest** for CI gates (DeepEval dropped); Phoenix deferred until agents trace to it |
| 1 — Review agents        | 2     | 100 labelled PRs (code-review reference solutions), 30 Juliet flows (security-review), per-PR per-category F1 diff comment on PRs                                           |
| 2 — Formal-oracle agents | 2     | 30 release-note reference solutions + RAGAS faithfulness scorer; Schemathesis baseline + 10 mutation seeds for contract-test                                                |
| 3 — Generative agents    | 2     | Talos-bench (20 instances), 10 RCA replay tasks with bundled log + source state, SWE-bench Verified Lite wired into nightly                                                 |
| 4 — SDLC dashboard       | 1     | DORA-with-AI dashboard (Phoenix or Vercel page), drift alerts, per-PR eval report — the talk's punchline view                                                               |

## 5. Anti-patterns explicitly avoided

Direct mapping from Anthropic's anti-patterns to Talos design decisions:

| Anthropic anti-pattern                | Talos counter                                                                                                                                         |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Task ambiguity                        | Every regression task includes a reference solution; tasks reviewed by two SMEs before entering the suite                                             |
| Over-specification (grading the path) | Graders score the artefact (comment, issue, patch, note) — never the tool-call sequence inside the trial                                              |
| One-sided evals                       | Each suite is balanced: review/security have clean PRs in the suite, RCA has clean logs, release-notes has fixup-only PRs                             |
| Insufficient environment isolation    | Each agent trial starts from a `git checkout` of the SHA + a fresh Docker container — no shared state between trials                                  |
| Grading bugs                          | String matches use fuzzy/numeric tolerance; LLM graders given an "Unknown" exit; humans recalibrate quarterly                                         |
| Goal mismatch                         | Graders are reviewed against the agent's system prompt every time the prompt changes                                                                  |
| Eval cheating                         | Code-based graders verify outcomes that the agent can't see in the prompt (hidden tests, mutation seeds on a private branch, post-merge verification) |
| Single-number summaries               | Per-category F1 for review agents; per-CWE for security; never aggregate over buckets                                                                 |
| Self-preference bias                  | Generator and judge always come from different model families                                                                                         |
| Stale suites                          | 10% monthly rotation from production sample; quarterly human re-grading                                                                               |
| Trajectory blindness                  | Cost-to-success / cost-to-cause are first-class gated metrics, not just success rate                                                                  |
| Benchmark contamination               | Talos-bench draws from this repo's private history; SWE-bench Verified Lite is held out from prompt-tuning                                            |

---

**Vocabulary**: [`docs/GLOSSARY.md`](./GLOSSARY.md)
**Source framework**: Anthropic — [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
