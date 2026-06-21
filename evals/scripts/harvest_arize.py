#!/usr/bin/env python3
"""Harvest Arize AX traces into eval dataset tasks (EVAL_STRATEGY.md §3.5).

This CLI takes the root spans Talos agents emit to Arize AX and turns the
interesting ones into hermetic eval tasks under ``evals/datasets/<agent>/``.
It implements the §3.5 flow:

  1. Export root spans for a time window (or load a previously exported file
     with ``--from-file`` for fully offline operation).
  2. Keep one root span per trace where ``name == "talos.<agent>.run"`` and the
     span kind is a recognised root kind.
  3. Drop spans whose output matches an InfraFailure signature (reusing
     ``runner.INFRA_PATTERNS`` / ``runner._classify_infra``) — never tasks.
  4. Scrub secrets / PII from every payload before writing (the suite is
     committed to git).
  5. Write a PLACEHOLDER label for the maintainer to fill in from the Arize
     human annotation.
  6. Admit to the CAPABILITY suite by default and tag each task with its source
     window so prompt-tuning can hold harvested tasks out (contamination guard).

Divergences from the §3.5 prose, confirmed against the live agent code:

* §3.5 says keep ``span kind == "AGENT"``. In current code only
  ``contract-test`` sets ``AGENT``; ``code-review``, ``rca``,
  ``security-review`` and ``release-notes`` set ``CHAIN``. ``is_root_span``
  therefore accepts kind in ``{"AGENT", "CHAIN"}`` or it would reject every
  real trace.
* ``input.value`` carries only *references* (repo / pr_number / log path /
  deployment_url), never the raw hermetic payload (diff / app.log /
  commit_messages / mutation.patch). The harvester writes the hermetic input
  file with a ``NEEDS_HYDRATION`` marker; the maintainer (or capture tooling)
  must hydrate it before the task is replayable.
* The reviewed SHA needed to freeze the code-review ``source/`` snapshot is not
  on the root span for code-review (only ``rca`` metadata has ``commit_sha``).
  ``build_task`` looks under several metadata keys and falls back to a
  ``NEEDS_SHA`` marker rather than inventing one.

Live export needs the ``arize`` and ``pandas`` packages (see
``evals/scripts/requirements-harvest.txt``). They are imported lazily inside
the IO layer only, so this module — and its unit test — import and run with
neither package installed and with no network access.

Usage examples
--------------
  # Live export from Arize for a window
  python evals/scripts/harvest_arize.py --agent code-review \
      --space-id SPACE --start 2026-06-01T00:00:00Z --end 2026-06-08T00:00:00Z

  # Offline: harvest from a previously exported parquet/json/csv
  python evals/scripts/harvest_arize.py --agent rca \
      --from-file traces.json --start 2026-06-01 --end 2026-06-08 --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# runner.py lives at evals/runner.py; this file is evals/scripts/harvest_arize.py.
# runner imports cleanly with stdlib only (no arize/pandas/network/docker at
# import time), so this is safe in the no-network unit test.
_EVALS_DIR = Path(__file__).resolve().parent.parent
if str(_EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVALS_DIR))

import runner  # noqa: E402  (reuse INFRA_PATTERNS / _classify_infra, do not re-invent)

REPO_ROOT = _EVALS_DIR.parent
DEFAULT_OUT = _EVALS_DIR / "datasets"

# Replayable agents (code / talos-bench has no replayer, so it is excluded).
REPLAYABLE_AGENTS = ["code-review", "security-review", "rca", "release-notes", "contract-test"]

# Span kinds that count as a root span. §3.5 says AGENT, but the live agents
# emit CHAIN for everything except contract-test — accept both.
ROOT_SPAN_KINDS = {"AGENT", "CHAIN"}

# Hermetic input filename the runner reads, per agent (authoritative: runner.py).
HERMETIC_INPUT = {
    "code-review": "diff.patch",
    "security-review": "diff.patch",
    "rca": "app.log",
    "release-notes": "input.json",
    "contract-test": "mutation.patch",
}

# Arize columns to request from export_model_to_df.
EXPORT_COLUMNS = [
    "context.span_id",
    "context.trace_id",
    "name",
    "attributes.openinference.span.kind",
    "attributes.input.value",
    "attributes.output.value",
    "attributes.metadata",
    "attributes.session.id",
]

NEEDS_HYDRATION = "NEEDS_HYDRATION"
NEEDS_SHA = "NEEDS_SHA"


# --------------------------------------------------------------------------- #
# record accessors (tolerant of both "attributes.X" and normalized "X" keys)
# --------------------------------------------------------------------------- #
def _get(rec: dict, *keys: str, default=None):
    """Return the first present key from ``keys`` in ``rec``."""
    for k in keys:
        if k in rec and rec[k] is not None:
            return rec[k]
    return default


def get_name(rec: dict):
    return _get(rec, "name")


def get_kind(rec: dict):
    return _get(
        rec,
        "openinference.span.kind",
        "attributes.openinference.span.kind",
        "span_kind",
    )


def get_input_value(rec: dict):
    return _get(rec, "input.value", "attributes.input.value")


def get_output_value(rec: dict):
    return _get(rec, "output.value", "attributes.output.value")


def get_metadata(rec: dict) -> dict:
    raw = _get(rec, "metadata", "attributes.metadata")
    return _loads_maybe(raw) or {}


def get_span_id(rec: dict):
    return _get(rec, "context.span_id", "span_id")


def get_trace_id(rec: dict):
    return _get(rec, "context.trace_id", "trace_id")


def _loads_maybe(value):
    """json.loads a value if it is a JSON string; pass dicts through; else None."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
    return None


