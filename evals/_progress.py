"""A live, grouped progress dashboard for the eval suite.

The default pytest dot reporter is a poor fit for this suite: every task is a
slow (~30-60s) docker replay run serially, so the screen sits on a silent `.`
for up to a minute at a time. This plugin replaces that with a `rich.Live`
panel — tasks grouped by agent, an animated spinner on the running task, the
grader's reason inline, a header progress bar with ETA, and a final summary.

It is *opt-out by environment*: it only activates on an interactive terminal
(and only if `rich` is importable). In CI / non-TTY runs every hook no-ops and
pytest falls back to its normal dot output, so `.results/results.json` and the
CI comment are completely unaffected.

Set TALOS_EVAL_UI=plain to force the dots even on a TTY.
"""

from __future__ import annotations

import os
import sys
import time

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _fmt(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _parse(nodeid: str) -> tuple[str, str, str] | None:
    """`...::test_task[code-review/clean-noop]` -> (fid, agent, short)."""
    if "[" not in nodeid:
        return None
    fid = nodeid.split("[", 1)[1].rstrip("]")
    agent, _, short = fid.partition("/")
    if not short:
        return None
    return fid, agent, short


class TalosProgress:
    """A pytest plugin instance rendering a live dashboard to /dev/tty."""

    def __init__(self, config):
        self.config = config
        self.enabled = False
        self.live = None
        self._tty = None
        self._console = None

        if os.environ.get("TALOS_EVAL_UI") == "plain":
            return
        try:
            isatty = sys.stdout.isatty()
        except Exception:
            isatty = False
        if not isatty:
            return
        try:
            from rich.console import Console  # noqa: F401
        except Exception:
            return
        try:
            # Write straight to the controlling terminal so pytest's
            # file-descriptor output capture can't swallow the live region.
            self._tty = open("/dev/tty", "w", encoding="utf-8")
        except Exception:
            return
        self.enabled = True

        self.total = 0
        self.done = 0
        self.namew = 12
        self.agent_order: list[str] = []
        self.groups: dict[str, list[str]] = {}
        # fid -> {"agent","short","state","start","end","reason"}
        self.status: dict[str, dict] = {}
        self.counts = {"pass": 0, "fail": 0, "infra": 0}
        self.durations: list[float] = []
        self.session_start = time.monotonic()

    # ---- rendering -------------------------------------------------------

    def _render(self):
        from rich.console import Group
        from rich.text import Text

        now = time.monotonic()
        lines: list = []

        width = 22
        filled = int(width * self.done / self.total) if self.total else 0
        bar = Text()
        bar.append("evals  ", style="bold")
        bar.append("▕")
        bar.append("█" * filled, style="green")
        bar.append(" " * (width - filled))
        bar.append("▏ ")
        bar.append(f"{self.done}/{self.total}", style="bold")
        bar.append(f"  ⏱ {_fmt(now - self.session_start)}", style="dim")
        if self.durations and self.done < self.total:
            eta = (sum(self.durations) / len(self.durations)) * (self.total - self.done)
            bar.append(f"  ETA {_fmt(eta)}", style="dim")
        lines.append(bar)
        lines.append(Text(""))

        spin = SPINNER[int(now * 10) % len(SPINNER)]
        for agent in self.agent_order:
            lines.append(Text(f"  {agent}", style="bold cyan"))
            for fid in self.groups[agent]:
                st = self.status[fid]
                state = st["state"]
                if state == "pending":
                    icon, istyle, rstyle = "⏳", "dim", "dim"
                elif state == "running":
                    icon, istyle, rstyle = spin, "cyan", "cyan"
                elif state == "pass":
                    icon, istyle, rstyle = "✓", "green", "dim"
                elif state == "fail":
                    icon, istyle, rstyle = "✗", "red", "red"
                else:  # infra
                    icon, istyle, rstyle = "⊘", "yellow", "yellow"

                if state == "running" and st["start"]:
                    elapsed = _fmt(now - st["start"])
                elif st.get("end") and st.get("start"):
                    elapsed = _fmt(st["end"] - st["start"])
                else:
                    elapsed = ""

                reason = st.get("reason") or ("running…" if state == "running" else "")

                row = Text("    ")
                row.append(f"{icon} ", style=istyle)
                row.append(f"{st['short']:<{self.namew}} ")
                row.append(f"{reason[:34]:<34} ", style=rstyle)
                row.append(f"{elapsed:>5}", style="dim")
                lines.append(row)
            lines.append(Text(""))

        pending = self.total - self.done
        tally = Text("  ")
        tally.append(f"✓ {self.counts['pass']}   ", style="green")
        tally.append(f"✗ {self.counts['fail']}   ", style="red")
        tally.append(f"⊘ {self.counts['infra']}   ", style="yellow")
        tally.append(f"⏳ {pending}", style="dim")
        lines.append(tally)

        return Group(*lines)

    class _Dynamic:
        """Recomputes the whole panel each refresh so spinner + clocks tick."""

        def __init__(self, owner):
            self._owner = owner

        def __rich__(self):
            return self._owner._render()

    def _reason(self, agent: str, short: str) -> str:
        for entry in reversed(self.config._talos_results):
            if entry.get("agent") == agent and entry.get("task") == short:
                detail = entry.get("detail", "")
                reason = detail.split(" — ", 1)[1] if " — " in detail else detail
                return reason.split(" | ", 1)[0].strip()
        return ""

    # ---- pytest hooks ----------------------------------------------------

    def pytest_collection_finish(self, session):
        if not self.enabled:
            return
        for item in session.items:
            parsed = _parse(item.nodeid)
            if not parsed:
                continue
            fid, agent, short = parsed
            if agent not in self.groups:
                self.groups[agent] = []
                self.agent_order.append(agent)
            self.groups[agent].append(fid)
            self.status[fid] = {
                "agent": agent, "short": short, "state": "pending",
                "start": None, "end": None, "reason": "",
            }
            self.namew = max(self.namew, len(short))
        self.total = len(self.status)
        if not self.total:
            self.enabled = False
            return

        from rich.console import Console
        from rich.live import Live

        self._console = Console(file=self._tty, force_terminal=True)
        self.live = Live(
            self._Dynamic(self),
            console=self._console,
            refresh_per_second=12,
            transient=False,
        )
        self.live.start()

    def pytest_runtest_logstart(self, nodeid, location):
        if not self.enabled:
            return
        parsed = _parse(nodeid)
        if not parsed:
            return
        fid = parsed[0]
        st = self.status.get(fid)
        if st and st["state"] == "pending":
            st["state"] = "running"
            st["start"] = time.monotonic()

    def pytest_runtest_logreport(self, report):
        if not self.enabled:
            return
        parsed = _parse(report.nodeid)
        if not parsed:
            return
        fid, agent, short = parsed
        st = self.status.get(fid)
        if not st or st["state"] not in ("pending", "running"):
            return

        if report.when == "call":
            final = "pass" if report.passed else "fail" if report.failed else "infra"
        elif report.when == "setup" and report.skipped:
            final = "infra"
        elif report.when == "setup" and report.failed:
            final = "fail"
        else:
            return

        st["state"] = final
        st["end"] = time.monotonic()
        if st["start"]:
            self.durations.append(st["end"] - st["start"])
        st["reason"] = self._reason(agent, short) or (
            "infra failure" if final == "infra" else ""
        )
        self.counts[final] += 1
        self.done += 1

    def pytest_report_teststatus(self, report, config):
        # Silence the default dot stream while we own the screen, but keep the
        # category so pytest's final "N passed" summary line still tallies.
        if not self.enabled:
            return None
        if report.when in ("setup", "teardown") and report.passed:
            return ("", "", "")
        return (report.outcome, "", "")

    def pytest_sessionfinish(self, session, exitstatus):
        if not self.enabled or not self.live:
            return
        self.live.stop()
        from rich.panel import Panel
        from rich.text import Text

        elapsed = _fmt(time.monotonic() - self.session_start)
        summary = Text()
        summary.append(f"✓ {self.counts['pass']} passed   ", style="bold green")
        summary.append(f"✗ {self.counts['fail']} failed   ", style="bold red")
        summary.append(f"⊘ {self.counts['infra']} infra-skipped", style="bold yellow")
        summary.append(f"\n{self.total} tasks in {elapsed}", style="dim")
        self._console.print(Panel(summary, title="eval results", expand=False))
        try:
            self._tty.close()
        except Exception:
            pass
