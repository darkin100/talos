"""pytest wiring for the Talos eval suites.

Usage:
    pytest evals --agent code-review            # one agent's regression suite
    pytest evals --agent rca --trials 3         # majority-of-3 per task
    pytest evals --suite capability             # the nightly hill
    pytest evals --mode direct                  # skip docker (host python deps)

Results are also written to evals/.results/results.json for the CI comment
(rendered by evals/report.py).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runner import discover_tasks  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / ".results"


def pytest_addoption(parser):
    group = parser.getgroup("talos-evals")
    group.addoption("--agent", action="append", default=None,
                    help="agent suite(s) to run (repeatable); default: all replayable agents")
    group.addoption("--suite", action="store", default="regression",
                    help="regression | capability | all (default: regression)")
    group.addoption("--trials", action="store", type=int, default=1,
                    help="trials per task; task passes on strict majority (default: 1)")
    group.addoption("--mode", action="store", default="docker",
                    help="docker (default, exercises the built artifact) | direct (host python)")
    group.addoption("--eval-model", action="store", default=None,
                    help="override MODEL for every replayed agent")
    group.addoption("--task-timeout", action="store", type=int, default=300,
                    help="seconds per trial before it is classed as an infra failure")


def _load_dotenv() -> None:
    """Mirror scripts/local-demo.sh: repo-root .env fills in missing env vars."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        os.environ.setdefault(key.strip(), value)


def pytest_configure(config):
    _load_dotenv()
    RESULTS_DIR.mkdir(exist_ok=True)
    config._talos_results = []

    # Live grouped dashboard for interactive runs; no-ops (default dots) in CI.
    from _progress import TalosProgress

    config.pluginmanager.register(TalosProgress(config), "talos-progress")


def pytest_generate_tests(metafunc):
    if "task" not in metafunc.fixturenames:
        return
    agents = metafunc.config.getoption("--agent")
    suite = metafunc.config.getoption("--suite")
    suites = None if suite == "all" else [suite]
    tasks = discover_tasks(agents=agents, suites=suites)
    metafunc.parametrize(
        "task",
        tasks,
        ids=[f"{t.agent}/{t.task_id}" for t in tasks],
    )


@pytest.fixture
def eval_options(request):
    return {
        "mode": request.config.getoption("--mode"),
        "trials": request.config.getoption("--trials"),
        "model": request.config.getoption("--eval-model"),
        "timeout_s": request.config.getoption("--task-timeout"),
    }


@pytest.fixture
def record_result(request):
    def _record(entry: dict):
        request.config._talos_results.append(entry)

    return _record


def pytest_sessionfinish(session, exitstatus):
    results = getattr(session.config, "_talos_results", [])
    if results:
        out = RESULTS_DIR / "results.json"
        out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