# --------------------------------------------------------------------------- #
# pure, unit-testable core
# --------------------------------------------------------------------------- #
def is_root_span(rec: dict, agent: str) -> bool:
    """True if ``rec`` is the agent's root span.

    Keeps ``name == "talos.<agent>.run"`` AND span kind in {AGENT, CHAIN}.
    See module docstring on the AGENT-vs-CHAIN divergence from §3.5.
    """
    if get_name(rec) != f"talos.{agent}.run":
        return False
    return get_kind(rec) in ROOT_SPAN_KINDS


def drop_infra(records: list[dict]) -> list[dict]:
    """Drop records whose output matches an InfraFailure signature.

    Reuses ``runner._classify_infra`` / ``runner.INFRA_PATTERNS``. Records with
    a missing output value are also dropped: a trace that crashed before setting
    output never meaningfully executed and must not become a task.
    """
    kept = []
    for rec in records:
        out = get_output_value(rec)
        if out is None:
            continue  # crashed before emitting output -> infra, not a task
        text = out if isinstance(out, str) else json.dumps(out)
        if runner._classify_infra(text) is not None:
            continue
        kept.append(rec)
    return kept


# Secret / PII redaction. Order matters: redact specific token shapes before the
# generic URL/email passes so we don't leak fragments.
_SCRUB_RULES = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"sk_live_[A-Za-z0-9]{8,}"), "[REDACTED_SECRET_KEY]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"gh[oprsu]_[A-Za-z0-9]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer [REDACTED_TOKEN]"),
    # basic-auth creds embedded in a URL: scheme://user:pass@host
    (re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED_CREDS]@"),
    # email addresses
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    # internal URLs (private/corp hosts)
    (re.compile(r"(?i)https?://[^\s/]*(?:localhost|127\.0\.0\.1|\.internal|\.corp|\.local)\b[^\s\"']*"),
     "[REDACTED_INTERNAL_URL]"),
]


def scrub_secrets(text):
    """Redact secrets / PII from a string (or any JSON-serialisable value).

    Returns a string for string input; for dict/list input it scrubs the JSON
    serialisation and returns the re-parsed structure so callers can write
    structured payloads safely.
    """
    if text is None:
        return text
    if isinstance(text, (dict, list)):
        scrubbed = scrub_secrets(json.dumps(text))
        try:
            return json.loads(scrubbed)
        except (json.JSONDecodeError, ValueError):
            return scrubbed
    if not isinstance(text, str):
        text = str(text)
    for pat, repl in _SCRUB_RULES:
        text = pat.sub(repl, text)
    return text


