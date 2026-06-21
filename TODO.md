# EVAL_STRATEGY.md review — recommendations TODO

Source: review of [docs/EVAL_STRATEGY.md](docs/EVAL_STRATEGY.md) against the repo's
purpose (single-maintainer conference demo of a dark-factory SDLC; exam question:
"can I build a dark factory and measure harness improvements?"). Work through one
item at a time; tick when the doc (or repo) reflects the change.

## Major

- [x] **1. Close the task-suite vs repo-history gap.** *(Done 2026-06-21:
  added a §2 lead note in EVAL_STRATEGY.md stating the at-scale cell counts are
  a target, not history — the repo has only 21 PRs / 3 issues — and that the
  suites are synthetically seeded (labelled defects injected into `todo-api` on
  fixture branches, clean halves from real merges), the same mechanism as the
  contract-test mutation seeds (§2.4) and Juliet flows (§2.3). Calls out that
  seeded tasks are better for a live demo (controllable, reproducible, known
  ground truth), cites [docs/EVAL_BACKLOG.md](docs/EVAL_BACKLOG.md) and the
  current on-disk 48 task.json / §0.1. Individual §2 cells left unchanged.)*
  Backlog created at [docs/EVAL_BACKLOG.md](docs/EVAL_BACKLOG.md). The doc asks for 100
  labelled PRs (code-review), 30 PRs (release-notes), 20 resolved issues
  (Talos-bench), 10 past incidents (RCA) — the repo has 21 PRs and 3 issues
  total. State explicitly that these suites are **synthetically seeded**
  (labelled defects injected into `todo-api` on fixture branches), mirroring
  the approach already used for contract-test mutation seeds and Juliet flows.
  Seeded tasks are also better for a live demo: controllable, reproducible,
  known ground truth.

