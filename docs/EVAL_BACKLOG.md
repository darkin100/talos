# Eval dataset backlog

This backlog closes [TODO.md item 1](../TODO.md): the eval task suites in
[EVAL_STRATEGY.md](./EVAL_STRATEGY.md) need more history than the repo has
(21 PRs, 3 issues). Instead of waiting for history, we grow the `todo-api`
through a deliberate backlog where **every item doubles as eval data**. Work
an item through the real pipeline (issue → `@talos` → PR → agent gates →
merge → deploy → RCA), then harvest the artefacts into the dataset with the
ground-truth label we knew when we wrote the item.

Two kinds of item, with different merge rules:

- **Organic** — real features and bugs. Merged to `main` like any work.
  Harvested into Talos-bench, release-notes references, and the "clean"
  halves of the review suites.
- **Seeded** — PRs or branches authored with a *known planted flaw*
  (defect category, CWE, mutation, incident). Labelled `eval-seed`,
  **never merged to main** (closed after harvesting, or kept as fixture
  branches). The planted flaw is the reference solution.

## Dataset layout

Harvested tasks live in `evals/datasets/<agent>/<task-id>/`:

```
evals/datasets/
├── code/talos-bench-001/        # task.json: issue ref, base SHA, hidden test ref
├── code-review/cr-001/          # task.json: PR ref, category label, expected verdict
├── security-review/sec-001/     # task.json: PR ref, CWE, severity, expected findings
├── contract-test/mut-001/       # mutation.patch + expected violation
├── release-notes/rn-001/        # input (PR/commits) + reference.md (hand-edited)
└── rca/rca-001/                 # logs.jsonl + source SHA + labelled cause
```

`task.json` always carries: `id`, `source` (issue/PR/branch URL), `label`
(the ground truth), `created`, and `suite` (`capability` | `regression`).

---

## Wave 1 — sized exactly to the MVP cuts

The first wave produces precisely what the six "MVP first cut" rows in
EVAL_STRATEGY.md §2 require. Nothing more.

**Status (2026-06-11): Wave 1 harvested and runnable.** All six MVP cuts are
populated in `evals/datasets/` and replay green through the `evals/` pytest
runner (`pytest evals`). The runner, graders, the per-PR CI workflow
(`.github/workflows/talos-evals.yml`), and hermetic `diff.patch`/`input.json`
inputs land alongside the data — this *is* the EVAL_STRATEGY.md Phase 0
deliverable. See `evals/README.md` for how each agent replays.

| MVP requirement (from strategy) | Backlog items that produce it | Status |
|---|---|---|
| code: 5 fix-a-bug tasks | B1–B2 + retro-harvest #46/#38; B3 live | talos-bench-001..004 ✅, B3 (#66) in flight |
| code-review: 5 real-defect + 5 style-only PRs | S1–S5 (seeded defects) + S6–S10 (style-only) | cr-006..015 ✅ (+ organic cr-001..005) |
| security: 5 CWE flows + 5 clean PRs | V1–V5 (seeded vulns) + 5 merged clean PRs | sec-002..011 ✅ (+ organic sec-001) |
| contract-test: 3 mutation seeds | M1–M3 | mut-001..003 ✅ (+ organic ct-001) |
| release-notes: 5 reference notes | rn-001 + 4 retro-harvested merges | rn-001..005 ✅ |
| rca: 3 replay tasks + 2 clean runs | I1, I2, #15 + 2 healthy deploys | incident-001/003, dep0169-001, clean-001/002 ✅ (+ organic incident-002) |

### Track B — genuine bugs already in the code (organic)

Found by inspection of `api/handler.js` / `lib/store.js` — file these as
real issues, fix via `@talos`, harvest as Talos-bench tasks.