def map_input(agent: str, input_value) -> dict:
    """Map a root span's input.value to a hermetic input ``{filename, content}``.

    input.value holds only references (repo / pr_number / log path /
    deployment_url), never the raw payload bytes the runner needs. We therefore
    return the hermetic filename plus a stub marked NEEDS_HYDRATION carrying the
    references, rather than pretending the diff/log/commits are present.

    Returns a dict with at least ``filename`` and ``content``. ``skip`` is set
    (with ``reason``) for agents whose hermetic input cannot be reconstructed.
    """
    refs = _loads_maybe(input_value) or {}
    filename = HERMETIC_INPUT.get(agent)

    if agent == "contract-test":
        # mutation.patch is essentially never reconstructable from a trace.
        return {
            "filename": filename,
            "content": None,
            "skip": True,
            "reason": "contract-test mutation.patch is not present in the trace",
            "references": refs,
        }

    if agent in ("code-review", "security-review"):
        content = (
            f"# {NEEDS_HYDRATION}: diff.patch is not in the trace input.value.\n"
            f"# Reconstruct from PR {refs.get('repo', '?')}"
            f"#{refs.get('pr_number', '?')} (git fetch the PR diff at the reviewed SHA).\n"
        )
        return {"filename": filename, "content": content, "references": refs}

    if agent == "rca":
        content = (
            f"{NEEDS_HYDRATION}: app.log content is not in the trace input.value.\n"
            f"Hydrate from log_file={refs.get('log_file', '?')} for repo "
            f"{refs.get('repo', '?')}.\n"
        )
        return {"filename": filename, "content": content, "references": refs}

    if agent == "release-notes":
        # runner requires the "commit_messages" key; it is NOT in input.value.
        stub = {
            "_note": f"{NEEDS_HYDRATION}: commit_messages not in trace; fill from the PR/release.",
            "repo": refs.get("repo"),
            "pr_number": refs.get("pr_number"),
            "release_tag": refs.get("release_tag"),
            "commit_messages": [],
        }
        return {"filename": filename, "content": json.dumps(stub, indent=2), "references": refs}

    # unknown agent: best-effort stub
    return {
        "filename": filename or "input.txt",
        "content": f"{NEEDS_HYDRATION}: {json.dumps(refs)}",
        "references": refs,
    }


def map_output(agent: str, output_value) -> dict:
    """Map a root span's output.value to a reference_trial dict.

    release-notes output.value is raw markdown text; everything else is JSON.
    """
    trial: dict = {"harvested_output": None}

    if agent == "release-notes":
        # plain text, do NOT json.loads
        notes = output_value if isinstance(output_value, str) else (
            "" if output_value is None else str(output_value)
        )
        trial["harvested_output"] = notes
        trial["notes"] = notes
        return trial

    parsed = _loads_maybe(output_value)
    if parsed is None:
        # not JSON (or absent) — keep raw so the maintainer can inspect it
        trial["harvested_output"] = output_value
        return trial
    trial["harvested_output"] = parsed

    if agent == "code-review":
        verdict = (parsed.get("verdict") or "").upper()
        if verdict:
            trial["verdict"] = verdict
        if "summary" in parsed:
            trial["summary"] = parsed["summary"]
        if "reason" in parsed:
            trial["reason"] = parsed["reason"]
    elif agent == "security-review":
        verdict = (parsed.get("verdict") or "").upper()
        if verdict:
            trial["verdict"] = verdict
        for k in ("findings_kept", "findings_suppressed", "reason"):
            if k in parsed:
                trial[k] = parsed[k]
    elif agent == "rca":
        verdict = parsed.get("verdict")
        if verdict is not None:
            trial["verdict"] = verdict
            trial["incident"] = (verdict == "errors")
        for k in ("errors", "title", "issue_number", "dry_run"):
            if k in parsed:
                trial[k] = parsed[k]
    elif agent == "contract-test":
        for k in ("verdict", "killed", "endpoint"):
            if k in parsed:
                trial[k] = parsed[k]

    return trial


def _short_span_id(rec: dict) -> str:
    span_id = get_span_id(rec)
    if not span_id:
        return "unknown"
    s = str(span_id).replace("0x", "").replace("-", "")
    return s[:12] if s else "unknown"


