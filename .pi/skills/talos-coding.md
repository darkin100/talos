---
name: talos-coding
description: Project conventions for the Talos repo when Pi is acting as the coding agent
---

# Talos coding conventions

This repo demonstrates an agentified SDLC. The Pi coding agent is invoked by
`agents/code/agent.py` to implement individual GitHub issues. The harness
handles git operations and PR creation; Pi only edits files.

## Code layout

- `todo-api/` — the demo Node.js Vercel Function (single `api/handler.js`
  with `vercel.json` rewrites). Tests live in `todo-api/test/` and run via
  `npm test`.
- `agents/` — Dockerised Python agents (code-review, security-review,
  release-notes, contract-test, rca, and this `code` agent).
- `.github/workflows/` — the SDLC pipeline. Do not modify these unless the
  issue specifically asks for a workflow change.

## Rules for changes

- Match the existing style of the file you're editing (ESM in `todo-api/`,
  Python 3.12 in `agents/`).
- Before claiming completion, run `npm test` from `todo-api/` if you touched
  anything under that folder.
- Do not add new top-level dependencies unless the issue calls for it.
- Keep changes scoped to the issue. No drive-by refactors.
- Do not write comments that just restate what the code does — see
  `CLAUDE.md` for the broader convention.

## Things the harness will do for you

- `git add -A`, commit, push to a fresh `talos/issue-<N>-<run-id>` branch.
- Open the PR with your final summary as the description.
- React to the triggering comment with `eyes` on start and `rocket` on
  success.

Just edit the files. End with a concise summary of what you changed.
