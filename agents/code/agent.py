"""Code agent: picks up a GitHub issue, runs the Pi coding agent
(https://pi.dev) to implement the change, then commits the result, pushes a
branch, and opens a pull request.

Triggered from `.github/workflows/talos-code.yml` when someone with write
access posts a comment containing `@talos` on an issue.

Environment:
    GITHUB_TOKEN          token with `issues:write` (used for reactions/comments)
    PUSH_TOKEN            PAT with `contents:write` + `pull-requests:write`
                          (a separate token is used for push so the resulting
                          PR triggers downstream workflows; the default
                          GITHUB_TOKEN suppresses workflow_run events)
    GITHUB_REPOSITORY     owner/repo
    ISSUE_NUMBER          issue number that the agent should resolve
    COMMENT_ID            id of the @talos comment that triggered the run
                          (optional; used to add an eyes reaction)
    TRIGGERED_BY          login of the user who invoked the agent (optional)
    OPENROUTER_API_KEY    OpenRouter API key (passed through to Pi)
    MODEL                 model id (default: anthropic/claude-haiku-4.5)
    WORKSPACE             path to the repo checkout the agent should edit
                          (default: /workspace)
    GITHUB_RUN_ID         GitHub Actions run id (used to disambiguate branch names)
    ARIZE_SPACE_ID        (optional) Arize AX space id; enables tracing if set
    ARIZE_API_KEY         (optional) Arize AX API key; required with ARIZE_SPACE_ID
    ARIZE_PROJECT_NAME    (optional) Arize project name (default: talos-code)

Exit codes:
    0 = success (PR opened) or no-op (agent made no changes)
    1 = failure (Pi failed, push failed, or PR could not be opened)
"""

from __future__ import annotations

import os
import sys


def _setup_arize_tracing(default_project: str):
    """Initialise Arize AX tracing.

    Must run before `openai` is imported so the OpenAI instrumentor can patch
    the SDK. No-ops if ARIZE_SPACE_ID/ARIZE_API_KEY are not set. Returns the
    tracer provider (or None) so the caller can open spans on it directly.
    """
    space_id = os.environ.get("ARIZE_SPACE_ID")
    api_key = os.environ.get("ARIZE_API_KEY")
    if not space_id or not api_key:
        print("[code] ARIZE_SPACE_ID/ARIZE_API_KEY not set; tracing disabled", flush=True)
        return None
    from arize.otel import register
    from openinference.instrumentation.openai import OpenAIInstrumentor

    tracer_provider = register(
        space_id=space_id,
        api_key=api_key,
        project_name=os.environ.get("ARIZE_PROJECT_NAME", default_project),
    )
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
    return tracer_provider


def _flush_tracing() -> None:
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception:
        pass


_TRACER_PROVIDER = _setup_arize_tracing("talos-code")

import json  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

from opentelemetry import trace  # noqa: E402

AGENT_TAG = "<!-- talos:code -->"

PI_APPEND_SYSTEM_PROMPT = """You are Talos, an autonomous coding agent
implementing a single GitHub issue end-to-end.

Operating rules:
- Make the smallest set of changes that fully resolves the issue.
- Do NOT run `git commit`, `git push`, or open a PR yourself — the harness
  handles all version control. Just modify files in place.
- Do NOT modify CI workflow files, secrets, or anything outside the scope
  the issue describes.
- If the issue is ambiguous or appears to require destructive changes
  (deleting large amounts of code, rewriting unrelated subsystems), stop
  and explain what is unclear instead of guessing.
- After your changes, run any relevant tests (e.g. `npm test` in `todo-api/`).
  If tests fail and you cannot fix them, summarise the failure.
- Finish with a short summary of what you changed and why, including the
  files touched. This summary becomes the PR description.
"""


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        sys.exit(f"missing required env var: {name}")
    return value


