"""Unit tests for report.py — the per-PR comment renderer, incl. Δ-vs-base.

Plain pytest, no network/docker/agents. Runs under `pytest evals` (these tests
don't use the parametrized `task` fixture, so they're ordinary unit tests).
"""

from __future__ import annotations

from report import MARKER, _task_delta, render


def _row(agent, task, outcome, pass_rate=None, category="real_defect"):
    r = {"agent": agent, "task": task, "category": category, "outcome": outcome, "detail": "x"}
    if pass_rate is not None:
        r["pass_rate"] = pass_rate
    return r


# --- _task_delta -----------------------------------------------------------

def test_task_delta_regression():
    label, is_reg = _task_delta(_row("cr", "t", "fail", "1/3"), _row("cr", "t", "pass", "3/3"))
    assert is_reg is True and "regressed" in label


def test_task_delta_fixed():
    label, is_reg = _task_delta(_row("cr", "t", "pass", "3/3"), _row("cr", "t", "fail", "0/3"))
    assert is_reg is False and "fixed" in label


def test_task_delta_new():
    label, is_reg = _task_delta(_row("cr", "t", "pass", "3/3"), None)
    assert is_reg is False and "new" in label


def test_task_delta_pass_rate_shift_same_outcome():
    label, is_reg = _task_delta(_row("cr", "t", "pass", "3/3"), _row("cr", "t", "pass", "2/3"))
    assert is_reg is False and label == "2/3→3/3"


def test_task_delta_unchanged():
    label, is_reg = _task_delta(_row("cr", "t", "pass", "3/3"), _row("cr", "t", "pass", "3/3"))
    assert is_reg is False and label == "—"


def test_task_delta_infra_never_regression():
    # cur infra: no agent-quality signal, even though base passed.
    label, is_reg = _task_delta(_row("cr", "t", "infra"), _row("cr", "t", "pass", "3/3"))
    assert is_reg is False
    # base infra: not a regression either.
    _, is_reg2 = _task_delta(_row("cr", "t", "fail", "0/3"), _row("cr", "t", "infra"))
    assert is_reg2 is False


# --- render: no baseline ---------------------------------------------------

def test_render_no_baseline_is_backward_compatible():
    out = render([_row("code-review", "cr-001", "pass", "1/1", category="none")])
    assert out.startswith(MARKER)
    assert "tasks passed (majority pass@k)" in out
    assert "pass@1 (trial-level):" in out
    # No baseline => no Δ view and no "vs base" column.
    assert "vs base" not in out
    assert "regression(s) vs base" not in out
    # 4-column data table (no vs-base column).
    assert "| task | category | outcome | trials (pass@k) | detail |" in out


# --- render: with baseline -------------------------------------------------

def test_render_with_baseline_surfaces_all_deltas():
    cur = [
        _row("code-review", "cr-011", "fail", "1/3"),   # regressed (base pass)
        _row("code-review", "cr-012", "pass", "3/3"),   # fixed (base fail)
        _row("code-review", "cr-013", "pass", "2/3"),   # pass-rate shift (base 3/3)
        _row("code-review", "cr-099", "pass", "3/3"),   # new (absent from base)
    ]
    base = [
        _row("code-review", "cr-011", "pass", "3/3"),
        _row("code-review", "cr-012", "fail", "0/3"),
        _row("code-review", "cr-013", "pass", "3/3"),
    ]
    out = render(cur, baseline=base)

    # Δ banner + regressions callout naming the regressed task only.
    assert "Δ vs the committed ground-truth baseline" in out
    assert "1 regression(s) vs base" in out
    assert "**code-review/cr-011**" in out
    assert "code-review/cr-012" not in out.split("majority pass@k")[0]  # not in callout

    # vs-base column present with the right per-task labels.
    assert "| task | category | outcome | trials (pass@k) | vs base | detail |" in out
    assert "🔻 regressed" in out
    assert "🔺 fixed" in out
    assert "🆕 new" in out
    assert "3/3→2/3" in out

    # Per-agent deltas: common graded tasks = cr-011/012/013 (cr-099 is new).
    # tasks-passed: base 2 (011,013), cur 2 (012,013) -> Δ 0, +1 new.
    assert "Δ +0 vs base (+1 new)" in out
    # pass@1 over common: base (3+0+3)/9=67%, cur (1+3+2)/9=67% -> Δ +0 pp.
    assert "pp vs base" in out


def test_render_no_regressions_shows_clear_banner():
    cur = [_row("rca", "incident-001", "pass", "3/3", category="")]
    base = [_row("rca", "incident-001", "pass", "3/3", category="")]
    out = render(cur, baseline=base)
    assert "✅ No regressions vs base." in out


def test_render_surfaces_baseline_provenance():
    cur = [_row("rca", "incident-001", "pass", "3/3", category="")]
    base = [_row("rca", "incident-001", "pass", "3/3", category="")]
    meta = {"cast_at": "2026-06-22T09:00:00Z", "commit": "abc1234", "suite": "regression", "trials": 3}
    out = render(cur, baseline=base, baseline_meta=meta)
    # Freshness shows in the caption so reviewers can judge a stale baseline.
    assert "cast 2026-06-22T09:00:00Z" in out
    assert "@abc1234" in out
    # Absent meta degrades to the plain ground-truth caption (no provenance).
    assert "cast 2026-06-22T09:00:00Z" not in render(cur, baseline=base)
