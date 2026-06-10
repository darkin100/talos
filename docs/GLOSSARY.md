# Talos Evaluation Glossary

This glossary fixes the vocabulary used across Talos eval design and code. The
top half is Anthropic's framework from
[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
(definitions are paraphrased and, where wording matters, quoted). The bottom
half lists Talos-specific extensions — terms we need that the Anthropic piece
doesn't define.

When the two diverge, prefer Anthropic's term.

---

## 1. Core concepts

| Term | Definition |
|---|---|
| **Eval** (evaluation) | A test for an AI system: give an AI an input, then apply grading logic to its output to measure success. |
| **Automated eval** | An eval that can be run during development without real users. The default surface for Talos CI. |
| **Task** (problem, test case) | A single test with defined inputs and success criteria. |
| **Trial** | One attempt at a task. Because model outputs vary between runs, the same task is usually run with multiple trials. |
| **Transcript** (trace, trajectory) | The complete record of a trial — outputs, tool calls, reasoning, intermediate results. For an Anthropic API call this is the final `messages` array. In Talos this maps to the Phoenix span tree for one agent run. |
| **Outcome** | The final state in the environment at the end of a trial. Distinct from the transcript: an agent's transcript might say "booked", but the outcome is whether a row exists in the DB. For Talos: was the PR comment posted, did the GitHub issue get created, did the deployment promote. |
| **Grader** | Logic that scores some aspect of agent performance. A task can have multiple graders, each containing multiple **assertions** (also called **checks**). |
| **Eval harness** | The infrastructure that runs evals end-to-end: provides instructions and tools, runs tasks concurrently, records the steps, grades the outputs, aggregates results. |
| **Agent harness** (scaffold) | The system that makes a model act as an agent: processes inputs, orchestrates tool calls, returns results. When we evaluate "an agent" we are evaluating the harness *and* the model together. In Talos, the Python scripts in `agents/*/agent.py` plus Pi are the agent harness. |
| **Eval suite** | A collection of tasks designed to measure specific capabilities or behaviours. Tasks in a suite share a broad goal. |
| **Reference solution** | A known working output that passes all graders for a given task. Used to sanity-check tasks and calibrate graders. |

## 2. Grader types

Three types, each with strengths and weaknesses. A good eval mixes them.

**Decision shortcut** — pick the cheapest grader that can answer the question:

| If the question is… | Use | Talos example |
|---|---|---|
| "Did a specific verifiable thing happen?" | **Code-based** | `tests_pass@1`, schema validation, mutation kill, top-3 set membership |
| "Is this output substantively right when phrased differently?" | **Model-based** | Faithfulness on release notes, severity calibration on security findings |
| "Is the rubric itself any good?" | **Human** | Quarterly SME re-grade to recalibrate the model-based grader |

If you're tempted to use a model-based grader for something a code-based
grader could answer, stop — you're paying more for less reproducibility.

### 2.1 Code-based graders

Deterministic logic. Methods include string match (exact, regex, fuzzy), binary
tests (fail-to-pass, pass-to-pass), static analysis, outcome verification,
tool-call verification, transcript analysis (turns, tokens).

- **Strengths**: fast, cheap, objective, reproducible, easy to debug.
- **Weaknesses**: brittle to valid variations, lacking nuance, limited on
  subjective tasks.

### 2.2 Model-based graders

An LLM scores the output. Methods include rubric scoring, natural-language
assertions, pairwise comparison, reference-based evaluation, multi-judge
consensus.

- **Strengths**: flexible, scalable, captures nuance, handles open-ended /
  freeform output.
- **Weaknesses**: non-deterministic, more expensive than code, requires
  calibration against human graders.

Anthropic's guidance: "LLM-as-judge graders should be closely calibrated with
human experts" and "give the LLM a way out, like providing an instruction to
return 'Unknown' when it doesn't have enough information."

### 2.3 Human graders

Methods: SME (Subject Matter Expert) review, crowdsourced judgement,
spot-check sampling, A/B testing, inter-annotator agreement.

- **Strengths**: gold standard quality, matches expert user judgement, used to
  calibrate model-based graders.
- **Weaknesses**: expensive, slow, requires expert access at scale.

## 3. Eval categories

### 3.1 By turn count

| Category | Definition |
|---|---|
| **Single-turn eval** | A prompt, a response, grading logic. The non-agentic baseline. |
| **Multi-turn eval** | Multiple exchanges; increasingly common as capabilities grow. |
| **Agent eval** | Tools used across many turns, state modified in the environment, mistakes propagate and compound. Most Talos agents are here. |

### 3.2 By intent — capability vs regression

| Category | Question it answers | Pass rate target |
|---|---|---|
| **Capability eval** (quality eval) | "What can this agent do well?" | Starts low — the hill to climb |
| **Regression eval** | "Does the agent still handle everything it used to?" | Near 100% — a drop signals breakage |

Anthropic's progression: "after an agent is launched and optimized, capability
evals with high pass rates can 'graduate' to become a regression suite that is
run continuously to catch any drift."

### 3.3 By agent type

| Type | What it does | How it's evaluated |
|---|---|---|
| **Coding agent** | Writes, tests, debugs code | Deterministic graders, test suites pass, transcript grading for quality |
| **Conversational agent** | Multi-turn user interaction with tool use | End-state outcomes + rubrics for task completion *and* interaction quality; usually needs a second LLM to simulate the user |
| **Research agent** | Gather, synthesise, analyse, output a report | Quality judged relative to the task — context-dependent |
| **Computer-use agent** | Operates software via screenshots/clicks/keyboard | Run in a real or sandboxed environment; check the intended outcome |

## 4. Metrics and saturation

| Term | Definition |
|---|---|
| **pass@k** | Probability the agent gets at least one correct solution in *k* attempts. Rises with *k*. Example: 50% pass@1 = succeeds at half the tasks on the first try. |
| **pass^k** | Probability *all k* trials succeed. Falls with *k*. Example: 75% per-trial × 3 trials → (0.75)³ ≈ 42%. Matters for user-facing agents where reliability is the requirement. |
| **Eval saturation** | When the agent passes all solvable tasks, leaving no room for improvement. Once approached, real capability gains show up as small score increases — results become deceptive. |
| **Eval cheating** | When the agent finds a way to score well without doing the intended work. Graders should be resistant to bypasses. |

## 5. The 8-step methodology

Anthropic's roadmap for building automated evals from scratch.

| Step | Heading | Key point |
|---|---|---|
| 0 | Start early | 20–50 tasks drawn from real failures beats a 6-month wait for hundreds |
| 1 | Start with manual tests | Convert the checks you already run by hand + bug reports + support queue |
| 2 | Write unambiguous tasks with reference solutions | Two domain experts must reach the same pass/fail verdict. A 0% pass@100 with a frontier model usually means broken task, not incapable agent |
| 3 | Build balanced problem sets | Test where a behaviour should happen *and* shouldn't. One-sided evals create one-sided optimisation |
| 4 | Build a robust eval harness with a stable environment | Each trial starts from a clean state — no shared files, no cached data |
| 5 | Design graders thoughtfully | Grade what the agent *produced*, not the path it took. Build in partial credit for multi-component tasks. Calibrate LLM graders against humans |
| 6 | Check the transcripts | "We do not take eval scores at face value until someone digs into the details of the eval and reads some transcripts" |
| 7 | Monitor for capability-eval saturation | Once near 100%, graduate to a regression suite and start a new capability suite |
| 8 | Keep eval suites healthy long-term | Dedicated eval team owns infra; domain experts/product teams own the tasks. Eval-driven development: define a capability via evals before the agent can fulfil it |

## 6. Principles and anti-patterns

### Principles

- **Clarity over perfection.** Define success early.
- **Realistic task sourcing.** Tasks come from real user failures, not imagination.
- **Grade outcome, not path.** Over-specifying tool-call sequences punishes
  agents for finding valid alternative approaches.
- **Failures should seem fair.** It should be clear what the agent got wrong
  and why. If it isn't, the grader or the task is the problem.

### Anti-patterns

| Anti-pattern | Symptom | Fix |
|---|---|---|
| **Task ambiguity** | Two experts disagree on pass/fail | Tighten the spec; refuse to ship the task until they agree |
| **Over-specification** | Grader checks exact tool-call sequence | Grade the outcome instead |
| **One-sided evals** | Only positive examples | Add the cases where the behaviour shouldn't happen |
| **Insufficient environment isolation** | Flaky correlated failures | Clean environment per trial |
| **Grading bugs** | Strict string match rejects valid outputs (e.g. "96.12" vs "96.124991…") | Fuzzy match or numeric tolerance |
| **Goal mismatch** | Agent follows instructions and scores worse than one that ignores them | Align grader with task spec |
| **Eval cheating** | Agent gets high score without doing the work | Make graders resistant to bypass |

## 7. Complementary methods (the Swiss-cheese model)

Automated evals are one layer. Anthropic frames the others as complementary:

| Method | Primary use |
|---|---|
| **Production monitoring** | Ground truth post-launch |
| **A/B testing** | Validating significant changes |
| **User feedback** | Surfacing unanticipated problems (thumbs-down, bug reports) |
| **Manual transcript review** | Building intuition for failure modes |
| **Systematic human studies** | Calibrating LLM graders; scoring subjective tasks |

"No single evaluation layer catches every issue. With multiple methods
combined, failures that slip through one layer are caught by another."

---

## 8. Talos extensions

Terms we use in Talos that aren't in the Anthropic piece. Marked here so the
team uses them consistently and doesn't reinvent them.

### 8.1 Agents under evaluation

The six Talos agents and the eval category that fits each:

| Agent | Anthropic type | Primary grader mix |
|---|---|---|
| `code` (Pi code-gen) | Coding agent | Code-based (hidden tests) + model-based (pairwise judge) |
| `code-review` | Coding agent (review variant) | Code-based (verdict match) + model-based (category labelling) |
| `security-review` | Coding agent (security variant) | Code-based (per-CWE precision/recall) + model-based (severity calibration) |
| `contract-test` | Coding agent (API-test variant) | Code-based (mutation kill rate, schema validity) — model-based only for triage |
| `release-notes` | Research agent (summarisation variant) | Model-based (faithfulness) + code-based (length, claim grounding) |
| `rca` | Research agent (incident triage) | Code-based (top-k accuracy on labelled cause) + model-based (evidence citation) |

### 8.2 Grader vocabulary specific to Talos

| Term | Definition |
|---|---|
| **Faithfulness** | RAGAS-style: decompose the output into atomic claims; for each, ask a grader "is this entailed by the source?" Score = supported / total. Used for `release-notes`. |
| **Hallucination rate** | % of outputs with ≥ 1 ungrounded claim. Auto-fail in CI for `release-notes`. |
| **Mutation kill rate** | killed_mutants / (total − equivalent). The headline grader for `contract-test`: did the generated tests detect deliberately-injected bugs in the system under test. |
| **Mutation seed** | A small semantic edit to the production code, used as the truth condition for `contract-test` evals. |
| **Top-*k* hypothesis accuracy** | Did the true root cause appear in the agent's top *k* hypotheses. Used for `rca` because RCA is rarely deterministic. |
| **Evidence-citation rate** | % of agent hypotheses that cite a specific `file:line` or log entry. Makes hallucination directly measurable. Used for `rca`. |
| **Cost-to-cause** | Tokens (or trial cost) until the correct answer is named. Used for `rca` and `code`. |
| **SARIF** | [OASIS SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html) — the static-analysis interchange format. We emit `security-review` findings as SARIF for diffability and comparison to Snyk/Semgrep. |
| **Suppression-list utilisation** | How often the `.github/security-review-ignore` list silenced a finding during a trial. Rising = prompt drift; falling = grader improving. |
| **Override rate** | % of agent verdicts a human overrode (merge despite a fail, dismiss a comment). Trust-collapse indicator. |
| **Gate escape rate** | Of merged PRs that later triggered an RCA or contract-test issue, % that had been passed by `code-review` or `security-review`. Each escape = a new task for the regression suite. |

### 8.3 Judge bias terms (model-based grader pitfalls)

| Term | Definition |
|---|---|
| **Position bias** | LLM judge prefers the answer in a particular position in a pairwise comparison. Mitigation: run both orderings; only count agreement. |
| **Verbosity bias** | LLM judge prefers longer answers regardless of quality. Mitigation: length-normalise the rubric. |
| **Self-preference bias** | LLM judge prefers outputs from its own model family. Mitigation: never use the same family for generator and judge. |
| **Authority bias** | LLM judge defers to outputs that sound confident. Mitigation: rubric-driven scoring, not free-form preference. |

### 8.4 System-level (SDLC) metrics

These are not per-agent eval scores; they measure the harness as a whole.

| Term | Definition |
|---|---|
| **DORA metrics** | The four ([dora.dev](https://dora.dev/)): deployment frequency, lead time for changes, change-failure rate, MTTR. The harness-level dashboard. |
| **CFR** (change-failure rate) | % of deploys triggering an RCA or contract-test issue. Pair with deployment frequency to detect AI-era "fast and worse". |
| **MTTR** | Mean time to recovery — RCA issue opened → closed. |
| **Cost per PR** | Total OpenRouter spend across all six agents for one PR end-to-end. The ROI denominator. |
| **Trust-cost ratio** | (1 − override_rate) / cost_per_PR. A single demoable harness-quality number. |
| **Harness drift** | Per-agent regression-suite score moving > 2σ from a 30-day rolling baseline. Sources: silent OpenRouter model swaps, prompt edits, dependency bumps, judge-model updates. |

### 8.5 Phoenix-specific surfaces

[Arize Phoenix](https://arize.com/docs/phoenix/) is already wired into every
Talos agent. Three eval surfaces matter:

| Surface | What it is |
|---|---|
| **Online evaluator** | A Python (or LLM-as-judge) function that runs on every traced span in production. Score is attached to the span and queryable as a metric. Use for "% of code-review comments judged accurate" rolling daily. |
| **Custom evaluator** | Any one-argument Python function returning a bool or float. Runs are themselves OTel-traced so the evaluator is debuggable. |
| **Dataset experiment** | A versioned golden eval suite re-run against a new prompt/model. Produces side-by-side diff tables; integrates with GitHub Actions for per-PR comments. |

---

## 9. Term-mapping for existing prose

If you see older Talos docs (including the original `EVAL_STRATEGY.md` draft)
using the left column, replace with the right column going forward.

| Older Talos term | Anthropic-aligned term |
|---|---|
| "Golden set" / "gold" | **Task suite** (capability or regression) with **reference solutions** |
| "Hand-labelled examples" | **Reference solutions** / human-graded tasks |
| "Offline gate" | **Automated regression eval** |
| "Online observability" | **Production monitoring** + online evaluator |
| "Judge" / "LLM-as-judge" | **Model-based grader** |
| "Replay" (RCA) | A **task** run in a stable **environment** snapshot |
| "Decision rule" (in agent code) | The agent's outcome production — graded separately |
| "Verdict" returned by the LLM | Part of the **transcript**, not the **outcome** |
| "Per-PR cheap suite" | **Regression eval suite** run on every PR |
| "Nightly canary" | **Capability eval suite** run nightly |
| "F1 / precision / recall on diff" | **Code-based grader** with assertions on outcome |
| "Pass@1" | **pass@1** (already aligned) |

---

**Source**: Anthropic Engineering — [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
**Maintained alongside**: `docs/EVAL_STRATEGY.md`