def gh(
    args: list[str],
    *,
    token: str,
    stdin: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run `gh` with the given args, authenticating via GH_TOKEN.

    We pass the token via env (not a flag) so it never lands in process lists
    or workflow logs. Drop GITHUB_TOKEN from the inherited env so gh always
    uses the one we picked explicitly.
    """
    env_vars = os.environ.copy()
    env_vars["GH_TOKEN"] = token
    env_vars.pop("GITHUB_TOKEN", None)
    result = subprocess.run(
        ["gh", *args],
        env=env_vars,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(
            f"[code] gh {' '.join(args)} failed ({result.returncode}): {result.stderr}\n"
        )
        if check:
            raise subprocess.CalledProcessError(result.returncode, ["gh", *args], result.stdout, result.stderr)
    return result


def fetch_issue(token: str, repo: str, issue_number: str) -> dict:
    r = gh(["api", f"repos/{repo}/issues/{issue_number}"], token=token)
    return json.loads(r.stdout)


def fetch_issue_comments(token: str, repo: str, issue_number: str) -> list[dict]:
    r = gh(
        ["api", f"repos/{repo}/issues/{issue_number}/comments?per_page=100"],
        token=token,
    )
    return json.loads(r.stdout)


def add_reaction(token: str, repo: str, comment_id: str | None, issue_number: str, content: str) -> None:
    """React to the triggering comment, or to the issue itself as a fallback.

    Best-effort: reactions are cosmetic, so don't fail the run on errors.
    """
    if comment_id:
        endpoint = f"repos/{repo}/issues/comments/{comment_id}/reactions"
    else:
        endpoint = f"repos/{repo}/issues/{issue_number}/reactions"
    gh(
        ["api", endpoint, "-X", "POST", "-f", f"content={content}"],
        token=token,
        check=False,
    )


def post_issue_comment(token: str, repo: str, issue_number: str, body: str) -> None:
    gh(
        ["issue", "comment", str(issue_number), "--repo", repo, "--body-file", "-"],
        token=token,
        stdin=body,
    )


def run(cmd: list[str], cwd: str | None = None, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    print(f"[code] $ {' '.join(cmd)}", flush=True)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        check=False,
        capture_output=capture,
        text=True,
    )
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


def configure_git(workspace: str) -> None:
    # Bind-mounted checkouts often hit "detected dubious ownership" because
    # the host uid that owns the files doesn't match root inside the container.
    run(["git", "config", "--global", "--add", "safe.directory", workspace])
    run(["git", "config", "user.email", "talos-bot@users.noreply.github.com"], cwd=workspace)
    run(["git", "config", "user.name", "Talos Code Agent"], cwd=workspace)
    # Make sure we're in a clean state from origin/main.
    run(["git", "fetch", "origin", "main"], cwd=workspace)


def build_prompt(issue: dict, comments: list[dict]) -> str:
    title = issue.get("title") or "(no title)"
    body = issue.get("body") or "(no body)"
    parts = [
        f"GitHub issue #{issue.get('number')}: {title}",
        "",
        "## Issue body",
        body.strip(),
    ]
    relevant = [c for c in comments if "@talos" not in (c.get("body") or "")]
    if relevant:
        parts.extend(["", "## Discussion so far"])
        for c in relevant[-10:]:
            user = (c.get("user") or {}).get("login", "unknown")
            parts.append(f"\n**{user}:**\n{(c.get('body') or '').strip()}")
    parts.extend([
        "",
        "## Task",
        "Implement the change requested in this issue.",
        "Then summarise the files you changed and why.",
    ])
    return "\n".join(parts)


def run_pi(
    workspace: str,
    prompt: str,
    model: str,
    openrouter_key: str,
    tracer,
) -> tuple[int, str, list[dict]]:
    """Invoke `pi --mode json` and stream JSON events.

    Returns (exit_code, final_assistant_text, events). Each event is the
    parsed JSON line emitted by Pi. We open a span per turn so the run is
    visible in Arize alongside the existing agents.
    """
    cmd = [
        "pi",
        "--mode", "json",
        "--provider", "openrouter",
        "--model", model,
        "--no-session",
        "--append-system-prompt", PI_APPEND_SYSTEM_PROMPT,
        prompt,
    ]
    env_vars = os.environ.copy()
    env_vars["OPENROUTER_API_KEY"] = openrouter_key
    # Pi reads context files (CLAUDE.md/AGENTS.md) and skills from cwd ancestors.
    print(f"[code] launching pi: {' '.join(cmd[:6])} ... <prompt {len(prompt)} chars>", flush=True)
    proc = subprocess.Popen(
        cmd,
        cwd=workspace,
        env=env_vars,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    events: list[dict] = []
    final_text_chunks: list[str] = []
    current_turn_span = None
    current_turn_ctx = None

    assert proc.stdout is not None
    for raw in proc.stdout:
        raw = raw.strip()
        if not raw:
            continue
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            print(f"[code] non-JSON pi output: {raw[:200]}", flush=True)
            continue
        events.append(evt)
        etype = evt.get("type", "")

        if etype == "turn_start" and tracer is not None:
            current_turn_ctx = tracer.start_as_current_span(f"pi.turn.{len(events)}")
            current_turn_span = current_turn_ctx.__enter__()
        elif etype == "turn_end" and current_turn_ctx is not None:
            current_turn_ctx.__exit__(None, None, None)
            current_turn_ctx = None
            current_turn_span = None
        elif etype == "message_update":
            inner = evt.get("assistantMessageEvent", {})
            if inner.get("type") == "text_delta":
                final_text_chunks.append(inner.get("delta", ""))
        elif etype == "message_end":
            # `message_end` is emitted for each assistant message; the final
            # one is the agent's closing summary. We always concatenate text
            # deltas above, but if pi emits a `text` field on the end event
            # use that as a more reliable source.
            text = evt.get("text")
            if text and not final_text_chunks:
                final_text_chunks.append(text)
        if current_turn_span is not None:
            try:
                current_turn_span.add_event(etype, attributes={"raw": raw[:500]})
            except Exception:
                pass

    if current_turn_ctx is not None:
        current_turn_ctx.__exit__(None, None, None)

    stderr = proc.stderr.read() if proc.stderr else ""
    proc.wait()
    if stderr:
        sys.stderr.write(stderr)

    return proc.returncode, "".join(final_text_chunks).strip(), events


def has_changes(workspace: str) -> bool:
    result = run(["git", "status", "--porcelain"], cwd=workspace)
    return bool(result.stdout.strip())


def commit_and_push(workspace: str, branch: str, issue_number: str, summary: str, push_token: str, repo: str) -> None:
    run(["git", "checkout", "-b", branch], cwd=workspace)
    run(["git", "add", "-A"], cwd=workspace)
    title_line = f"talos: address issue #{issue_number}"
    body_line = summary.strip().splitlines()[0] if summary.strip() else "Implemented via Talos code agent."
    run(
        ["git", "commit", "-m", title_line, "-m", body_line],
        cwd=workspace,
    )
    # Push using the supplied PAT so downstream workflows (the existing
    # talos-sdlc.yml on PR open) actually fire.
    remote = f"https://x-access-token:{push_token}@github.com/{repo}.git"
    run(["git", "push", remote, f"HEAD:refs/heads/{branch}"], cwd=workspace)


def open_pr(token: str, repo: str, branch: str, issue_number: str, issue_title: str, summary: str, model: str) -> str:
    """Open a PR via `gh pr create`.

    The caller must pass the PAT (not GITHUB_TOKEN): PRs opened with the
    default Actions token do not trigger downstream workflows.
    """
    title = (f"talos: {issue_title}".strip())[:120]
    body = (
        f"{AGENT_TAG}\n"
        f"Closes #{issue_number}.\n\n"
        f"## Summary\n\n{summary or '(no summary returned by the agent)'}\n\n"
        f"---\n_Generated by the Talos code agent (pi.dev + `{model}`)._"
    )
    r = gh(
        [
            "pr", "create",
            "--repo", repo,
            "--base", "main",
            "--head", branch,
            "--title", title,
            "--body-file", "-",
        ],
        token=token,
        stdin=body,
    )
    # `gh pr create` prints the PR URL on the last non-empty stdout line.
    for line in reversed(r.stdout.splitlines()):
        line = line.strip()
        if line.startswith("https://"):
            return line
    return ""


def main() -> int:
    token = env("GITHUB_TOKEN")
    push_token = os.environ.get("PUSH_TOKEN") or token
    repo = env("GITHUB_REPOSITORY")
    issue_number = env("ISSUE_NUMBER")
    comment_id = os.environ.get("COMMENT_ID") or None
    openrouter_key = env("OPENROUTER_API_KEY")
    model = os.environ.get("MODEL", "anthropic/claude-haiku-4.5")
    workspace = os.environ.get("WORKSPACE", "/workspace")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")

    if not Path(workspace, ".git").exists():
        sys.exit(f"workspace {workspace} is not a git checkout")

    tracer = trace.get_tracer("talos.code") if _TRACER_PROVIDER else None

    span_ctx = tracer.start_as_current_span("talos.code.run") if tracer else None
    span = span_ctx.__enter__() if span_ctx else None
    if span is not None:
        span.set_attribute("talos.repo", repo)
        span.set_attribute("talos.issue_number", issue_number)
        span.set_attribute("talos.model", model)
        if os.environ.get("TRIGGERED_BY"):
            span.set_attribute("talos.triggered_by", os.environ["TRIGGERED_BY"])

    try:
        add_reaction(token, repo, comment_id, issue_number, "eyes")

        issue = fetch_issue(token, repo, issue_number)
        if issue.get("pull_request"):
            print("[code] target is a pull request, not an issue — refusing", flush=True)
            post_issue_comment(
                token, repo, issue_number,
                f"{AGENT_TAG}\nTalos only runs against issues, not pull requests.",
            )
            return 0

        comments = fetch_issue_comments(token, repo, issue_number)
        prompt = build_prompt(issue, comments)

        configure_git(workspace)
        run(["git", "checkout", "main"], cwd=workspace, check=False)
        run(["git", "reset", "--hard", "origin/main"], cwd=workspace, check=False)

        exit_code, summary, events = run_pi(workspace, prompt, model, openrouter_key, tracer)
        if span is not None:
            span.set_attribute("talos.pi.exit_code", exit_code)
            span.set_attribute("talos.pi.event_count", len(events))

        if exit_code != 0:
            msg = f"Pi exited with code {exit_code}. See workflow logs for details."
            print(f"[code] {msg}", flush=True)
            post_issue_comment(
                token, repo, issue_number,
                f"{AGENT_TAG}\n:x: Talos failed to implement this issue.\n\n{msg}",
            )
            add_reaction(token, repo, comment_id, issue_number, "confused")
            if span is not None:
                span.set_attribute("talos.verdict", "pi_failed")
            return 1

        if not has_changes(workspace):
            print("[code] no file changes produced", flush=True)
            post_issue_comment(
                token, repo, issue_number,
                f"{AGENT_TAG}\n:information_source: Talos ran but produced no changes.\n\n"
                f"**Agent summary:**\n\n{summary or '(no summary)'}",
            )
            add_reaction(token, repo, comment_id, issue_number, "confused")
            if span is not None:
                span.set_attribute("talos.verdict", "no_changes")
            return 0

        branch = f"talos/issue-{issue_number}-{run_id}"
        commit_and_push(workspace, branch, issue_number, summary, push_token, repo)
        # Use the PAT to create the PR so downstream pr-review fires.
        pr_url = open_pr(push_token, repo, branch, issue_number, issue.get("title") or "", summary, model)

        post_issue_comment(
            token, repo, issue_number,
            f"{AGENT_TAG}\n:rocket: Talos opened {pr_url} for this issue.\n\n"
            f"**Summary:**\n\n{summary}",
        )
        add_reaction(token, repo, comment_id, issue_number, "rocket")
        if span is not None:
            span.set_attribute("talos.verdict", "pr_opened")
            span.set_attribute("talos.pr_url", pr_url)
        print(f"[code] opened {pr_url}", flush=True)
        return 0
    except Exception as e:  # noqa: BLE001 — top-level reporter
        print(f"[code] unhandled error: {e}", flush=True)
        try:
            post_issue_comment(
                token, repo, issue_number,
                f"{AGENT_TAG}\n:x: Talos crashed: `{type(e).__name__}: {e}`. See workflow logs.",
            )
        except Exception:
            pass
        if span is not None:
            span.set_attribute("talos.verdict", "crashed")
            span.record_exception(e)
        return 1
    finally:
        if span_ctx is not None:
            span_ctx.__exit__(None, None, None)


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _flush_tracing()
