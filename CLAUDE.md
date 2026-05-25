# Project conventions

## Before opening a PR, check for upstream overlap

Always run `git fetch origin main && git log HEAD..origin/main --oneline` before
`gh pr create`. If `main` has moved, also run
`git merge-tree $(git merge-base origin/main HEAD) origin/main HEAD | head`
to preview conflicts.

If the branch is stale and main contains overlapping work (e.g. a parallel
folder reorg, rename, or refactor of the same files), do **not** push the
existing branch as-is. Instead, cherry-pick only the genuinely new commits
onto a fresh branch from `origin/main` and open the PR from there.

Why: a previous PR (#11) on a stale `feature/folder-cleanup` branch hit
"added in both" conflicts on every file because another PR (#10) had already
landed the same `hello-world/` → `todo-api/` reorg on main. The semantic
change was ~13 lines but git couldn't auto-merge the duplicated reorg
history. Catching the overlap upstream first would have avoided the
conflict entirely.