- [x] **2. Invert the structure: demo path first, scale path second.**
  *(Done 2026-06-21.)* The MVP cuts were buried as the last row of six §2 tables
  and the dashboard ("the talk's punchline") was Phase 4 of an ~8-week plan.
  Added [EVAL_STRATEGY.md §0.1 "The demo, built today"](docs/EVAL_STRATEGY.md)
  right after the executive summary: it collects the six MVP first cuts into one
  table, names the three demo ingredients (six cuts + per-PR eval comment via
  `report.py`/`talos-evals.yml` + one dashboard tile), grounds each in real repo
  paths, and flags the standing dashboard tile as the one remaining demo piece
  (only `evals/_progress.py`, a TTY-only panel, exists). Recast §2 (now "Per-agent
  strategy (what this looks like at scale)") and §4 (now "Implementation phases
  (the scale-up roadmap)") with lead blockquotes marking them as the roadmap
  beyond the demo; all original content (the six per-agent tables incl. their MVP
  first-cut rows, and the 5-phase plan) preserved.

- [x] **3. Replace human-grader cadences with what one maintainer can do.**
  *(Done 2026-06-21: collapsed all six §2 "Human grader cadence" rows to the
  single honest mechanism — "the maintainer re-grades a sample whenever a suite
  or the judge model changes" (per §3.5) — with the SME quarterly/monthly/
  per-spec versions explicitly demoted to "*At scale*". §3.4 Monthly/Quarterly
  rows now tagged "*(at scale)*" with the today-mechanism inline. §0 exec
  summary and §1 principle 2 quarterly phrasings got at-scale qualifiers so no
  location still presents the SME cadence as running today. §2.5 notes a solo
  maintainer's 10% monthly ≈ two notes — too few to recalibrate.)*
  Quarterly SME recalibration, monthly 10% production labelling, "two SMEs per
  task", a security SME — none of this exists; 10% of production release notes
  monthly ≈ two notes.

- [x] **4. Cut or demote SWE-bench Verified Lite.** *(Done 2026-06-21: demoted
  in EVAL_STRATEGY.md. §2.1 "Nightly capability eval" row relabelled "External
  capability baseline (on model/Pi change)" — runs only when the model or Pi
  version changes, flagged as a model-baseline (not a harness signal) and noted
  that 50 agentic instances alone exceed the nightly budget; §2.1 Gate row notes
  SWE-bench is not part of the gate. §3.4 Nightly row drops SWE-bench (now
  capability suites + mutation sweep + OWASP Benchmark), budget annotated to
  explain the <$5/night figure, and a new "On model / Pi version change" cadence
  row added. §4 Phase 3 reconciled to "wired as an on-model/Pi-change external
  baseline (not nightly)". §5 contamination note holds unchanged.)*
  It measures the model + Pi scaffold on foreign repos, not the Talos harness.

- [ ] **12. Harvest Arize AX traces into the dataset suite.** *(Strategy
  written 2026-06-21: new [EVAL_STRATEGY.md §3.5](docs/EVAL_STRATEGY.md). The
  agents already trace every run to Arize AX as OpenInference spans (root
  `talos.<agent>.run`, kind `AGENT`, `input.value`/`output.value` JSON); that
  trace store is the production sample the suite-refresh cadence needs.)*
  Remaining build: a `evals/scripts/harvest_arize.py` that exports root spans
  (`ArizeExportClient.export_model_to_df(..., Environments.TRACING, ...)`),
  filters out `InfraFailure` spans, scrubs secrets/PII, maps `input.value`→the
  hermetic input + `output.value`→`reference_trial`, freezes the code-review
  `source/` snapshot, and writes `evals/datasets/<agent>/<id>/`. Label via Arize
  annotations (TODO #3 mechanism); admit to capability; tag the source window so
  prompt-tuning can be held out (contamination guard). Harvest overrides + FPs
  first — that path is currently manual (cr-005/cr-016/sec-012).

- [x] **5. Make the gates statistically sound — specify trials per task.**
  *(Done 2026-06-21.)* The original ask: the strategy gated on single
  thresholds ("block if F1 drops > 5 pp") with no trial count; on a 20-task
  suite one task = 5 pp, so a single flaky trial tripped the gate — state
  trials-per-task (3 trials, majority pass; report pass@1 and pass@3) and set
  thresholds in units the suite size can resolve. The CI already ran the gate
  at `--trials 3` with strict-majority grading
  (`.github/workflows/talos-evals.yml`); this change makes the **strategy doc**
  match the runner: every §0/§1/§2/§3 gate, saturation watch and the harness-
  drift / per-PR cadence rows now state trials/task = 3, strict-majority
  (ties fail, infra trials excluded), report **both pass@1 (trial-level) and
  majority pass@3 (task-level)**, and express every threshold in the
  pp-per-task each suite actually resolves (e.g. no 5 pp gate on a 10-pp/task
  suite). Principle 5 now defines graduation capability→regression as reliable
  success *across trials* (sustained majority pass@3 on N consecutive nights),
  not a single lucky pass. `evals/report.py` now surfaces the recorded
  `pass_rate` ("k/N") per task in the table and a per-agent pass@1 line
  alongside the majority pass@k headline (parses `pass_rate` defensively;
  legacy rows = single trial; per-category reporting and the results.json
  schema / MARKER unchanged). *Most important technical fix in the doc.*

## Moderate

- [x] **6. Verify the Phoenix sketch (§3.3) against the real API.** *(Done
  2026-06-21: §3.3 lead now states the code block is illustrative pseudocode
  (not a tested call); the code-block intro and the `register(...)` call both
  carry inline pseudocode labels. The confirmed Arize export/datasets surface
  for §3.5 is named in the lead, and the single unpinned call is explicitly
  flagged — `Client().evaluators.register(...)` — pointing at Phoenix's
  documented `phoenix.experiments` / evals surface pending a version pin.)*
  The `@create_evaluator` / `Client().evaluators.register` code doesn't obviously
  match Phoenix's documented surface (`phoenix.experiments.run_experiment`,
  evals library). The Arize-side surface for §3.5 is confirmed —
  `arize.exporter.ArizeExportClient.export_model_to_df` (SDK ≥ 7.0.3) and
  `arize.experimental.datasets.ArizeDatasetsClient.create_dataset/run_experiment`.

- [x] **7. Pick one CI eval tool.** *(Done 2026-06-11: the `evals/` runner is
  plain pytest — no DeepEval. Strategy §4 Phase 0 updated; Phoenix deferred
  until the agents trace to it rather than Arize AX.)* Phase 0 brings in
  DeepEval *and* Phoenix. Drop DeepEval unless a specific gate is materially
  cheaper with it — plain pytest + Phoenix experiments covers the need and
  keeps the pattern clean.

- [x] **8. Split harness metrics (§3.2) into "demoable now" vs "needs scale".**
  *(Done 2026-06-21: added a "Demoable now?" column to the §3.2 table — cost per
  PR and stage cycle time = demoable now; gate escape rate, override rate, and
  harness drift = needs scale; trust-cost ratio = partly (cost half now, trust
  half inherits override rate's gap, reconciled with the §0.1 standing tile).
  Added a lead note tying the per-PR trace tree (§3.3) + demoable-now metrics to
  day one and warning the dashboard story must not promise needs-scale panels.)*
  Override rate, gate escape rate, and CFR need human reviewers and deploy
  volume the demo won't have; cost per PR, stage cycle time, and the per-PR
  trace tree work from day one.

## Minor

- [x] **9. Define the dual-judge disagreement path.** *(Done 2026-06-21: §1
  principle 4 now states plainly that agreement-to-fail biases toward false
  negatives (missing regressions) over false positives, with the trust
  rationale, and defines the disagreement outcome — not a gate failure, passed
  for gating but flagged for maintainer review and logged as a calibration
  sample, feeding the §3.4 weekly judge-agreement spot check and the §3.5 step-5
  re-grade-on-change mechanism; disagreement rate itself flagged as a drift
  signal. The §2.1 and §2.2 "Model-based grader" rows now back-reference
  principle 4.)* "Only fail on agreement" biases toward missing regressions —
  fine for a gate, but say so and specify what happens on disagreement.

- [x] **10. Fix the per-PR trigger path filter.** *(Done 2026-06-11:
  `.github/workflows/talos-evals.yml` triggers on `agents/**` (plus `evals/**`)
  only; the `prompts/**` glob is gone. §3.4 cadence table updated to match.)*
  `agents/**` or `prompts/**` — prompts live inside `agents/*/`, so `prompts/**`
  matches nothing. Check against the actual layout.

## Framing

- [x] **11. Add a section that closes the loop on the exam question.**
  *(Done 2026-06-21.)* Added [EVAL_STRATEGY.md §4.1 "Closing the loop: the
  harness-improvement experiment"](docs/EVAL_STRATEGY.md), a dedicated four-beat
  arc: a prompt change lands on an agent → the per-PR eval comment shows
  trials-aware per-category regression deltas (pass@1 trial-level + majority
  pass@3 task-level, per TODO #5) → the nightly capability curve moves (fed by
  the §3.5 Arize-harvest flywheel) → the DORA throughput/quality pairing (§3.1)
  stays healthy (throughput up without CFR creeping; harness-drift §3.2 as the
  alarm). Grounded in real artifacts (`talos-evals.yml`, `report.py`) and honest
  about the two not-yet-built gaps (the baseline delta in the comment, the
  nightly cron). Ends by naming the arc the talk's punchline (dark factory built
  AND its improvement measured); §0 now points to it.
