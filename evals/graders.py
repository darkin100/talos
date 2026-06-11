"""Code-based graders: turn a Trial + task label into a pass/fail + reason.

These are the deterministic gates from EVAL_STRATEGY.md §2 ("code-based
grader" rows). Model-based graders are deliberately absent — they are signal,
not gate, and land with the Phoenix experiment layer.

Every grader returns (passed: bool, reason: str). Reasons surface in the
pytest failure message and the CI comment, so they should say what the agent
did vs what the label expected.
"""

from __future__ import annotations

import re

from runner import Task, Trial

# Categories where the correct review outcome is "do not block".
CLEAN_CATEGORIES = {"none", "style_only"}


def grade_code_review(task: Task, trial: Trial) -> tuple[bool, str]:
    """Verdict match: exit code 0 ↔ the label says the PR is clean."""
    category = task.label.get("category", "")
    expected_exit = 0 if category in CLEAN_CATEGORIES else 1
    actual = trial.exit_code
    if actual == expected_exit:
        return True, f"verdict matches label category {category!r} (exit {actual})"
    direction = "false positive: flagged a clean PR" if expected_exit == 0 else "miss: passed a defective PR"
    return False, f"{direction} (category {category!r}, expected exit {expected_exit}, got {actual})"


def grade_security_review(task: Task, trial: Trial) -> tuple[bool, str]:
    """Verdict match against expected_verdict; CWE coverage reported as info."""
    expected = task.label.get("expected_verdict", "PASS").upper()
    expected_exit = 0 if expected == "PASS" else 1
    if trial.exit_code != expected_exit:
        direction = (
            "false positive: blocked a clean PR"
            if expected_exit == 0
            else "miss: passed a PR with a planted/real vulnerability"
        )
        return False, f"{direction} (expected {expected}, exit {trial.exit_code})"

    # Info-only CWE recall: did any kept finding mention the labelled CWE(s)?
    expected_cwes = {
        m
        for f in task.label.get("findings", [])
        if f.get("real")
        for m in re.findall(r"CWE-\d+", str(f.get("cwe", "")))
    }
    if expected_cwes and trial.artifact:
        seen = " ".join(
            str(f.get("title", "")) + " " + str(f.get("detail", ""))
            for f in trial.artifact.get("findings", [])
        )
        hit = {c for c in expected_cwes if c in seen}
        return True, f"verdict matches ({expected}); CWE mention {len(hit)}/{len(expected_cwes)} (info only)"
    return True, f"verdict matches ({expected})"


def grade_rca(task: Task, trial: Trial) -> tuple[bool, str]:
    """Incident detection match + (for incidents) evidence-token check."""
    expected_incident = bool(task.label.get("incident", False))
    actual_incident = trial.exit_code == 1
    if actual_incident != expected_incident:
        direction = (
            "false positive: raised an incident on clean/known-benign logs"
            if not expected_incident
            else "miss: stayed silent on a real incident"
        )
        return False, f"{direction} (exit {trial.exit_code})"
    if not expected_incident:
        return True, "correctly silent on clean logs"

    # Evidence check: the diagnosis must cite at least one labelled token
    # (file, function, or trigger). Tokens live in label.evidence_tokens;
    # fall back to the cause_file basename so older tasks still grade.
    tokens = task.label.get("evidence_tokens")
    if not tokens:
        cause = str(task.label.get("cause_file", ""))
        tokens = [t for t in re.split(r"[ /():]+", cause) if t.endswith((".js", ".py", ".go"))]
    body = ""
    if trial.artifact:
        body = str(trial.artifact.get("title", "")) + "\n" + str(trial.artifact.get("body", ""))
    if not tokens:
        return True, "incident detected (no evidence tokens labelled)"
    hits = [t for t in tokens if t.lower() in body.lower()]
    if hits:
        return True, f"incident detected, diagnosis cites {hits!r}"
    return False, f"incident detected but diagnosis cites none of {tokens!r}"


def grade_contract_test(task: Task, trial: Trial) -> tuple[bool, str]:
    """Mutation kill: a seeded violation must be caught; clean must pass."""
    expect_violation = bool(task.label.get("violation", False))
    found_violation = trial.exit_code == 1
    if found_violation != expect_violation:
        direction = (
            "false positive: flagged violations on a clean deploy"
            if not expect_violation
            else "mutant survived: seeded contract break not caught"
        )
        return False, f"{direction} (exit {trial.exit_code})"
    if not expect_violation:
        return True, "clean deploy, contract holds"

    expected_endpoint = task.label.get("endpoint", "")
    if expected_endpoint and trial.artifact:
        method, _, path = expected_endpoint.partition(" ")
        for v in trial.artifact.get("violations", []):
            if v.get("method", "").upper() == method.upper() and v.get("path", "") == path:
                return True, f"killed mutant on {expected_endpoint}"
        return False, f"violations found but none on labelled endpoint {expected_endpoint}"
    return True, "violation caught"


WORD_LIMIT = 300
_REF_PATTERN = re.compile(r"#\d+|\b[0-9a-f]{7,40}\b|v\d+")


def grade_release_notes(task: Task, trial: Trial) -> tuple[bool, str]:
    """Hard length rule + reference grounding (every #PR/sha/tag the note
    mentions must appear in the input). Full claim-level grounding is the
    model-based grader's job later."""
    if trial.exit_code != 0:
        return False, f"agent exited {trial.exit_code}"
    notes = (trial.artifact or {}).get("notes", "")
    if not notes:
        return False, "no notes emitted"
    words = len(notes.split())
    if words > WORD_LIMIT:
        return False, f"length {words} words exceeds the {WORD_LIMIT}-word hard rule"

    input_file = task.path / "input.json"
    grounding = input_file.read_text(encoding="utf-8") if input_file.exists() else ""
    ungrounded = [ref for ref in _REF_PATTERN.findall(notes) if ref not in grounding]
    if ungrounded:
        return False, f"ungrounded references {ungrounded!r} (not in input.json)"
    return True, f"{words} words, all references grounded"


GRADERS = {
    "code-review": grade_code_review,
    "security-review": grade_security_review,
    "rca": grade_rca,
    "contract-test": grade_contract_test,
    "release-notes": grade_release_notes,
}


def grade(task: Task, trial: Trial) -> tuple[bool, str]:
    grader = GRADERS.get(task.agent)
    if grader is None:
        return False, f"no grader for agent {task.agent!r}"
    return grader(task, trial)
