# EVAL_STRATEGY.md review — recommendations TODO

Source: review of [docs/EVAL_STRATEGY.md](docs/EVAL_STRATEGY.md) against the repo's
purpose (single-maintainer conference demo of a dark-factory SDLC; exam question:
"can I build a dark factory and measure harness improvements?"). Work through one
item at a time; tick when the doc (or repo) reflects the change.

## Major

- [ ] **1. Close the task-suite vs repo-history gap.** *(In progress —
  backlog created at [docs/EVAL_BACKLOG.md](docs/EVAL_BACKLOG.md); next: file
  Wave 1 issues, work them through the pipeline, harvest into
  `evals/datasets/`, then update EVAL_STRATEGY.md §2 to reference the seeded
  approach.)* The doc asks for 100
  labelled PRs (code-review), 30 PRs (release-notes), 20 resolved issues
  (Talos-bench), 10 past incidents (RCA) — the repo has 21 PRs and 3 issues
  total. State explicitly that these suites are **synthetically seeded**
  (labelled defects injected into `todo-api` on fixture branches), mirroring
  the approach already used for contract-test mutation seeds and Juliet flows.
  Seeded tasks are also better for a live demo: controllable, reproducible,
  known ground truth.

- [ ] **2. Invert the structure: demo path first, scale path second.** The MVP
  cuts are buried as the last row of six tables and the dashboard ("the talk's
  punchline") is Phase 4 of an ~8-week plan. Restructure so Phase 0 = the six
  MVP cuts + per-PR diff comment + one dashboard tile (that IS the demo), and
  the full per-agent builds become a "what this looks like at scale" roadmap.

- [ ] **3. Replace human-grader cadences with what one maintainer can do.**
  Quarterly SME recalibration, monthly 10% production labelling, "two SMEs per
  task", a security SME — none of this exists; 10% of production release notes
  monthly ≈ two notes. Collapse to one honest mechanism ("maintainer re-grades
  a sample whenever a suite or judge model changes") and mark the cadence
  tables as the at-scale pattern.

- [ ] **4. Cut or demote SWE-bench Verified Lite.** It measures the model + Pi
  scaffold on foreign repos, not the Talos harness — prompt/harness changes
  barely move it, and 50 agentic coding runs nightly blows the < $5/night
  budget alone. Run it only when the underlying model or Pi version changes.
  Also sanity-check the $5 nightly figure against six capability suites + the
  mutation sweep.

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

- [ ] **5. Make the gates statistically sound — specify trials per task.** The
  strategy gates on single thresholds ("block if F1 drops > 5 pp") with no
  trial count; on a 20-task suite one task = 5 pp, so a single flaky trial
  trips the gate. State trials-per-task (e.g. 3 trials, majority pass; report
  pass@1 and pass@3) and set thresholds in units the suite size can resolve.
  *Most important technical fix in the doc.*

## Moderate

- [ ] **6. Verify the Phoenix sketch (§3.3) against the real API.** The
  `@create_evaluator` / `Client().evaluators.register` code doesn't obviously
  match Phoenix's documented surface (`phoenix.experiments.run_experiment`,
  evals library). Pin it to a tested Phoenix version or label it pseudocode.
  *(2026-06-21: §3.3 lead now labels the snippet pseudocode and points at the
  real substrate. The Arize-side surface for §3.5 is confirmed —
  `arize.exporter.ArizeExportClient.export_model_to_df` (SDK ≥ 7.0.3) and
  `arize.experimental.datasets.ArizeDatasetsClient.create_dataset/run_experiment`.
  Still to pin: the online-evaluator registration call itself.)*

- [x] **7. Pick one CI eval tool.** *(Done 2026-06-11: the `evals/` runner is
  plain pytest — no DeepEval. Strategy §4 Phase 0 updated; Phoenix deferred
  until the agents trace to it rather than Arize AX.)* Phase 0 brings in
  DeepEval *and* Phoenix. Drop DeepEval unless a specific gate is materially
  cheaper with it — plain pytest + Phoenix experiments covers the need and
  keeps the pattern clean.

- [ ] **8. Split harness metrics (§3.2) into "demoable now" vs "needs scale".**
  Override rate, gate escape rate, and CFR need human reviewers and deploy
  volume the demo won't have; cost per PR, stage cycle time, and the per-PR
  trace tree work from day one. Be explicit, or the dashboard shows empty /
  noise-dominated panels on stage.

## Minor

- [ ] **9. Define the dual-judge disagreement path.** "Only fail on agreement"
  biases toward missing regressions — fine for a gate, but say so and specify
  what happens on disagreement (currently undefined).

- [x] **10. Fix the per-PR trigger path filter.** *(Done 2026-06-11:
  `.github/workflows/talos-evals.yml` triggers on `agents/**` (plus `evals/**`)
  only; the `prompts/**` glob is gone. §3.4 cadence table updated to match.)*
  `agents/**` or `prompts/**` — prompts live inside `agents/*/`, so `prompts/**`
  matches nothing. Check against the actual layout.

## Framing

- [ ] **11. Add a section that closes the loop on the exam question.** Show the
  *experiment* that claims "the harness improved": a prompt change lands → the
  per-PR diff comment shows regression deltas → the nightly capability curve
  moves → the DORA throughput/quality pairing stays healthy. That narrative
  arc is the talk's actual punchline; right now it's implied, not written.
