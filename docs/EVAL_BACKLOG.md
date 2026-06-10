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

| MVP requirement (from strategy) | Backlog items that produce it |
|---|---|
| code: 5 fix-a-bug tasks | B1–B3 + F1, F3 (bugs + small features below) |
| code-review: 5 real-defect + 5 style-only PRs | S1–S5 (seeded defects) + S6–S10 (style-only) |
| security: 5 CWE flows + 5 clean PRs | V1–V5 (seeded vulns); clean = any 5 merged Wave-1 PRs |
| contract-test: 3 mutation seeds | M1–M3 |
| release-notes: 5 reference notes | hand-edit the notes generated for the 5 organic merges |
| rca: 3 replay tasks + 2 clean runs | I1–I2 + closed issue #15; clean = 2 healthy deploys |

### Track B — genuine bugs already in the code (organic)

Found by inspection of `api/handler.js` / `lib/store.js` — file these as
real issues, fix via `@talos`, harvest as Talos-bench tasks.

| ID | Issue to file | Ground truth |
|---|---|---|
| B1 ✅ *(done 2026-06-10: issue #25 → PR #26 → v48; harvested as talos-bench-001, cr-001, rn-001, rca/clean-001)* | `PUT /api/todos/:id` silently resets `completed` to `false` when the body omits it (`store.update` does `completed = !!completed`). Toggling a title wipes completion state. | Fix: preserve existing `completed` when absent. Test: update title only → completed unchanged. |
| B2 | `GET /api/todos/search?q=a&q=b` returns 500 — repeated query param arrives as an array, `q.toLowerCase()` throws (`handler.js` `handleSearch`). | Fix: coerce/reject array `q` with 400. Test: repeated param → 400 (or first value), never 500. |
| B3 | `POST /api/todos` accepts unbounded `title` length — no max, so a 10 MB title is stored and echoed on every list call. | Fix: 400 over a documented max (e.g. 500 chars); update `openapi.yaml` `maxLength`. |

> B2 is also an **RCA incident seed**: deploy *without* the fix, hit the
> endpoint, harvest the 500s from logs as `rca/` replay task I1 — then merge
> the fix. One backlog item, two datasets.

### Track F — small features (organic)

Each: issue → `@talos` → PR → merge. Harvest: Talos-bench task,
release-note reference, contract-test surface (spec grows), clean PRs for
the review suites.

| ID | Feature | Notes for the issue |
|---|---|---|
| F1 | Filter list by status: `GET /api/todos?completed=true\|false` | Spec + handler + test. Small, single-file — ideal first Talos-bench task. |
| F2 | `PATCH /api/todos/:id` partial update | Fixes the PUT wart properly; supersedes the B1 workaround. Spec change exercises contract-test. |
| F3 | `GET /api/todos/stats` → `{total, completed, open}` | Tiny new endpoint; good fix-a-bug-sized task. |
| F4 | `due_date` field (ISO 8601, optional) on create/update | Validation surface (bad date → 400) feeds future mutation seeds. |
| F5 | `priority` field (`low\|medium\|high`, default `medium`) | Enum validation; UI dropdown in `public/index.html`. |

### Track S — seeded code-review fixtures (seeded, never merged)

Author each as a PR labelled `eval-seed:code-review`; record category in
`task.json`; close after the code-review agent has run (its comment is the
trial output to grade against the label).

| ID | PR content | Label |
|---|---|---|
| S1 | F1 implementation with the filter inverted (`completed=true` returns open todos) | `real_defect` |
| S2 | Search "optimisation" that drops `.toLowerCase()` — silently becomes case-sensitive | `real_defect` |
| S3 | DELETE returns `200` + body instead of `204` (contract break vs `openapi.yaml`) | `real_defect` |
| S4 | New endpoint with copy-pasted validation block duplicated from `handleTodos` | `maintainability` |
| S5 | F3 implementation with no test added to `store.test.js` | `missing_test` |
| S6–S10 | Five style-only PRs: rename locals, reorder imports, comment rewording, README typo fix, log message tweak | `style_only` (agent must stay silent — FPR half of the suite) |

### Track V — seeded security fixtures (seeded, never merged)

PRs labelled `eval-seed:security-review`, one CWE each, mapped to the
strategy's in-scope categories.

| ID | Planted vulnerability | CWE | Severity |
|---|---|---|---|
| V1 | Render `todo.title` unescaped into `public/index.html` DOM via `innerHTML` | CWE-79 (XSS) | high |
| V2 | Log raw `req.body` (user-controlled) into the single-line JSON logs — log injection | CWE-117 | medium |
| V3 | Hardcoded API token committed in a new `lib/config.js` | CWE-798 | critical |
| V4 | `Object.assign(existing, req.body)` in update — mass-assignment / prototype-pollution path | CWE-915 | high |
| V5 | Search switched to `new RegExp(q)` on raw user input — ReDoS | CWE-1333 | medium |

### Track M — contract-test mutation seeds (seeded, fixture branches)

Branches `eval-seed/mutation-<n>` off main, each a one-line handler bug.
Stored as `mutation.patch` + expected violation in `evals/datasets/contract-test/`.

| ID | Mutation | Expected catch |
|---|---|---|
| M1 | POST success returns `200` instead of `201` | wrong-status violation |
| M2 | `create()` drops `created_at` from the response | schema violation (required field) |
| M3 | GET by id returns the todo wrapped as `{todo: {...}}` | schema violation (shape) |

### Track I — RCA incident seeds

| ID | Incident | Harvest |
|---|---|---|
| I1 | B2 deployed unfixed; traffic with repeated `q` params → 500s in logs | logs.jsonl + SHA + labelled cause ("array query param unhandled in handleSearch") |
| I2 | Deploy a build where `logEvent` throws on circular metadata (seeded in a branch) — every request 500s | logs + labelled cause |
| — | Closed issue #15 (DEP0169 deprecation warning) | retro-harvest as the third replay task |
| — | Two healthy deploys, logs captured | the 2 clean-log runs (FPR half) |

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

## Working agreement

1. One item at a time, through the real pipeline — the pipeline run *is* the
   data generation.
2. Harvest immediately after each item closes (while ground truth is fresh):
   write `task.json`, commit to `evals/datasets/`.
3. Seeded PRs are closed, never merged; their branches are kept (`eval-seed/*`)
   so tasks are re-runnable from the SHA.
4. Every harvested task records which wave/track it came from, so suite
   balance (defect vs clean) is auditable.
