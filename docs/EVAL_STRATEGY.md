# Talos Evaluation Strategy

This document defines the evaluation strategy for the six agents in the
Talos SDLC and for the harness as a whole. Vocabulary follows
[`docs/GLOSSARY.md`](./GLOSSARY.md), which in turn follows Anthropic's
[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).
If a term here is unfamiliar, the glossary is the source of truth.

## 0. Executive summary

For each of the six Talos agents (`code`, `code-review`, `security-review`,
`contract-test`, `release-notes`, `rca`) we build two **eval suites**: a
**regression suite** (~20 tasks, runs on every PR that touches an agent,
near-100% pass rate is the gate) and a **capability suite** (~50 tasks, runs
nightly, the hill we're climbing). Each task has **reference solutions** and
is graded by a **code-based grader** (gate) plus a **model-based grader**
(signal); human SMEs recalibrate the model-based grader quarterly.

We grade **outcomes** (the PR comment, the patch, the issue body, the
release note) — never the path the agent took to produce them. The two
grader families come from different model providers to avoid self-preference
bias. Tasks graduate from capability → regression as they're solved
reliably; the capability suite always has fresh hard tasks.

Above the per-agent layer, the harness is graded by **DORA + AI caveats**
(deployment frequency vs change failure rate plotted together), plus
Talos-specific cross-cutting metrics: **gate escape rate**, **override
rate**, **cost per PR**, **trust-cost ratio**, and **harness drift**.

The whole thing rides on Phoenix: every agent's existing OTel span tree *is*
the **transcript**. Online evaluators score those spans post-hoc; dataset
experiments re-run suites on prompt changes and post a diff to the PR.

**Minimum viable cut to demo this**: 5 tasks per agent + 1 code-based grader
each + a per-PR comment showing pass/fail vs main. Everything else is
incremental on that.

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
5. **Capability suites graduate to regression suites.** Once an agent passes
   a capability task reliably, move it to the regression suite and add a
   harder capability task. This is Anthropic's Step 7.
6. **Phoenix is the substrate.** Every agent already emits OTel spans
   (the **transcript** in glossary terms). Online evaluators score those
   spans post-hoc; dataset experiments re-run task suites on prompt changes.

## 2. Per-agent strategy

Each agent gets the same six-field treatment:

- **Task suite** — capability and regression, what the tasks look like
- **Outcome** — what gets graded (the artefact, not the path)
- **Grader mix** — code-based + model-based + human cadence
- **Gate** — what blocks a prompt change or a PR
- **Saturation watch** — when to graduate tasks
- **Online signal** — the production-monitoring layer

### 2.1 Code agent (Pi code-gen)

| Field | Value |
|---|---|
| Anthropic type | Coding agent |
| Task suite | **Talos-bench**: 20 resolved issues from this repo, each with merged diff + the test suite at that SHA, runnable from a stable environment snapshot. Starts as a **capability suite**; tasks the agent solves reliably graduate to the regression suite. |
| Outcome | The patch (diff) produced for the issue, plus pass/fail of the hidden test suite. |
| Code-based grader | `tests_pass@1` on hidden tests (binary, primary), `cost_to_success` (Pi turns + tokens, threshold), file-overlap Jaccard vs merged diff (sanity, not gate) |
| Model-based grader | Pairwise comparison against the merged diff on (correctness, minimality, maintainability). Two graders from different families; only fail on agreement. |
| Human grader cadence | Quarterly: SME re-grades 10 random trials to recalibrate the model-based grader. |
| Gate | Nightly only — per-PR uses real downstream tests. Block prompt promotion if `tests_pass@1` drops > 5 pp from baseline or `cost_to_success` rises > 50%. |
| Saturation watch | When Talos-bench hits 80% pass@1, graduate solved instances to regression and seed harder tasks (multi-file, cross-cutting refactors). |
| Online signal | Existing `talos.code.run` span gets `eval.tests_pass` and `eval.judge_score` attached asynchronously by a Phoenix online evaluator after the PR merges. |
| Nightly capability eval | SWE-bench Verified Lite (50 instances) — wide-net regression detector. |
| **MVP first cut** | 5 trivial fix-a-bug tasks from this repo's closed issues. One grader: `tests_pass@1`. Run nightly; surface pass rate in a single Phoenix dashboard tile. |

### 2.2 Code-review agent

| Field | Value |
|---|---|
| Anthropic type | Coding agent (review variant) |
| Task suite | 100 historical PRs from this repo, each with a **reference solution**: the labelled `{real_defect, missing_test, maintainability, style_only, none}` category and the expected verdict. **Balanced problem set** — must include PRs where the agent *should not* find issues (style-only, trivial), or one-sided optimisation will follow. |
| Outcome | The PR comment posted (or not), plus the exit code (pass/fail). |
| Code-based grader | Verdict match (assertion on outcome). Per-category precision/recall/F1 — never averaged, always reported per bucket (one of the explicit anti-patterns: single-number summaries hide regressions in critical categories). FPR on `style_only` PRs (trust-collapse indicator). |
| Model-based grader | A second LLM (different family) labels the agent's comment with one of the same categories; agreement required before flagging "fail". |
| Human grader cadence | Monthly: SME re-labels a 10% sample from production to refresh task suite (Anthropic Step 8 — keep the suite alive). |
| Gate | Per-PR: replay regression suite, fail if per-category F1 drops > 5 pp vs main. Nightly: replay [Martian code-review benchmark](https://github.com/withmartian/code-review-benchmark) for cross-tool comparability. |
| Saturation watch | When F1 ≥ 0.9 on regression suite, add harder tasks (multi-file PRs, subtle correctness bugs, race conditions). |
| Online signal | **Override rate** — % of merger-overrode agent verdicts. Rises before F1 does. |
| **MVP first cut** | 10 labelled PRs (5 with real defects, 5 style-only). One grader: verdict match. Per-PR comment shows the diff vs main on these 10. |

### 2.3 Security-review agent

| Field | Value |
|---|---|
| Anthropic type | Coding agent (security variant) |
| Task suite | 30 [Juliet](https://samate.nist.gov/SARD/test-suites/) flows seeded into a small Node fixture, each labelled by CWE in scope (injection, auth, crypto, secret leak). 20 known-clean PRs from this repo (must produce zero findings — the **balanced** half). |
| Outcome | The PR comment with findings (severity, title, detail), plus exit code. |
| Code-based grader | **Per-CWE** precision/recall (never averaged), severity-weighted confusion matrix (medium/high/critical miscalls cost more), FPR on the clean half, suppression-list utilisation. |
| Model-based grader | Independent security-tuned LLM grades severity calibration (was a "high" really high?). SARIF diff vs Snyk Code / Semgrep on identical PRs as an external cross-check. |
| Human grader cadence | Quarterly: security SME re-grades severity on a 10-task sample. |
| Gate | Any miss on a `high`/`critical` golden case = block prompt change. Per-CWE recall < 70% = block. |
| Saturation watch | When per-CWE F1 ≥ 0.85 across all in-scope CWEs, add CWE categories (e.g. SSRF, deserialisation). |
| Online signal | Suppression-list utilisation — each new entry is a labelled example for the suite. |
| **MVP first cut** | 5 Juliet flows (one per CWE in scope) + 5 clean PRs. One grader: per-CWE recall ≥ 1 and clean-PR FPR = 0. |

### 2.4 Contract-test agent

| Field | Value |
|---|---|
| Anthropic type | Coding agent (API-test variant) |
| Task suite | Two oracles, both formal: (a) [Schemathesis](https://schemathesis.readthedocs.io/) over the same OpenAPI as a property-based baseline — the agent's generated tests must match or beat it. (b) 10 **mutation seeds** — small handler bugs injected into `todo-api/api/handler.js` on a test branch. |
| Outcome | The set of generated tests and the violations they discovered. |
| Code-based grader | **Mutation kill rate** (the headline grader — coverage without kill = tests don't assert). Schema validity % of generated requests. Operation / status-code coverage. Schemathesis-relative catch rate (caught ≥ X% of what Schemathesis caught). |
| Model-based grader | Used only for **triage** (summarising violations into a GitHub issue body) — not for the pass/fail decision. The oracles are formal. |
| Human grader cadence | Per spec change: SME reviews the mutation seed set for relevance. |
| Gate | Mutation kill rate < 70% on seeds = block prompt promotion. Schema validity < 95% of generated requests = block. |
| Saturation watch | When mutation kill rate ≥ 90%, add harder mutants (semantic-preserving edits, mutation cascades). |
| Online signal | The "LLM-too-narrow-on-status-codes" tolerance fired in `agent.py:350-363` is the acknowledged eval-cheating surface — instrument *how often* it fires. Rising = prompt or spec drift. |
| **MVP first cut** | 3 mutation seeds (one obvious wrong-status, one schema break, one missing-field). One grader: mutation kill rate. |

### 2.5 Release-notes agent

| Field | Value |
|---|---|
| Anthropic type | Research agent (summarisation variant) |
| Task suite | 30 historical merged PRs, each with `(pr_title, pr_body, commits) → hand-edited ideal release note` as the **reference solution**. |
| Outcome | The generated markdown release note. |
| Code-based grader | Length constraint (≤ 300 words, hard rule). Claim-grounding check: each atomic claim in the note must map to a commit / PR field via string-overlap heuristics (first pass). |
| Model-based grader | **Faithfulness** ([RAGAS](https://docs.ragas.io/)-style: atomic claim → entailment judgement against the diff). **Hallucination rate**: % of notes with ≥ 1 ungrounded claim. Pairwise readability vs the hand-edited reference. |
| Human grader cadence | Monthly: SME labels a 10% sample of production release notes for the model-based grader to recalibrate against. |
| Gate | Any hallucinated claim on the regression suite = block prompt change. **Not a gate**: ROUGE / BLEU — Anthropic's principle that "failures should seem fair" is violated when surface-level n-gram overlap rejects valid rewordings. |
| Saturation watch | When hallucination rate = 0 across regression suite, add adversarial tasks (PRs with misleading titles, fixup commits, no-op renames). |
| Online signal | 10% of production release notes routed to human label queue monthly; new failures become regression tasks. |
| **MVP first cut** | 5 historical PRs + hand-edited reference notes. One grader: hallucination rate (any claim not in `git log` → fail). |

### 2.6 RCA agent

| Field | Value |
|---|---|
| Anthropic type | Research agent (incident triage) |
| Task suite | 10 **replay tasks** — past incidents (or seeded ones in `todo-api`) bundled as `{log bundle, source-tree state at incident time, labelled root cause, fix}`. Each runs in a clean environment per Anthropic's Step 4. |
| Outcome | The GitHub issue body the agent posts (title + diagnosis + cited evidence), plus the exit code. |
| Code-based grader | **Top-3 hypothesis accuracy** — was the truth in the agent's top 3? (RCA is rarely deterministic — one of Anthropic's grader-design principles.) **Evidence-citation rate** — % of hypotheses citing a specific `file:line` or log entry. **Cost-to-cause** — tokens / trials until correct. **FPR on clean logs** — must not raise issues when there are no errors. |
| Model-based grader | Independent LLM grades whether the issue body's diagnosis matches the labelled cause. Given an explicit "Unknown" exit (Anthropic's recommendation to "give the LLM a way out"). |
| Human grader cadence | When an RCA issue is closed in production, the closer labels `diagnosis_correct: y/n`. Forms the online flywheel. |
| Gate | Top-3 accuracy < 60% = block prompt change. FPR on clean logs > 5% = block (false incidents destroy trust faster than missed ones — note the asymmetry per **balanced problem sets**). |
| Saturation watch | When top-1 accuracy ≥ 80% across regression suite, add harder tasks (multi-cause incidents, latent bugs that surface days after deploy). |
| Online signal | Time-from-deploy to correct-hypothesis on live incidents (when `diagnosis_correct=y`). |
| **MVP first cut** | 3 replay tasks (one seeded bug + 2 incidents from this repo's history) + 2 clean-log runs. One grader: top-3 accuracy + FPR = 0 on clean. |

## 3. SDLC-level strategy

Per-agent grader scores answer "is this agent good?" The harness-level
question is "is Talos getting better or worse?" — which the per-agent scores
cannot answer alone.

### 3.1 DORA + AI caveats

The four [DORA](https://dora.dev/) metrics, paired to specific Talos signals:

| DORA metric | Talos signal | Source |
|---|---|---|
| Deployment frequency | Main pushes per week | `gh api repos/.../commits` on main |
| Lead time for changes | First `@talos` comment on issue → production promotion timestamp | `talos.code.run` span start + Vercel promote webhook |
| Change failure rate | % of weekly deploys that triggered an RCA or contract-test issue | GitHub issues labelled `talos-rca` or `talos-contract-test` ÷ deploys |
| MTTR | Median wall-clock from RCA / contract-test issue opened → closed | GitHub issue `created_at` and `closed_at` |

**Critical pairing**: never report throughput (DF, lead time) without quality
(CFR, escape rate) on the same chart. The 2025 DORA report explicitly warns
that AI-generated code lifts deployment frequency while CFR quietly grows.

### 3.2 Harness-specific cross-cutting metrics

| Metric | Definition | Why |
|---|---|---|
| **Gate escape rate** | Merged PRs that later triggered RCA or contract-test, % passed by code/security review | Each escape = a new regression-suite task |
| **Override rate** | % of agent verdicts a human overrode | Leading indicator of trust collapse |
| **Cost per PR** | Total OpenRouter $ across all six agents end-to-end | ROI denominator |
| **Stage cycle time** | Wall-clock per agent | Bottleneck finder |
| **Trust-cost ratio** | (1 − override_rate) / cost_per_PR | Single demoable harness-quality number |
| **Harness drift** | Per-agent regression score moving > 2σ from 30-day rolling baseline | Catches silent model swaps, prompt edits, dep bumps |

### 3.3 Phoenix wiring

Already partly there — every agent emits OTel spans.

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

| Cadence | What runs | Budget |
|---|---|---|
| Per PR (only if `agents/**` or `prompts/**` touched) | Regression suite for affected agent, schema/lint of agent outputs | < $0.10 / PR |
| Nightly | Capability suites, mutation sweep, SWE-bench Verified Lite, OWASP Benchmark | < $5 / night |
| Weekly | Drift dashboard review, judge-agreement spot check | manual |
| Monthly | Human label of 10% production sample → suite refresh | ~2 hrs human |
| Quarterly | Rotate judge model family; re-baseline against human grader | ~½ day SME |

## 4. Implementation phases

| Phase | Weeks | Deliverable |
|---|---|---|
| 0 — Scaffolding | 1 | `evals/` directory, eval CI workflow on `agents/**` changes, tooling: **DeepEval** (pytest-native) for CI gates + **Phoenix** for dataset experiments and online evaluators |
| 1 — Review agents | 2 | 100 labelled PRs (code-review reference solutions), 30 Juliet flows (security-review), per-PR per-category F1 diff comment on PRs |
| 2 — Formal-oracle agents | 2 | 30 release-note reference solutions + RAGAS faithfulness scorer; Schemathesis baseline + 10 mutation seeds for contract-test |
| 3 — Generative agents | 2 | Talos-bench (20 instances), 10 RCA replay tasks with bundled log + source state, SWE-bench Verified Lite wired into nightly |
| 4 — SDLC dashboard | 1 | DORA-with-AI dashboard (Phoenix or Vercel page), drift alerts, per-PR eval report — the talk's punchline view |

## 5. Anti-patterns explicitly avoided

Direct mapping from Anthropic's anti-patterns to Talos design decisions:

| Anthropic anti-pattern | Talos counter |
|---|---|
| Task ambiguity | Every regression task includes a reference solution; tasks reviewed by two SMEs before entering the suite |
| Over-specification (grading the path) | Graders score the artefact (comment, issue, patch, note) — never the tool-call sequence inside the trial |
| One-sided evals | Each suite is balanced: review/security have clean PRs in the suite, RCA has clean logs, release-notes has fixup-only PRs |
| Insufficient environment isolation | Each agent trial starts from a `git checkout` of the SHA + a fresh Docker container — no shared state between trials |
| Grading bugs | String matches use fuzzy/numeric tolerance; LLM graders given an "Unknown" exit; humans recalibrate quarterly |
| Goal mismatch | Graders are reviewed against the agent's system prompt every time the prompt changes |
| Eval cheating | Code-based graders verify outcomes that the agent can't see in the prompt (hidden tests, mutation seeds on a private branch, post-merge verification) |
| Single-number summaries | Per-category F1 for review agents; per-CWE for security; never aggregate over buckets |
| Self-preference bias | Generator and judge always come from different model families |
| Stale suites | 10% monthly rotation from production sample; quarterly human re-grading |
| Trajectory blindness | Cost-to-success / cost-to-cause are first-class gated metrics, not just success rate |
| Benchmark contamination | Talos-bench draws from this repo's private history; SWE-bench Verified Lite is held out from prompt-tuning |

---

**Vocabulary**: [`docs/GLOSSARY.md`](./GLOSSARY.md)
**Source framework**: Anthropic — [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