| ID | Issue to file | Ground truth |
|---|---|---|
| B1 ✅ *(done 2026-06-10: issue #25 → PR #26 → v48; harvested as talos-bench-001, cr-001, rn-001, rca/clean-001)* | `PUT /api/todos/:id` silently resets `completed` to `false` when the body omits it (`store.update` does `completed = !!completed`). Toggling a title wipes completion state. | Fix: preserve existing `completed` when absent. Test: update title only → completed unchanged. |
| B2 ✅ *(done 2026-06-10: seeded incident → RCA issue #30 → PR #31 → fixed; harvested as talos-bench-002 + cr-002 — note the fix omitted the requested test and code-review passed it anyway, an organic `missing_test` miss)* | `GET /api/todos/search?q=a&q=b` returns 500 — repeated query param arrives as an array, `q.toLowerCase()` throws (`handler.js` `handleSearch`). | Fix: coerce/reject array `q` with 400. Test: repeated param → 400 (or first value), never 500. |
| B3 🔄 *(2026-06-11: filed as issue #66, `@talos` triggered — live pipeline run in flight; harvest talos-bench-005 on merge)* | `POST /api/todos` accepts unbounded `title` length — no max, so a 10 MB title is stored and echoed on every list call. | Fix: 400 over a documented max (e.g. 500 chars); update `openapi.yaml` `maxLength`. |

> B2 is also an **RCA incident seed**: deploy *without* the fix, hit the
> endpoint, harvest the 500s from logs as `rca/` replay task I1 — then merge
> the fix. One backlog item, two datasets.

### Track F — small features (organic)

Each: issue → `@talos` → PR → merge. Harvest: Talos-bench task,
release-note reference, contract-test surface (spec grows), clean PRs for
the review suites.

| ID | Feature | Notes for the issue |
|---|---|---|
| F1 | Filter list by status: `GET /api/todos?completed=true\|false` | Spec + handler + test. Small, single-file — ideal first Talos-bench task. *(The inverted-filter variant was used as seeded defect S1/cr-011; the correct organic merge is still open.)* |
| F2 | `PATCH /api/todos/:id` partial update | Fixes the PUT wart properly; supersedes the B1 workaround. Spec change exercises contract-test. |
| F3 | `GET /api/todos/stats` → `{total, completed, open}` | Tiny new endpoint; good fix-a-bug-sized task. *(The no-test variant was used as seeded defect S5/cr-015; the correct organic merge is still open.)* |
| F4 | `due_date` field (ISO 8601, optional) on create/update | Validation surface (bad date → 400) feeds future mutation seeds. |
| F5 | `priority` field (`low\|medium\|high`, default `medium`) | Enum validation; UI dropdown in `public/index.html`. |

### Track S — seeded code-review fixtures (seeded, never merged)

Author each as a PR labelled `eval-seed:code-review`; record category in
`task.json`; close after the code-review agent has run (its comment is the
trial output to grade against the label).

All ten harvested 2026-06-11. **Seeded defect PRs are opened as drafts** (see
harness-failure log #6) so the SDLC auto-merge cannot land them; the
code-review agent still runs and comments on a draft.

| ID | PR content | Label | Harvest |
|---|---|---|---|
| S1 ✅ | F1 implementation with the filter inverted (`completed=true` returns open todos) | `real_defect` | PR #61 → cr-011 (agent FAIL ✓) |
| S2 ✅ | Search "optimisation" that drops `.toLowerCase()` — silently becomes case-sensitive | `real_defect` | PR #62 → cr-012 (agent FAIL ✓) |
| S3 ✅ | DELETE returns `200` + body instead of `204` (contract break vs `openapi.yaml`) | `real_defect` | PR #63 → cr-013 (agent FAIL ✓) |
| S4 ✅ | New endpoint with copy-pasted validation block duplicated from `handleTodos` | `maintainability` | PR #64 → cr-014 (agent FAIL ✓) |
| S5 ✅ | F3 implementation with no test added to `store.test.js` | `missing_test` | PR #65 → cr-015 (agent FAIL ✓) |
| S6–S10 ✅ | Five style-only PRs: rename locals, reorder imports, comment rewording, README typo fix, log message tweak | `style_only` (agent must stay silent — FPR half of the suite) | PRs #50–54 → cr-006..010 (agent PASS ✓; #50 & #54 auto-merged before close — reverted via #55, see harness-failure log #6) |

### Track V — seeded security fixtures (seeded, never merged)

PRs labelled `eval-seed:security-review`, one CWE each, mapped to the
strategy's in-scope categories. All five harvested 2026-06-11 as **draft**
PRs (a planted vuln must never auto-merge — harness-failure log #6). Each
vuln also trips code-review, and the SDLC short-circuits security-review
when code-review FAILs (harness-failure log #7), so these are graded via the
hermetic runner (DRY_RUN replay of the stored `diff.patch`) rather than a
live security-review comment.

| ID | Planted vulnerability | CWE | Severity | Harvest |
|---|---|---|---|---|
| V1 ✅ | Render `todo.title` unescaped into `public/index.html` DOM via `innerHTML` | CWE-79 (XSS) | high | PR #56 → sec-002 |
| V2 ✅ | Log raw `req.body` (user-controlled) into the single-line JSON logs — log injection | CWE-117 | medium | PR #57 → sec-003 |
| V3 ✅ | Hardcoded credentials committed in a new `lib/config.js` | CWE-798 | critical | PR #58 → sec-004 (real Stripe-format token tripped GitHub push protection — re-seeded as a basic-auth credential) |
| V4 ✅ | `Object.assign(existing, req.body)` in update — mass-assignment / prototype-pollution path | CWE-915 | high | PR #59 → sec-005 |
| V5 ✅ | Search switched to `new RegExp(q)` on raw user input — ReDoS | CWE-1333 | medium | PR #60 → sec-006 |

Clean half (FPR): sec-007..011 from merged organic PRs #26/#47/#45/#41/#39 —
the agent must stay silent.

### Track M — contract-test mutation seeds (seeded, fixture branches)

Branches `eval-seed/mutation-<n>` off main, each a one-line handler bug.
Stored as `mutation.patch` + expected violation in `evals/datasets/contract-test/`.

All three pushed 2026-06-11 (branches `eval-seed/mutation-1..3`); the runner
copies `todo-api`, applies the patch, serves it locally, and replays
contract-test against it. Two were adapted from the original spec so the
*agent* (not a spec gap) is what's tested — see each `task.json` rationale.

| ID | Mutation | Expected catch | Status |
|---|---|---|---|
| M1 ✅ | POST success returns `200` instead of `201` | wrong-status violation | mut-001 (killed ✓) |
| M2 ✅ | `create()` drops `completed` (a *required* field; `created_at` is spec-optional, so the original M2 mutant would survive) | schema violation (required field) | mut-002 (killed ✓) |
| M3 ✅ | `search` wraps results as `{results: [...]}` (the deterministic set never GETs an existing todo, so the original GET-by-id wrap is only LLM-catchable) | schema violation (shape) | mut-003 (killed ✓) |

### Track I — RCA incident seeds

| ID | Incident | Harvest |
|---|---|---|
| I1 ✅ *(done 2026-06-10: 50x 500s seeded into the post-promote soak window; RCA top-1 hit with file:line evidence → incident-001. Bonus organic harvest: incident-002, RCA's first false positive — DEP0169 noise re-raised as #32 despite triage in #15; suppression fix = issue #33)* | B2 deployed unfixed; traffic with repeated `q` params → 500s in logs | logs.jsonl + SHA + labelled cause ("array query param unhandled in handleSearch") |
| I2 ✅ *(2026-06-11: seeded log bundle, no live deploy — faithful to the circular-metadata throw; companion 2nd real-incident replay)* | A build where `logEvent` throws on circular metadata — every request 500s | incident-003: logs + labelled cause (`logging.js:13` JSON.stringify in `logEvent`) |
| ✅ | Closed issue #15 (DEP0169 deprecation warning) | dep0169-001: DEP0169-only bundle; ground truth = suppressed, no issue (the regression guard for the suppressions.json packaging path broken by #42) |
| ✅ | Two healthy deploys, logs captured | clean-001 + clean-002 (FPR half) |

---

## Wave 2 — capability-suite growth (after Wave 1 is harvested)

Larger features that create multi-file Talos-bench tasks and harder review
fixtures. File only once Wave 1 is in `evals/datasets/`.

- Tags on todos (`tags: string[]`, filter by tag) — multi-file, spec + store + UI
- Pagination (`?limit&offset`) with envelope response — breaking spec change, good contract-test stress
- Sort param (`?sort=created_at|title&order=asc|desc`)
- Description/notes field with markdown rendering in UI (second XSS surface for V-track)
- Bulk operation: `POST /api/todos/clear-completed`
- Persistence via Vercel KV / marketplace store — the big one; produces a rich
  multi-file Talos-bench task and a real release-note challenge
- Adversarial release-note inputs: a PR with a misleading title, a fixup-only
  PR (the strategy's saturation-watch cases)

## Harness-failure log (feeds EVAL_STRATEGY.md "harness vs agent failure")

Failures observed *while generating eval data* on 2026-06-10 — none of which
reflect agent answer-quality, all of which a green-checkmark dashboard would
miss. The strategy needs to score agents only on runs that actually executed:

1. **Platform outage** — GitHub API auth incident (erroneous 401s) killed the
   first code-agent run after it had already pushed its branch.
2. **Repo misconfiguration** — "Allow GitHub Actions to create PRs" was off, so
   `gh pr create` failed; masked by (1) on the first attempt.
3. **Agent-harness hang** — Pi stalled indefinitely on issue #38 (run
   27295653691 cancelled after 30+ min); fixed by human fallback (PR #41).

4. **Docker Hub flake** — `Build agent images` timed out pulling
   `python:3.12-slim` (transient registry i/o timeout); cleared on rerun.
5. **Packaging gap (passed all gates, failed in prod)** — the RCA suppression
   rules (#33/#37) worked in local replay and passed code-review,
   security-review, and unit tests, but `agents/rca/Dockerfile` copied only
   `agent.py`, not `suppressions.json` — so the deployed image loaded 0 rules
   and re-raised DEP0169 as #42. Neither review agent flagged the cross-file
   omission. This is the strongest argument in the repo for grading
   **real-deploy outcomes**, not just unit tests: no test that imports the
   module can see a missing `COPY` line.

Observed 2026-06-11 while harvesting the seeded fixtures (Wave 1 build-out):

6. **Auto-merge landed two seeds on main** — the SDLC `auto-merge` job enables
   `gh pr merge --auto` on every PR, gated only on `pr-review` passing. Two
   style-only seed PRs (#50, #54) passed code-review and auto-merged before
   they could be closed; the three that the agent happened to comment on more
   slowly were closed in time. Reverted via #55 (which code-review then *failed*
   with backwards reasoning — harvested for judge calibration). **Fix adopted:
   open every seeded PR as a draft** — `--auto` cannot merge a draft, but the
   review agents still run and comment. A planted *vulnerability* auto-merging
   to main (had V1–V5 gone in non-draft) would have been a real incident, not a
   cosmetic one.
7. **Review short-circuit hides one agent's trial** — `pr-review` runs
   code-review then security-review as ordered steps with no `if: always()`.
   When code-review exits non-zero, the job stops and security-review never
   runs. Every V-track vuln also trips code-review, so none produced a live
   security-review comment. Consequence for eval harvesting: **security
   fixtures are graded by the hermetic runner** (DRY_RUN replay of the stored
   `diff.patch`), not by scraping a live PR comment. Also a real harness smell —
   a PR's security posture is unknown whenever code-review fails first.
8. **Push protection caught a realistic secret seed** — V3's first attempt used
   a Stripe-format `sk_live_…` token; GitHub secret scanning blocked the push
   (correctly). Re-seeded as a basic-auth credential, which still exercises
   CWE-798 without matching a vendor secret pattern. Note for seed authors:
   plant credentials that read as hardcoded secrets to a reviewer but don't
   match push-protection regexes.

Observed 2026-06-20 while fixing the code-review false positives (cr-005, cr-016):

9. **Diff-only review caused convention-blind false positives → agent rewritten
   to use Pi with code access.** The code-review agent reviewed only the unified
   diff (~3 lines of context), so it invented defects the surrounding file
   contradicts (cr-016: "this `return 400` is wrong" when every handler in the
   file returns a numeric status; cr-005: a hallucinated double-response and a
   non-existent missing default export). Rewrote the agent to drive Pi inside a
   checkout of the repo so it reads full files and must ground each claimed
   defect in the actual code. Result on the regression suite: cr-016 flips to a
   correct PASS, graduates capability→regression, and recall holds (cr-011/012/
   013 real-defect and cr-015 missing-test still correctly FAIL; style-only
   PRs stay silent). Two sub-findings worth keeping:
   - *Verdict non-determinism.* A small model driving the agentic loop sometimes
     ends without emitting the final JSON verdict. The agent now retries
     (bounded) and treats a persistent no-verdict as an **infra skip**, never a
     graded fail — a crash-to-fail on a clean PR would manufacture the very
     false positives this fix removes.
   - *Workspace replay needs the diff to apply.* The hermetic replay rebuilds
     the reviewed tree by applying `diff.patch` to current `todo-api`. Six older
     fixtures (cr-001/002/003/004/005/009) were harvested against drifted bases
     and no longer apply, so they now infra-skip. Reviewing them against the
     unpatched tree was tried and **mis-graded a real defect** (cr-004 passed —
     the defect lives only in the diff), so skipping is the honest behaviour.
     Re-harvest against current main or pin a base SHA to restore coverage.

Implication for the strategy: distinguish *infra/harness failure* from *agent
failure* before computing pass rates; add timeouts + bounded-retry +
human-escalation as first-class harness behaviour (exercised manually on #33
and #38); keep at least one **outcome grader that exercises the built
artefact** (the deployed container), since #5 is invisible to every
source-level grader; and treat the **eval runner's infra-vs-agent split**
(`InfraFailure` → pytest skip, never a fail — see `evals/runner.py`) as the
code embodiment of that first principle. Findings #6/#7 are arguments for two
harness guards the strategy should name: seeds must be merge-blocked
(draft/label), and review stages should run independently (`if: always()`) so
one agent's verdict never masks another's.

## Working agreement

1. One item at a time, through the real pipeline — the pipeline run *is* the
   data generation.
2. Harvest immediately after each item closes (while ground truth is fresh):
   write `task.json`, commit to `evals/datasets/`.
3. Seeded PRs are closed, never merged; their branches are kept (`eval-seed/*`)
   so tasks are re-runnable from the SHA.
4. Every harvested task records which wave/track it came from, so suite
   balance (defect vs clean) is auditable.
