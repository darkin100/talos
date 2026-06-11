"""Code agent: picks up a GitHub issue, runs the Pi coding agent
(https://pi.dev) to implement the change, then commits the result, pushes a
branch, and opens a pull request.

Triggered from `.github/workflows/talos-code.yml` when someone with write
access posts a comment containing `@talos` on an issue.

Auth model: the agent runs with the default workflow `GITHUB_TOKEN` only —
there is no long-lived push PAT. `actions/checkout` writes its credential
into `.git/config` so `git push` works through the bind mount. A PR opened
by GITHUB_TOKEN doesn't fire downstream `pull_request` workflows (GitHub's
loop-prevention), so after opening the PR we emit a `repository_dispatch`
event of type `talos-pr-ready` to wake up `talos-sdlc.yml`.

Environment:
    GITHUB_TOKEN          default Actions token (contents:write, issues:write,
                          pull-requests:write). Used for push, PR creation,
                          comments/reactions, and the dispatch fire.
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
    # Prompt-injection note: issue title, body, and comments are
    # attacker-influenceable in principle, and we deliberately pass them
    # through to Pi without sanitisation — sanitising free-form English
    # would just blind the agent. The primary control is upstream in the
    # workflow: `if:` gates on `author_association ∈ {OWNER, MEMBER,
    # COLLABORATOR}`, so an unprivileged user can't trigger a run at all.
    # Secondary controls: Pi executes inside an ephemeral container with
    # only the job-lifetime GITHUB_TOKEN available (no long-lived PAT),
    # the env handed to it is scrubbed of the workflow token and tracing
    # keys in `run_pi`, and `PI_APPEND_SYSTEM_PROMPT` instructs Pi not to
    # touch CI files or secrets. The harness (not Pi) does the git push
    # and PR open.
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


# --- OpenInference span helpers -------------------------------------------
#
# Pi runs as a subprocess, so the OpenAI auto-instrumentor never sees its LLM
# calls. We reconstruct OpenInference-compliant LLM/TOOL spans from Pi's JSON
# event stream instead (conventions: docs/openinference-spec/).

WELL_KNOWN_LLM_SYSTEMS = {
    "anthropic", "openai", "vertexai", "cohere", "mistralai",
    "xai", "deepseek", "amazon", "meta", "ai21",
}


def llm_system_for(model: str) -> str:
    """Map an OpenRouter model id (e.g. anthropic/claude-haiku-4.5) to llm.system."""
    prefix = model.split("/", 1)[0].lower()
    return prefix if prefix in WELL_KNOWN_LLM_SYSTEMS else model


def _message_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
    return "".join(parts)


def _content_blocks(msg: dict) -> list[dict]:
    content = msg.get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _tool_calls(msg: dict) -> list[dict]:
    calls: list[dict] = []
    for block in _content_blocks(msg):
        if block.get("type") in {"toolCall", "tool_call", "tool_use"}:
            args = block.get("arguments") if "arguments" in block else block.get("input")
            calls.append({
                "id": str(block.get("id") or block.get("toolCallId") or ""),
                "name": str(block.get("name") or block.get("toolName") or ""),
                "arguments": args if isinstance(args, str) else json.dumps(args or {}),
            })
    return calls


def _flatten_message(msg: dict) -> dict:
    """Flatten a Pi message into OpenInference `message.*` attributes."""
    role = str(msg.get("role") or "")
    if role == "toolResult":
        role = "tool"
    out: dict = {"message.role": role}
    text = _message_text(msg)
    if text:
        out["message.content"] = text
    if role == "tool":
        if msg.get("toolName"):
            out["message.name"] = str(msg["toolName"])
        if msg.get("toolCallId"):
            out["message.tool_call_id"] = str(msg["toolCallId"])
    for i, call in enumerate(_tool_calls(msg)):
        for suffix, value in (
            ("id", call["id"]),
            ("function.name", call["name"]),
            ("function.arguments", call["arguments"]),
        ):
            if value:
                out[f"message.tool_calls.{i}.tool_call.{suffix}"] = value
    # Reasoning must be replayable in order, so emit ordered message.contents
    # items when the model produced any thinking content.
    blocks = _content_blocks(msg)
    if any(b.get("type") in {"thinking", "reasoning"} for b in blocks):
        ci = 0
        for b in blocks:
            btype = b.get("type")
            if btype in {"thinking", "reasoning"}:
                out[f"message.contents.{ci}.message_content.type"] = "reasoning"
                out[f"message.contents.{ci}.message_content.text"] = str(
                    b.get("thinking") or b.get("text") or ""
                )
                if b.get("signature"):
                    out[f"message.contents.{ci}.message_content.signature"] = str(b["signature"])
                ci += 1
            elif btype == "text":
                out[f"message.contents.{ci}.message_content.type"] = "text"
                out[f"message.contents.{ci}.message_content.text"] = str(b.get("text") or "")
                ci += 1
    return out


def _token_count_attrs(usage: dict) -> dict:
    """Map Pi/OpenAI-style usage objects onto llm.token_count.* / llm.cost.*."""
    def grab(src: dict, *keys: str) -> int | float | None:
        for k in keys:
            v = src.get(k)
            if isinstance(v, (int, float)):
                return v
        return None

    out: dict = {}
    prompt = grab(usage, "input", "prompt_tokens", "inputTokens")
    completion = grab(usage, "output", "completion_tokens", "outputTokens")
    total = grab(usage, "total", "total_tokens", "totalTokens")
    cache_read = grab(usage, "cacheRead", "cache_read_input_tokens")
    cache_write = grab(usage, "cacheWrite", "cache_creation_input_tokens")
    if prompt is not None:
        out["llm.token_count.prompt"] = int(prompt)
    if completion is not None:
        out["llm.token_count.completion"] = int(completion)
    if cache_read is not None:
        out["llm.token_count.prompt_details.cache_read"] = int(cache_read)
    if cache_write is not None:
        out["llm.token_count.prompt_details.cache_write"] = int(cache_write)
    if total is None and (prompt is not None or completion is not None):
        total = (prompt or 0) + (completion or 0)
    if total is not None:
        out["llm.token_count.total"] = int(total)
    cost = usage.get("cost")
    if isinstance(cost, dict):
        for attr, key in (
            ("llm.cost.prompt", "input"),
            ("llm.cost.completion", "output"),
            ("llm.cost.total", "total"),
        ):
            v = grab(cost, key)
            if v is not None:
                out[attr] = float(v)
    return out


def _record_llm_span(span, model: str, conversation: list[dict], msg: dict) -> None:
    """Populate an LLM span per the OpenInference LLM-span conventions."""
    span.set_attribute("llm.system", llm_system_for(model))
    span.set_attribute("llm.provider", "openrouter")
    span.set_attribute("llm.model_name", str(msg.get("model") or model))
    span.set_attribute("llm.invocation_parameters", json.dumps({"model": model}))
    span.set_attribute(
        "input.value",
        json.dumps({
            "model": model,
            "messages": [
                {"role": m.get("message.role"), "content": m.get("message.content", "")}
                for m in conversation
            ],
        }),
    )
    span.set_attribute("input.mime_type", "application/json")
    for i, m in enumerate(conversation):
        for key, value in m.items():
            span.set_attribute(f"llm.input_messages.{i}.{key}", value)
    for key, value in _flatten_message(msg).items():
        span.set_attribute(f"llm.output_messages.0.{key}", value)
    text = _message_text(msg)
    if text:
        span.set_attribute("output.value", text)
        span.set_attribute("output.mime_type", "text/plain")
    stop = msg.get("stopReason") or msg.get("stop_reason")
    if stop:
        span.set_attribute("llm.finish_reason", str(stop))
    usage = msg.get("usage")
    if isinstance(usage, dict):
        for key, value in _token_count_attrs(usage).items():
            span.set_attribute(key, value)


def run_pi(
    workspace: str,
    prompt: str,
    model: str,
    openrouter_key: str,
    tracer,
) -> tuple[int, str, list[dict]]:
    """Invoke `pi --mode json` and stream JSON events.

    Returns (exit_code, final_assistant_text, events). Each event is the
    parsed JSON line emitted by Pi. The event stream is mirrored into
    OpenInference spans: a CHAIN span per turn, an LLM span per assistant
    message (input/output messages and token counts reconstructed from the
    stream), and a TOOL span per tool execution.
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
    # Strip secrets Pi doesn't need: a prompt-injected issue body could
    # otherwise convince Pi to exfiltrate the workflow token or tracing keys.
    sensitive = {"GITHUB_TOKEN", "GH_TOKEN", "ARIZE_API_KEY", "ARIZE_SPACE_ID"}
    env_vars = {k: v for k, v in os.environ.items() if k not in sensitive}
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
    # Conversation as flattened OpenInference messages; each LLM span snapshots
    # this as its llm.input_messages. Pi prepends its own base system prompt,
    # which we can't observe, so the system message holds our appended prompt.
    conversation: list[dict] = [
        {"message.role": "system", "message.content": PI_APPEND_SYSTEM_PROMPT},
        {"message.role": "user", "message.content": prompt},
    ]
    turn_count = 0
    llm_count = 0
    turn_handle = None
    llm_handle = None
    tool_handle = None

    def start_span(name: str, kind: str):
        if tracer is None:
            return None
        cm = tracer.start_as_current_span(name)
        span = cm.__enter__()
        span.set_attribute("openinference.span.kind", kind)
        return cm, span

    def end_span(handle) -> None:
        if handle is not None:
            handle[0].__exit__(None, None, None)

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
        msg = evt.get("message") if isinstance(evt.get("message"), dict) else {}

        try:
            if etype == "turn_start":
                end_span(turn_handle)
                turn_count += 1
                turn_handle = start_span(f"pi.turn.{turn_count}", "CHAIN")
            elif etype == "message_start":
                if msg.get("role", "assistant") == "assistant" and llm_handle is None:
                    llm_count += 1
                    llm_handle = start_span(f"pi.llm.{llm_count}", "LLM")
            elif etype == "message_update":
                inner = evt.get("assistantMessageEvent", {})
                if inner.get("type") == "text_delta":
                    final_text_chunks.append(inner.get("delta", ""))
            elif etype == "message_end":
                role = msg.get("role", "")
                if role == "assistant":
                    if llm_handle is None:
                        llm_count += 1
                        llm_handle = start_span(f"pi.llm.{llm_count}", "LLM")
                    if llm_handle is not None:
                        _record_llm_span(llm_handle[1], model, conversation, msg)
                    end_span(llm_handle)
                    llm_handle = None
                    conversation.append(_flatten_message(msg))
                elif role in {"toolResult", "tool"}:
                    entry = _flatten_message(msg)
                    tcid = entry.get("message.tool_call_id")
                    if not tcid or all(
                        m.get("message.tool_call_id") != tcid for m in conversation
                    ):
                        conversation.append(entry)
                # `message_end` is emitted for each assistant message; the
                # final one is the agent's closing summary. We always
                # concatenate text deltas above, but if pi emits a `text`
                # field on the end event use that as a more reliable source.
                text = evt.get("text")
                if text and not final_text_chunks:
                    final_text_chunks.append(text)
            elif etype in {"tool_execution_start", "toolExecutionStart"}:
                end_span(tool_handle)
                tool_name = str(evt.get("toolName") or evt.get("tool_name") or "tool")
                tool_handle = start_span(f"pi.tool.{tool_name}", "TOOL")
                if tool_handle is not None:
                    tool_span = tool_handle[1]
                    tool_span.set_attribute("tool.name", tool_name)
                    call_id = evt.get("toolCallId") or evt.get("tool_call_id")
                    if call_id:
                        tool_span.set_attribute("tool.id", str(call_id))
                    args = evt.get("args") if "args" in evt else evt.get("arguments")
                    if args is not None:
                        tool_span.set_attribute(
                            "input.value", args if isinstance(args, str) else json.dumps(args)
                        )
                        tool_span.set_attribute("input.mime_type", "application/json")
            elif etype in {"tool_execution_end", "toolExecutionEnd"}:
                result = evt.get("result")
                result_text = _message_text(result) if isinstance(result, dict) else str(result or "")
                if tool_handle is not None:
                    tool_span = tool_handle[1]
                    if result_text:
                        tool_span.set_attribute("output.value", result_text[:8000])
                        tool_span.set_attribute("output.mime_type", "text/plain")
                end_span(tool_handle)
                tool_handle = None
                # Record the result in the conversation unless Pi also emits a
                # toolResult message_end for it (deduped on tool_call_id).
                call_id = str(evt.get("toolCallId") or evt.get("tool_call_id") or "")
                if call_id and all(
                    m.get("message.tool_call_id") != call_id for m in conversation
                ):
                    entry = {
                        "message.role": "tool",
                        "message.tool_call_id": call_id,
                        "message.content": result_text[:8000],
                    }
                    tool_name = evt.get("toolName") or evt.get("tool_name")
                    if tool_name:
                        entry["message.name"] = str(tool_name)
                    conversation.append(entry)
            elif etype == "turn_end":
                end_span(llm_handle)
                llm_handle = None
                end_span(tool_handle)
                tool_handle = None
                end_span(turn_handle)
                turn_handle = None
        except Exception as exc:  # span bookkeeping must never kill the run
            print(f"[code] span bookkeeping error on {etype}: {exc}", flush=True)

        if turn_handle is not None:
            try:
                turn_handle[1].add_event(etype, attributes={"raw": raw[:500]})
            except Exception:
                pass

    end_span(llm_handle)
    end_span(tool_handle)
    end_span(turn_handle)

    stderr = proc.stderr.read() if proc.stderr else ""
    proc.wait()
    if stderr:
        sys.stderr.write(stderr)

    return proc.returncode, "".join(final_text_chunks).strip(), events


