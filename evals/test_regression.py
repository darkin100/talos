"""One parametrized test per harvested task: replay the agent, grade the outcome.

Failure semantics (per docs/EVAL_BACKLOG.md "Harness-failure log"):
- grader fail   -> test FAILS (agent regression)
- InfraFailure  -> test SKIPS with the reason (never counted against the agent)
- trials > 1    -> task passes on strict majority of *graded* trials
"""

from __future__ import annotations

import pytest

from graders import grade
from runner import InfraFailure, replay


def test_task(task, eval_options, record_result):
    trials = eval_options["trials"]
    outcomes = []  # (passed, reason)
    infra_reasons = []

    for n in range(trials):
        try:
            trial = replay(
                task,
                mode=eval_options["mode"],
                model=eval_options["model"],
                timeout_s=eval_options["timeout_s"],
            )
        except InfraFailure as exc:
            infra_reasons.append(str(exc))
            continue
        outcomes.append(grade(task, trial))

    if not outcomes:
        record_result(
            {"agent": task.agent, "task": task.task_id, "category": task.label.get("category", ""),
             "outcome": "infra", "detail": "; ".join(infra_reasons)}
        )
        pytest.skip(f"all {trials} trial(s) hit infra failures: {infra_reasons}")

    passed = sum(1 for ok, _ in outcomes if ok)
    majority = passed * 2 > len(outcomes)
    detail = " | ".join(
        f"trial {i + 1}: {'pass' if ok else 'FAIL'} — {reason}" for i, (ok, reason) in enumerate(outcomes)
    )
    record_result(
        {
            "agent": task.agent,
            "task": task.task_id,
            "category": task.label.get("category", ""),
            "outcome": "pass" if majority else "fail",
            "pass_rate": f"{passed}/{len(outcomes)}",
            "infra_trials": len(infra_reasons),
            "detail": detail,
        }
    )
    assert majority, f"{task.agent}/{task.task_id}: {detail}"
