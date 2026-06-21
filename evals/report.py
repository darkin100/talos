"""Render evals/.results/results.json as the per-PR markdown comment.

Usage: python evals/report.py [results.json]
Prints markdown to stdout; the CI workflow pipes it into a PR comment.
Per EVAL_STRATEGY.md anti-patterns, results are reported per category —
never collapsed into a single number across buckets.
"""

from __future__ import annotations

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


def render(results: list[dict]) -> str:
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_agent[r["agent"]].append(r)

    lines = [MARKER, "## Talos eval results", ""]
    for agent in sorted(by_agent):
        rows = by_agent[agent]
        graded = [r for r in rows if r["outcome"] in ("pass", "fail")]
        infra = [r for r in rows if r["outcome"] == "infra"]
        passed = sum(1 for r in graded if r["outcome"] == "pass")
        # pass@1 = fraction of all graded TRIALS that passed (trial-level),
        # summed across this agent's tasks. The headline above is majority
        # pass@k (task-level): a task passes on a strict majority of its trials.
        trial_passed = sum(_parse_pass_rate(r)[0] for r in graded)
        trial_total = sum(_parse_pass_rate(r)[1] for r in graded)
        pass_at_1 = (
            f"{trial_passed}/{trial_total} = {100 * trial_passed / trial_total:.0f}%"
            if trial_total else "n/a"
        )
        lines.append(f"### {agent} — {passed}/{len(graded)} tasks passed (majority pass@k)"
                     + (f" ({len(infra)} infra-skipped, not counted)" if infra else ""))
        lines.append("")
        lines.append(f"pass@1 (trial-level): {pass_at_1}")
        lines.append("")
        lines.append("| task | category | outcome | trials (pass@k) | detail |")
        lines.append("|---|---|---|---|---|")
        for r in rows:
            icon = {"pass": "✅", "fail": "❌", "infra": "⚠️ infra"}[r["outcome"]]
            detail = r.get("detail", "").replace("|", "\\|")
            if len(detail) > 200:
                detail = detail[:200] + "…"
            if r["outcome"] == "infra":
                trials = "—"
            else:
                k, n = _parse_pass_rate(r)
                trials = f"{k}/{n}"
            lines.append(f"| {r['task']} | {r.get('category', '') or '—'} | {icon} | {trials} | {detail} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / ".results" / "results.json"
    if not path.exists():
        print(f"{MARKER}\n## Talos eval results\n\nNo results file at {path} — suite did not run.")
        return 1
    print(render(json.loads(path.read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
