"""Render evals/.results/results.json as the per-PR markdown comment.

Usage:
    python evals/report.py [results.json] [--baseline BASELINE.json]

Prints markdown to stdout; the CI workflow pipes it into a PR comment.

When a baseline (the same suite run on the PR's base branch, e.g. main) is
supplied with --baseline, the comment also shows the **delta vs base** — this is
the per-PR half of the EVAL_STRATEGY.md §4.1 close-the-loop arc. Because the
same grader runs on both sides (§3.3), the delta is a true regression signal,
not grader drift. The delta surfaces three ways:
  * a **regressions callout** at the top — any task that passed on base and
    fails here (the gate signal);
  * per-agent **Δ tasks-passed** and **Δ pass@1** vs base, computed over the
    tasks common to both sides (apples-to-apples);
  * a per-task **vs base** column (regressed / fixed / new / pass-rate shift).

Per EVAL_STRATEGY.md anti-patterns, results are reported per category — never
collapsed into a single number across buckets.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

MARKER = "<!-- talos:evals -->"


def _parse_pass_rate(r: dict) -> tuple[int, int]:
    """Return (passed_trials, graded_trials) for a result row.

    Reads the runner-recorded ``pass_rate`` ("k/N", e.g. "2/3") defensively:
    older results may lack it, in which case the row is a single graded trial
    whose pass/fail is the trial outcome. Infra rows have no graded trials.
    """
    if r["outcome"] == "infra":
        return 0, 0
    raw = r.get("pass_rate")
    if isinstance(raw, str) and "/" in raw:
        k, _, n = raw.partition("/")
        try:
            return int(k), int(n)
        except ValueError:
            pass
    # No usable pass_rate -> treat as a single trial = its own outcome.
    return (1 if r["outcome"] == "pass" else 0), 1


def _key(r: dict) -> tuple[str, str]:
    return (r["agent"], r["task"])


def _pp(passed: int, total: int) -> float:
    return 100 * passed / total if total else 0.0


def _task_delta(cur: dict, base: dict | None) -> tuple[str, bool]:
    """The 'vs base' cell for one task. Returns (label, is_regression).

    A regression is the gate signal: graded pass on base, graded fail here. An
    infra outcome on either side carries no agent-quality signal, so it is never
    a regression.
    """
    if base is None:
        return "🆕 new", False
    if cur["outcome"] == "infra":
        return "—", False
    if base["outcome"] == "infra":
        return "was infra", False
    cur_pass = cur["outcome"] == "pass"
    base_pass = base["outcome"] == "pass"
    if base_pass and not cur_pass:
        return "🔻 regressed", True
    if not base_pass and cur_pass:
        return "🔺 fixed", False
    # Same task-level outcome — surface a trial-level pass_rate shift, if any.
    bk, bn = _parse_pass_rate(base)
    ck, cn = _parse_pass_rate(cur)
    if (bk, bn) != (ck, cn):
        return f"{bk}/{bn}→{ck}/{cn}", False
    return "—", False


def render(results: list[dict], baseline: list[dict] | None = None) -> str:
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_agent[r["agent"]].append(r)
    base_idx: dict[tuple[str, str], dict] = (
        {_key(r): r for r in baseline} if baseline else {}
    )
    has_base = baseline is not None

    lines = [MARKER, "## Talos eval results", ""]

    if has_base:
        lines.append("_Δ vs the base branch — same grader both sides (§3.3)._")
        lines.append("")
        regressions = [
            r for r in results if _task_delta(r, base_idx.get(_key(r)))[1]
        ]
        if regressions:
            lines.append(
                f"### ⚠️ {len(regressions)} regression(s) vs base "
                "— passed on base, failing here"
            )
            for r in regressions:
                lines.append(f"- **{r['agent']}/{r['task']}** ({r.get('category') or '—'})")
            lines.append("")
        else:
            lines.append("✅ No regressions vs base.")
            lines.append("")

    for agent in sorted(by_agent):
        rows = by_agent[agent]
        graded = [r for r in rows if r["outcome"] in ("pass", "fail")]
        infra = [r for r in rows if r["outcome"] == "infra"]
        passed = sum(1 for r in graded if r["outcome"] == "pass")
        # pass@1 = fraction of all graded TRIALS that passed (trial-level),
        # summed across this agent's tasks. The headline is majority pass@k
        # (task-level): a task passes on a strict majority of its trials.
        trial_passed = sum(_parse_pass_rate(r)[0] for r in graded)
        trial_total = sum(_parse_pass_rate(r)[1] for r in graded)
        pass_at_1 = (
            f"{trial_passed}/{trial_total} = {_pp(trial_passed, trial_total):.0f}%"
            if trial_total else "n/a"
        )

        # Deltas vs base over the COMMON graded tasks (apples-to-apples); new
        # tasks (absent from base) are reported as a count, not folded into Δ.
        tasks_delta = pass1_delta = ""
        if has_base:
            common = [
                r for r in graded
                if _key(r) in base_idx and base_idx[_key(r)]["outcome"] in ("pass", "fail")
            ]
            cur_pass_c = sum(1 for r in common if r["outcome"] == "pass")
            base_pass_c = sum(1 for r in common if base_idx[_key(r)]["outcome"] == "pass")
            tasks_delta = f" · Δ {cur_pass_c - base_pass_c:+d} vs base"
            new = [r for r in graded if _key(r) not in base_idx]
            if new:
                tasks_delta += f" (+{len(new)} new)"
            cur_tp = sum(_parse_pass_rate(r)[0] for r in common)
            cur_tt = sum(_parse_pass_rate(r)[1] for r in common)
            base_tp = sum(_parse_pass_rate(base_idx[_key(r)])[0] for r in common)
            base_tt = sum(_parse_pass_rate(base_idx[_key(r)])[1] for r in common)
            pass1_delta = f" · Δ {_pp(cur_tp, cur_tt) - _pp(base_tp, base_tt):+.0f} pp vs base"

        lines.append(
            f"### {agent} — {passed}/{len(graded)} tasks passed (majority pass@k)"
            + (f" ({len(infra)} infra-skipped, not counted)" if infra else "")
            + tasks_delta
        )
        lines.append("")
        lines.append(f"pass@1 (trial-level): {pass_at_1}{pass1_delta}")
        lines.append("")
        header = "| task | category | outcome | trials (pass@k) |"
        sep = "|---|---|---|---|"
        if has_base:
            header += " vs base |"
            sep += "---|"
        header += " detail |"
        sep += "---|"
        lines.append(header)
        lines.append(sep)
        for r in rows:
            icon = {"pass": "✅", "fail": "❌", "infra": "⚠️ infra"}[r["outcome"]]
            detail = r.get("detail", "").replace("|", "\\|")
            if len(detail) > 200:
                detail = detail[:200] + "…"
            trials = "—" if r["outcome"] == "infra" else "{}/{}".format(*_parse_pass_rate(r))
            cell = f"| {r['task']} | {r.get('category', '') or '—'} | {icon} | {trials} |"
            if has_base:
                cell += f" {_task_delta(r, base_idx.get(_key(r)))[0]} |"
            cell += f" {detail} |"
            lines.append(cell)
        lines.append("")
    return "\n".join(lines)


def _load(path: Path) -> list[dict] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Talos eval results as a PR comment.")
    parser.add_argument(
        "results", nargs="?",
        default=str(Path(__file__).parent / ".results" / "results.json"),
        help="path to the run's results.json",
    )
    parser.add_argument(
        "--baseline", default=None,
        help="path to the base-branch results.json; enables the Δ-vs-base view",
    )
    args = parser.parse_args()

    results = _load(Path(args.results))
    if results is None:
        print(f"{MARKER}\n## Talos eval results\n\nNo results file at {args.results} — suite did not run.")
        return 1
    # A missing/empty baseline degrades gracefully to the no-delta view.
    baseline = _load(Path(args.baseline)) if args.baseline else None
    print(render(results, baseline=baseline))
    return 0


if __name__ == "__main__":
    sys.exit(main())