def has_changes(workspace: str) -> bool:
    result = run(["git", "status", "--porcelain"], cwd=workspace)
    return bool(result.stdout.strip())


def commit_and_push(workspace: str, branch: str, issue_number: str, summary: str) -> None:
    run(["git", "checkout", "-b", branch], cwd=workspace)
    run(["git", "add", "-A"], cwd=workspace)
    title_line = f"talos: address issue #{issue_number}"
    body_line = summary.strip().splitlines()[0] if summary.strip() else "Implemented via Talos code agent."
    run(
        ["git", "commit", "-m", title_line, "-m", body_line],
        cwd=workspace,
    )
    # `actions/checkout` already configured the GITHUB_TOKEN credential in
    # the bind-mounted .git/config (as http.extraheader), so this push
    # works with no extra auth plumbing and no token in argv.
    run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], cwd=workspace)


def open_pr(token: str, repo: str, branch: str, issue_number: str, issue_title: str, summary: str, model: str) -> str:
    """Open a PR via `gh pr create`.

    Uses GITHUB_TOKEN. The PR's `pull_request` event is suppressed by GitHub's
    loop-prevention, so the caller follows up with `dispatch_pr_ready()` to
    wake up the downstream SDLC workflow.
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


def dispatch_pr_ready(token: str, repo: str, pr_number: str | int) -> None:
    """Fire `repository_dispatch: talos-pr-ready` so the SDLC workflow runs.

    A PR opened by GITHUB_TOKEN does not trigger `pull_request` events, so the
    code-review / security-review / auto-merge pipeline would otherwise sit
    idle. This dispatch wakes it up, with the PR number in the payload.
    """
    gh(
        [
            "api", f"repos/{repo}/dispatches",
            "-X", "POST",
            "-f", "event_type=talos-pr-ready",
            "-F", f"client_payload[pr_number]={int(pr_number)}",
        ],
        token=token,
    )


def main() -> int:
    token = env("GITHUB_TOKEN")
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
        span.set_attribute("openinference.span.kind", "AGENT")
        span.set_attribute("agent.name", "talos-code")
        span.set_attribute("session.id", run_id)
        span.set_attribute(
            "metadata",
            json.dumps({"repo": repo, "issue_number": issue_number, "model": model}),
        )
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
        if span is not None:
            span.set_attribute("input.value", prompt)
            span.set_attribute("input.mime_type", "text/plain")

        configure_git(workspace)
        run(["git", "checkout", "main"], cwd=workspace, check=False)
        run(["git", "reset", "--hard", "origin/main"], cwd=workspace, check=False)

        exit_code, summary, events = run_pi(workspace, prompt, model, openrouter_key, tracer)
        if span is not None:
            span.set_attribute("talos.pi.exit_code", exit_code)
            span.set_attribute("talos.pi.event_count", len(events))
            if summary:
                span.set_attribute("output.value", summary)
                span.set_attribute("output.mime_type", "text/plain")

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
        commit_and_push(workspace, branch, issue_number, summary)
        pr_url = open_pr(token, repo, branch, issue_number, issue.get("title") or "", summary, model)

        # GITHUB_TOKEN-opened PRs don't fire `pull_request` events; this
        # dispatch is what actually triggers the SDLC workflow.
        pr_number = pr_url.rstrip("/").rsplit("/", 1)[-1]
        if pr_number.isdigit():
            dispatch_pr_ready(token, repo, pr_number)
        else:
            print(f"[code] could not parse PR number from {pr_url!r}; SDLC dispatch skipped", flush=True)

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