def _sha_from_metadata(meta: dict):
    for key in ("commit_sha", "sha", "head_sha", "diff_sha"):
        val = meta.get(key)
        if val:
            return val
    return None


def build_task(agent: str, rec: dict, suite: str, window: dict) -> dict:
    """Build a task.json dict from a root span record.

    Carries the contamination-guard ``source_window`` and a placeholder
    ``label`` the maintainer fills in from the Arize human annotation.
    """
    short = _short_span_id(rec)
    span_id = get_span_id(rec)
    trace_id = get_trace_id(rec)
    meta = scrub_secrets(get_metadata(rec)) or {}
    model_id = window.get("model_id") or f"talos-{agent}"

    task = {
        "id": f"{agent}-arize-{short}",
        "agent": agent,
        "suite": suite,
        "track": "harvested (arize)",
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": f"arize:{model_id}/trace:{trace_id}/span:{span_id}",
        "harvested_from": "arize",
        "source_window": {"start": window.get("start"), "end": window.get("end")},
        "label": {
            "category": "NEEDS_LABEL",
            "expected_verdict": "NEEDS_LABEL",
            "_note": "fill from Arize annotation",
        },
        "reference_trial": map_output(agent, get_output_value(rec)),
    }

    if agent == "code-review":
        sha = _sha_from_metadata(meta) or NEEDS_SHA
        task["diff_sha"] = sha
        task["_snapshot_todo"] = (
            f"freeze source/ via evals/scripts/capture_snapshot.sh at SHA {sha}"
        )

    return task


# --------------------------------------------------------------------------- #
# thin IO layer (DataFrame <-> records, lazy arize/pandas imports)
# --------------------------------------------------------------------------- #
def _df_to_records(df) -> list[dict]:
    """Convert a pandas DataFrame to plain list-of-dict records."""
    return df.to_dict("records")


