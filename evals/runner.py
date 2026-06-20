"""Talos eval runner: replays agents against harvested dataset tasks.

Execution model
---------------
Each trial runs one agent container (or local process in --mode direct)
against the hermetic inputs stored in the task directory, with DRY_RUN=1 so
no comments/issues/releases are ever created. The agent's exit code and the
artifact it emits between ARTIFACT_BEGIN/ARTIFACT_END markers are the trial
outcome; graders.py turns that into pass/fail against the task label.

Infra vs agent failure
----------------------
Per the harness-failure log in docs/EVAL_BACKLOG.md, a trial that never
meaningfully executed (docker build/pull failure, upstream 5xx, timeout)
must NOT count against the agent's pass rate. Those trials raise
InfraFailure, which the pytest layer converts to a skip.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASETS = Path(__file__).resolve().parent / "datasets"

ARTIFACT_BEGIN = "===TALOS_EVAL_ARTIFACT_BEGIN==="
ARTIFACT_END = "===TALOS_EVAL_ARTIFACT_END==="

# stderr/stdout signatures that mean the trial never meaningfully executed.
INFRA_PATTERNS = [
    r"HTTP 5\d\d for ",                      # GitHub / OpenRouter server errors
    r"InternalServerError|APIConnectionError|APITimeoutError",
    r"failed to resolve source metadata",     # docker pull flake
    r"i/o timeout",
    r"TLS handshake timeout",
    r"Cannot connect to the Docker daemon",
    r"connection reset by peer",
    r"could not determine a code-review verdict",  # Pi never emitted a verdict
]


class InfraFailure(Exception):
    """The trial failed for harness/infra reasons; do not grade it."""


@dataclass
class Trial:
    exit_code: int
    stdout: str
    stderr: str
    artifact: dict | None
    duration_s: float


@dataclass
class Task:
    task_id: str
    agent: str
    suite: str
    path: Path
    data: dict = field(repr=False, default_factory=dict)

    @property
    def label(self) -> dict:
        return self.data.get("label", {})


def discover_tasks(agents: list[str] | None = None, suites: list[str] | None = None) -> list[Task]:
    tasks = []
    for task_file in sorted(DATASETS.glob("*/*/task.json")):
        data = json.loads(task_file.read_text(encoding="utf-8"))
        task = Task(
            task_id=data.get("id", task_file.parent.name),
            agent=data.get("agent", task_file.parent.parent.name),
            suite=data.get("suite", "regression"),
            path=task_file.parent,
            data=data,
        )
        if agents and task.agent not in agents:
            continue
        if suites and task.suite not in suites:
            continue
        tasks.append(task)
    return tasks


def _classify_infra(output: str) -> str | None:
    for pat in INFRA_PATTERNS:
        m = re.search(pat, output)
        if m:
            return m.group(0)
    return None


def _extract_artifact(stdout: str) -> dict | None:
    begin = stdout.rfind(ARTIFACT_BEGIN)
    end = stdout.rfind(ARTIFACT_END)
    if begin < 0 or end < 0 or end < begin:
        return None
    payload = stdout[begin + len(ARTIFACT_BEGIN):end].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def build_image(agent: str) -> str:
    """docker build the agent; build/pull failures are infra, not agent, failures."""
    tag = f"talos-eval/{agent}"
    proc = subprocess.run(
        ["docker", "build", "-q", "-t", tag, str(REPO_ROOT / "agents" / agent)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise InfraFailure(f"docker build failed for {agent}: {proc.stderr[-2000:]}")
    return tag


def run_agent(
    agent: str,
    env: dict[str, str],
    mounts: dict[str, str] | None = None,
    mode: str = "docker",
    timeout_s: int = 300,
    mounts_rw: dict[str, str] | None = None,
) -> Trial:
    """Run one agent trial.

    mounts maps host path -> container path (read-only). mounts_rw is the same
    but writable — used for a Pi review workspace, where the agent may write
    scratch files into the checkout it reviews (the copy is ephemeral).
    """
    if mode == "docker":
        cmd = ["docker", "run", "--rm", "--add-host", "host.docker.internal:host-gateway"]
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
        for host, container in (mounts or {}).items():
            cmd += ["-v", f"{host}:{container}:ro"]
        for host, container in (mounts_rw or {}).items():
            cmd += ["-v", f"{host}:{container}"]
        cmd.append(build_image(agent))
    else:  # direct: run agent.py with the host python (deps must be installed)
        import os

        cmd = [sys.executable, str(REPO_ROOT / "agents" / agent / "agent.py")]
        env = {**os.environ, **env}
        # In direct mode container paths in env must already be host paths;
        # callers handle this by passing host paths when mode != docker.

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env if mode == "direct" else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise InfraFailure(f"trial timed out after {timeout_s}s") from exc

    combined = (proc.stdout or "") + (proc.stderr or "")
    infra = _classify_infra(combined)
    if infra and proc.returncode not in (0, 1):
        # Non-contract exit code plus an infra signature: never graded.
        raise InfraFailure(f"infra signature: {infra}")

    return Trial(
        exit_code=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        artifact=_extract_artifact(proc.stdout or ""),
        duration_s=time.monotonic() - start,
    )


# ---------------------------------------------------------------------------
# Per-agent replay wiring


def replay_review_agent(agent: str, task: Task, *, mode: str, model: str | None, timeout_s: int) -> Trial:
    """security-review: hermetic diff from the task dir (no workspace needed)."""
    diff_file = task.path / "diff.patch"
    if not diff_file.exists():
        raise InfraFailure(f"{task.task_id}: no diff.patch in task dir (not hermetic yet)")
    env = {
        "DRY_RUN": "1",
        "OPENROUTER_API_KEY": _require_env("OPENROUTER_API_KEY"),
        "GITHUB_REPOSITORY": task.data.get("source", ""),
        "PR_NUMBER": task.task_id,
    }
    if model:
        env["MODEL"] = model
    if mode == "docker":
        env["DIFF_FILE"] = "/task/diff.patch"
        mounts = {str(task.path): "/task"}
    else:
        env["DIFF_FILE"] = str(diff_file)
        mounts = None
    return run_agent(agent, env, mounts, mode=mode, timeout_s=timeout_s)


def replay_code_review(task: Task, *, mode: str, model: str | None, timeout_s: int) -> Trial:
    """code-review (Pi): give the agent the diff AND the code it touches.

    The reviewer reads full files, so the replay must reconstruct the reviewed
    state, not just hand over a diff. Copy todo-api, apply diff.patch so the
    workspace is the PR-head (post-change) tree, then point Pi at it. The diff
    is also passed via DIFF_FILE so the agent knows what changed.
    """
    diff_file = task.path / "diff.patch"
    if not diff_file.exists():
        raise InfraFailure(f"{task.task_id}: no diff.patch in task dir (not hermetic yet)")

    with tempfile.TemporaryDirectory(prefix="talos-eval-cr-") as tmp:
        shutil.copytree(REPO_ROOT / "todo-api", Path(tmp) / "todo-api")
        # Patches are repo-rooted (a/todo-api/...); apply from tmp where the
        # copied tree sits at the same todo-api/ prefix to reach PR-head state.
        apply = subprocess.run(
            ["git", "apply", str(diff_file)],
            cwd=tmp,
            capture_output=True,
            text=True,
        )
        if apply.returncode != 0:
            # The stored diff no longer applies to the current todo-api (the
            # base drifted). We can't reconstruct the reviewed post-change tree,
            # and reviewing against the unpatched tree mis-grades real-defect
            # tasks (the defect lives only in the diff, so the reviewer can't
            # see it) — proven on cr-004. Skip honestly rather than guess; the
            # task needs re-harvesting against current main or a pinned base SHA.
            raise InfraFailure(
                f"{task.task_id}: diff.patch no longer applies to current todo-api "
                f"(stale fixture — re-harvest needed): {apply.stderr.strip()[:300]}"
            )

        env = {
            "DRY_RUN": "1",
            "OPENROUTER_API_KEY": _require_env("OPENROUTER_API_KEY"),
            "GITHUB_REPOSITORY": task.data.get("source", ""),
            "PR_NUMBER": task.task_id,
        }
        if model:
            env["MODEL"] = model
        if mode == "docker":
            env["WORKSPACE"] = "/workspace"
            env["DIFF_FILE"] = "/task/diff.patch"
            mounts = {str(task.path): "/task"}
            mounts_rw = {tmp: "/workspace"}
        else:
            env["WORKSPACE"] = tmp
            env["DIFF_FILE"] = str(diff_file)
            mounts = None
            mounts_rw = None
        return run_agent("code-review", env, mounts, mode=mode, timeout_s=timeout_s, mounts_rw=mounts_rw)


def replay_rca(task: Task, *, mode: str, model: str | None, timeout_s: int) -> Trial:
    log_file = task.path / "app.log"
    env = {
        "DRY_RUN": "1",
        "OPENROUTER_API_KEY": _require_env("OPENROUTER_API_KEY"),
    }
    if model:
        env["MODEL"] = model
    source_dir = REPO_ROOT / "todo-api"
    if mode == "docker":
        env["LOG_FILE"] = "/logs/app.log"
        env["SOURCE_DIR"] = "/workspace"
        mounts = {str(source_dir): "/workspace"}
        if log_file.exists():
            mounts[str(task.path)] = "/logs"
    else:
        env["LOG_FILE"] = str(log_file)
        env["SOURCE_DIR"] = str(source_dir)
        mounts = None
    return run_agent("rca", env, mounts, mode=mode, timeout_s=timeout_s)


def replay_release_notes(task: Task, *, mode: str, model: str | None, timeout_s: int) -> Trial:
    input_file = task.path / "input.json"
    if not input_file.exists():
        raise InfraFailure(f"{task.task_id}: no input.json in task dir")
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    if "commit_messages" not in payload:
        raise InfraFailure(f"{task.task_id}: input.json lacks commit_messages (not hermetic yet)")
    env = {
        "DRY_RUN": "1",
        "OPENROUTER_API_KEY": _require_env("OPENROUTER_API_KEY"),
    }
    if model:
        env["MODEL"] = model
    if mode == "docker":
        env["INPUT_FILE"] = "/task/input.json"
        mounts = {str(task.path): "/task"}
    else:
        env["INPUT_FILE"] = str(input_file)
        mounts = None
    return run_agent("release-notes", env, mounts, mode=mode, timeout_s=timeout_s)


def replay_contract_test(task: Task, *, mode: str, model: str | None, timeout_s: int) -> Trial:
    """Mutation-seed replay: copy todo-api, apply mutation.patch (if any),
    serve it locally, and point the agent at it."""
    replay = task.data.get("replay", "mutation" if (task.path / "mutation.patch").exists() else "none")
    if replay == "none":
        raise InfraFailure(f"{task.task_id}: historical trial, not replayable (no mutation.patch)")

    with tempfile.TemporaryDirectory(prefix="talos-eval-ct-") as tmp:
        api_dir = Path(tmp) / "todo-api"
        shutil.copytree(REPO_ROOT / "todo-api", api_dir)
        patch = task.path / "mutation.patch"
        if patch.exists():
            # Patches are repo-rooted (a/todo-api/...), so apply from tmp where
            # the copied tree sits at the same todo-api/ prefix.
            apply = subprocess.run(
                ["git", "apply", str(patch)],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
            if apply.returncode != 0:
                # A stale mutation seed (drifted handler) is a harness problem.
                raise InfraFailure(f"{task.task_id}: mutation.patch no longer applies: {apply.stderr}")

        port = _free_port()
        server = subprocess.Popen(
            ["node", "dev-server.js"],
            cwd=api_dir,
            env={"PORT": str(port), "PATH": _path_env()},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_healthy(f"http://localhost:{port}/api/healthz")
            host = "host.docker.internal" if mode == "docker" else "localhost"
            env = {
                "DRY_RUN": "1",
                "OPENROUTER_API_KEY": _require_env("OPENROUTER_API_KEY"),
                "DEPLOYMENT_URL": f"http://{host}:{port}",
            }
            if model:
                env["MODEL"] = model
            if mode == "docker":
                env["SPEC_FILE"] = "/workspace/openapi.yaml"
                mounts = {str(api_dir): "/workspace"}
            else:
                env["SPEC_FILE"] = str(api_dir / "openapi.yaml")
                mounts = None
            return run_agent("contract-test", env, mounts, mode=mode, timeout_s=timeout_s)
        finally:
            server.terminate()
            server.wait(timeout=10)


REPLAYERS = {
    "code-review": replay_code_review,
    "security-review": lambda task, **kw: replay_review_agent("security-review", task, **kw),
    "rca": replay_rca,
    "release-notes": replay_release_notes,
    "contract-test": replay_contract_test,
}


def replay(task: Task, *, mode: str = "docker", model: str | None = None, timeout_s: int = 300) -> Trial:
    replayer = REPLAYERS.get(task.agent)
    if replayer is None:
        raise InfraFailure(f"no replayer for agent {task.agent!r} (talos-bench runs in the nightly harness)")
    return replayer(task, mode=mode, model=model, timeout_s=timeout_s)


# ---------------------------------------------------------------------------
# helpers


def _require_env(name: str) -> str:
    import os

    value = os.environ.get(name, "")
    if not value:
        raise InfraFailure(f"required env var {name} is not set")
    return value


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _path_env() -> str:
    import os

    return os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")


def _wait_healthy(url: str, attempts: int = 30) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            time.sleep(0.5)
    raise InfraFailure(f"todo-api never became healthy at {url}")
