"""No-network unit tests for the Arize harvester (EVAL_STRATEGY.md §3.5).

These tests run with neither the ``arize`` package, pandas, docker, nor any
network access. They exercise the pure core functions on synthetic records.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# make evals/scripts importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

import harvest_arize as h


def _root_record(agent="code-review", kind="AGENT", output=None, metadata=None):
    return {
        "context.span_id": "0xabc123def456789",
        "context.trace_id": "0xtrace0001",
        "name": f"talos.{agent}.run",
        "attributes.openinference.span.kind": kind,
        "attributes.input.value": json.dumps({"repo": "darkin100/talos", "pr_number": 51}),
        "attributes.output.value": output if output is not None
        else json.dumps({"verdict": "pass", "summary": "looks fine"}),
        "attributes.metadata": json.dumps(metadata or {"repo": "darkin100/talos", "pr_number": 51}),
    }


# --------------------------------------------------------------------------- #
# is_root_span
# --------------------------------------------------------------------------- #
def test_is_root_span_keeps_agent_kind():
    rec = _root_record(agent="code-review", kind="AGENT")
    assert h.is_root_span(rec, "code-review") is True


def test_is_root_span_keeps_chain_kind():
    # real code-review traces emit CHAIN, not AGENT
    rec = _root_record(agent="code-review", kind="CHAIN")
    assert h.is_root_span(rec, "code-review") is True


def test_is_root_span_rejects_child_span():
    rec = {
        "context.span_id": "0xchild",
        "name": "ChatCompletion",
        "attributes.openinference.span.kind": "LLM",
    }
    assert h.is_root_span(rec, "code-review") is False


def test_is_root_span_rejects_wrong_agent_name():
    rec = _root_record(agent="rca", kind="CHAIN")
    assert h.is_root_span(rec, "code-review") is False


def test_is_root_span_rejects_bad_kind():
    rec = _root_record(agent="code-review", kind="TOOL")
    assert h.is_root_span(rec, "code-review") is False


# --------------------------------------------------------------------------- #
# drop_infra
# --------------------------------------------------------------------------- #
def test_drop_infra_removes_infra_signature():
    infra = _root_record(
        output=json.dumps({"error": "could not determine a code-review verdict"})
    )
    clean = _root_record(output=json.dumps({"verdict": "pass", "summary": "ok"}))
    kept = h.drop_infra([infra, clean])
    assert len(kept) == 1
    assert kept[0] is clean


def test_drop_infra_drops_missing_output():
    rec = _root_record()
    rec["attributes.output.value"] = None
    assert h.drop_infra([rec]) == []


# --------------------------------------------------------------------------- #
# scrub_secrets
# --------------------------------------------------------------------------- #
def test_scrub_secrets_redacts_token_and_email():
    text = "key sk-ABCDEF1234567890 from dev@example.com please"
    out = h.scrub_secrets(text)
    assert "sk-ABCDEF1234567890" not in out
    assert "dev@example.com" not in out
    assert "REDACTED" in out


def test_scrub_secrets_redacts_bearer_and_basic_auth():
    text = "Authorization: Bearer abcdef123456 https://user:pass@host.example/x"
    out = h.scrub_secrets(text)
    assert "abcdef123456" not in out
    assert "user:pass@" not in out


def test_scrub_secrets_handles_dict():
    out = h.scrub_secrets({"token": "ghp_" + "a" * 30, "ok": "fine"})
    assert "ghp_" not in json.dumps(out)
    assert out["ok"] == "fine"


# --------------------------------------------------------------------------- #
# map_input / map_output
# --------------------------------------------------------------------------- #
def test_map_input_code_review_stub():
    m = h.map_input("code-review", json.dumps({"repo": "r", "pr_number": 7}))
    assert m["filename"] == "diff.patch"
    assert h.NEEDS_HYDRATION in m["content"]


def test_map_input_contract_test_skips():
    m = h.map_input("contract-test", json.dumps({"deployment_url": "http://x"}))
    assert m["skip"] is True
    assert "mutation.patch" in m["reason"]


def test_map_output_code_review_uppercases_verdict():
    t = h.map_output("code-review", json.dumps({"verdict": "pass", "summary": "ok"}))
    assert t["verdict"] == "PASS"


def test_map_output_release_notes_is_plain_text():
    t = h.map_output("release-notes", "## Notes\n- did a thing")
    assert t["notes"] == "## Notes\n- did a thing"


def test_map_output_rca_sets_incident_flag():
    t = h.map_output("rca", json.dumps({"verdict": "errors", "errors": 3, "title": "boom"}))
    assert t["incident"] is True
    assert t["errors"] == 3


# --------------------------------------------------------------------------- #
# build_task
# --------------------------------------------------------------------------- #
def test_build_task_capability_window_and_placeholder():
    rec = _root_record(agent="code-review", kind="CHAIN")
    window = {"start": "2026-06-01", "end": "2026-06-08", "model_id": "talos-code-review"}
    task = h.build_task("code-review", rec, "capability", window)

    assert task["suite"] == "capability"
    assert task["agent"] == "code-review"
    assert task["harvested_from"] == "arize"
    assert task["source_window"] == {"start": "2026-06-01", "end": "2026-06-08"}
    assert task["label"]["category"] == "NEEDS_LABEL"
    assert task["label"]["expected_verdict"] == "NEEDS_LABEL"
    assert task["id"].startswith("code-review-arize-")
    assert "arize:" in task["source"]


def test_build_task_code_review_needs_sha_fallback():
    # code-review metadata carries no sha
    rec = _root_record(agent="code-review", kind="CHAIN",
                       metadata={"repo": "r", "pr_number": 7, "model": "m"})
    task = h.build_task("code-review", rec, "capability",
                        {"start": "a", "end": "b", "model_id": "talos-code-review"})
    assert task["diff_sha"] == h.NEEDS_SHA
    assert "capture_snapshot.sh" in task["_snapshot_todo"]


def test_build_task_code_review_uses_metadata_sha():
    rec = _root_record(agent="code-review", kind="CHAIN",
                       metadata={"repo": "r", "pr_number": 7, "commit_sha": "deadbeef"})
    task = h.build_task("code-review", rec, "capability",
                        {"start": "a", "end": "b", "model_id": "talos-code-review"})
    assert task["diff_sha"] == "deadbeef"