def load_records_from_file(path: str) -> list[dict]:
    """Load previously exported traces (parquet/json/csv) without arize.

    JSON loads with stdlib; parquet/csv require pandas (lazy import).
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".json", ".jsonl"):
        text = p.read_text(encoding="utf-8")
        if suffix == ".jsonl":
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        data = json.loads(text)
        if isinstance(data, dict) and "records" in data:
            return data["records"]
        if isinstance(data, list):
            return data
        raise ValueError(f"unsupported JSON shape in {path}: expected list or {{'records': [...]}}")
    # parquet / csv -> pandas
    try:
        import pandas as pd  # lazy: offline JSON path needs no pandas
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            f"reading {suffix} needs pandas; install evals/scripts/requirements-harvest.txt"
        ) from exc
    if suffix == ".parquet":
        df = pd.read_parquet(p)
    elif suffix == ".csv":
        df = pd.read_csv(p)
    else:
        raise ValueError(f"unsupported --from-file extension: {suffix}")
    return _df_to_records(df)


def export_records_from_arize(space_id, model_id, start, end) -> list[dict]:
    """Live export from Arize. Imports arize/pandas lazily (network call)."""
    try:
        from arize.exporter import ArizeExportClient
        from arize.utils.types import Environments
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "live export needs the 'arize' package; install "
            "evals/scripts/requirements-harvest.txt (only live export needs it)."
        ) from exc

    client = ArizeExportClient()
    df = client.export_model_to_df(
        space_id=space_id,
        model_id=model_id,
        environment=Environments.TRACING,
        start_time=_parse_iso(start),
        end_time=_parse_iso(end),
        columns=EXPORT_COLUMNS,
    )
    return _df_to_records(df)


def _parse_iso(value):
    """Parse an ISO8601 string to a tz-aware datetime (lenient)."""
    if value is None:
        return None
    s = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.strptime(s[:10], "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------------------------------------------------------- #
# harvest orchestration
# --------------------------------------------------------------------------- #
def dedupe_by_trace(records: list[dict], agent: str) -> list[dict]:
    """Keep one root span per trace id."""
    seen = set()
    out = []
    for rec in records:
        if not is_root_span(rec, agent):
            continue
        tid = get_trace_id(rec) or get_span_id(rec)
        if tid in seen:
            continue
        seen.add(tid)
        out.append(rec)
    return out


def write_task(agent: str, rec: dict, task: dict, input_map: dict, out_dir: Path,
               dry_run: bool) -> tuple[str, str]:
    """Write a task dir. Returns (status, message). Never overwrites."""
    task_dir = out_dir / agent / task["id"]
    if task_dir.exists():
        return ("skip", f"exists, not overwriting: {task_dir}")

    if dry_run:
        return ("dry-run", f"would write {task_dir} ({input_map.get('filename')})")

    task_dir.mkdir(parents=True, exist_ok=False)

    # scrub the whole task payload (metadata/output may carry secrets)
    safe_task = scrub_secrets(task)
    (task_dir / "task.json").write_text(
        json.dumps(safe_task, indent=2) + "\n", encoding="utf-8"
    )

    filename = input_map.get("filename")
    content = input_map.get("content")
    if filename and content is not None:
        safe_content = scrub_secrets(content)
        if not isinstance(safe_content, str):
            safe_content = json.dumps(safe_content, indent=2)
        (task_dir / filename).write_text(safe_content, encoding="utf-8")

    return ("written", str(task_dir))


def harvest(records: list[dict], agent: str, suite: str, window: dict,
            out_dir: Path, limit: int | None, dry_run: bool) -> list[dict]:
    """Run the full §3.5 pipeline on already-loaded records. Returns a report."""
    report = []
    roots = dedupe_by_trace(records, agent)
    clean = drop_infra(roots)
    dropped_infra = len(roots) - len(clean)
    if limit:
        clean = clean[:limit]

    for rec in clean:
        input_map = map_input(agent, get_input_value(rec))
        if input_map.get("skip"):
            report.append({
                "id": f"{agent}-arize-{_short_span_id(rec)}",
                "status": "skip",
                "message": input_map.get("reason", "input not reconstructable"),
            })
            continue
        task = build_task(agent, rec, suite, window)
        status, message = write_task(agent, rec, task, input_map, out_dir, dry_run)
        report.append({"id": task["id"], "status": status, "message": message})

    report.append({
        "id": "_summary",
        "status": "info",
        "message": (
            f"root spans={len(roots)} dropped_infra={dropped_infra} "
            f"candidates={len(clean)} processed={len(report)}"
        ),
    })
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Harvest Arize AX traces into eval dataset tasks (EVAL_STRATEGY.md §3.5).",
    )
    p.add_argument("--agent", required=True, choices=REPLAYABLE_AGENTS,
                   help="agent whose root spans to harvest")
    p.add_argument("--space-id", help="Arize space id (required for live export)")
    p.add_argument("--model-id", help="Arize model id (default: talos-<agent>)")
    p.add_argument("--start", help="window start (ISO8601)")
    p.add_argument("--end", help="window end (ISO8601)")
    p.add_argument("--from-file", dest="from_file",
                   help="offline: load exported parquet/json/jsonl/csv instead of calling Arize")
    p.add_argument("--out", default=str(DEFAULT_OUT),
                   help="dataset root to write into (default: evals/datasets)")
    p.add_argument("--suite", default="capability", choices=["capability", "regression"],
                   help="suite to admit harvested tasks to (default: capability)")
    p.add_argument("--limit", type=int, help="cap the number of tasks harvested")
    p.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    model_id = args.model_id or f"talos-{args.agent}"

    if args.from_file:
        records = load_records_from_file(args.from_file)
    else:
        if not args.space_id or not args.start or not args.end:
            print("error: live export needs --space-id, --start and --end "
                  "(or use --from-file for offline harvesting)", file=sys.stderr)
            return 2
        records = export_records_from_arize(args.space_id, model_id, args.start, args.end)

    window = {"start": args.start, "end": args.end, "model_id": model_id}
    report = harvest(
        records=records,
        agent=args.agent,
        suite=args.suite,
        window=window,
        out_dir=Path(args.out),
        limit=args.limit,
        dry_run=args.dry_run,
    )

    for row in report:
        print(f"[{row['status']}] {row['id']}: {row['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
