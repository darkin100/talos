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
        lines.append(f"### {agent} — {passed}/{len(graded)} passed"
                     + (f" ({len(infra)} infra-skipped, not counted)" if infra else ""))
        lines.append("")
        lines.append("| task | category | outcome | detail |")
        lines.append("|---|---|---|---|")
        for r in rows:
            icon = {"pass": "✅", "fail": "❌", "infra": "⚠️ infra"}[r["outcome"]]
            detail = r.get("detail", "").replace("|", "\\|")
            if len(detail) > 200:
                detail = detail[:200] + "…"
            lines.append(f"| {r['task']} | {r.get('category', '') or '—'} | {icon} | {detail} |")
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
