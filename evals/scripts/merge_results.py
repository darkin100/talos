"""Merge per-agent results.json files into the single file report.py renders.

The Talos Evals workflow runs one matrix leg per agent, and each leg's
``pytest_sessionfinish`` (evals/conftest.py) overwrites its own copy of
``.results/results.json`` with only that agent's rows. The report job downloads
every leg's artifact into ``<artifacts>/eval-results-<agent>/results.json``;
this script concatenates those per-agent lists back into one results.json so the
PR comment (and the Δ-vs-baseline diff, keyed by (agent, task)) covers every
agent that ran.

Usage:
    python evals/scripts/merge_results.py <artifacts-dir> <out.json>

A missing/empty artifacts dir is not an error: it writes an empty list, which
report.py renders as the no-results view rather than crashing the gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def merge(artifacts_dir: Path) -> list[dict]:
    rows: list[dict] = []
    files = sorted(artifacts_dir.glob("eval-results-*/results.json"))
    for f in files:
        rows.extend(json.loads(f.read_text(encoding="utf-8")))
    print(f"merged {len(rows)} result row(s) from {len(files)} agent artifact(s)")
    return rows


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    artifacts_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = merge(artifacts_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
