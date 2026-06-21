"""Code-review agent: reviews a PR with the Pi coding agent and comments on it.

Unlike a diff-only reviewer, this agent runs Pi (https://pi.dev) inside a
checkout of the repository, so it can read the *full* files the diff touches —
not just the ~3 lines of surrounding context a unified diff carries. That
context is what stops convention-blind false positives: a reviewer that can
read `handler.js` sees that every handler returns a numeric status, so it does
not invent a "this return is wrong" defect (see evals cr-005, cr-016).

Pi reviews; it must not edit. The harness reads only Pi's final JSON verdict.

Reads configuration from environment variables (provided by GitHub Actions):

    GITHUB_TOKEN         token with PR write access
    GITHUB_REPOSITORY    owner/repo (e.g. darkin100/talos)
    PR_NUMBER            pull request number to review
    OPENROUTER_API_KEY   OpenRouter API key for LLM access
    MODEL                model id (default: anthropic/claude-haiku-4.5)
    WORKSPACE            (optional) repo checkout Pi reviews in (default: /workspace)
    DIFF_FILE            (optional) read the diff from this path instead of the
                         GitHub API — used by eval replay for hermetic inputs
    DRY_RUN              (optional) if set to a truthy value, do not post the PR
                         comment; emit the artifact to stdout instead
    ARIZE_SPACE_ID       (optional) Arize AX space id; enables tracing if set
    ARIZE_API_KEY        (optional) Arize AX API key; required with ARIZE_SPACE_ID
    ARIZE_PROJECT_NAME   (optional) Arize project name (default: talos-code-review)

Exit codes:
    0 = pass  (no significant feedback posted)
    1 = fail  (significant issues found and commented on the PR)
"""

from __future__ import annotations

import os
import sys


def _setup_arize_tracing(default_project: str) -> None:
    """Initialise Arize AX tracing. No-ops without ARIZE_SPACE_ID/ARIZE_API_KEY.

    Pi runs as a subprocess, so the OpenAI auto-instrumentor never sees its LLM
    calls; we reconstruct OpenInference spans from Pi's JSON event stream
    instead (see run_pi_review). This still registers the tracer provider so
    those reconstructed spans are exported.
    """
    space_id = os.environ.get("ARIZE_SPACE_ID")
    api_key = os.environ.get("ARIZE_API_KEY")
    if not space_id or not api_key:
        print("[code-review] ARIZE_SPACE_ID/ARIZE_API_KEY not set; tracing disabled", flush=True)
        return
    from arize.otel import register

    register(
        space_id=space_id,
        api_key=api_key,
        project_name=os.environ.get("ARIZE_PROJECT_NAME", default_project),
    )


def _flush_tracing() -> None:
    """Force-flush queued spans so short-lived runs don't drop traces."""
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception:
        pass


_setup_arize_tracing("talos-code-review")

import json  # noqa: E402
import subprocess  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

from opentelemetry import trace  # noqa: E402

try:
    from openinference.instrumentation import using_attributes  # noqa: E402
except ImportError:  # tracing deps absent — degrade to a no-op
    from contextlib import contextmanager  # noqa: E402

    @contextmanager
    def using_attributes(**_kwargs):
        yield


GITHUB_API = "https://api.github.com"
AGENT_TAG = "<!-- talos:code-review -->"
ARTIFACT_BEGIN = "===TALOS_EVAL_ARTIFACT_BEGIN==="
ARTIFACT_END = "===TALOS_EVAL_ARTIFACT_END==="

# Appended to Pi's base system prompt. The rules exist to kill the failure mode
# the diff-only reviewer had: inventing defects that the surrounding code (which
# it could not see) actually contradicts. Now Pi *can* see the code, so we
# require it to ground every claim in a file it has actually read.
PI_APPEND_SYSTEM_PROMPT = """You are Talos, a senior engineer performing a code review.

You are reviewing a proposed change to THIS repository. The working tree is the
post-change state; the unified diff in the task message tells you what changed.
You have full read access to every file — use it.

Operating rules:
- You are a REVIEWER. Do NOT edit, create, or delete files, and do NOT run
  git commit/push. Read files, search, and run read-only checks only.
- Before you call anything a defect, CONFIRM it against the actual code. Open
  the changed files and the code around them. If a claim depends on code
  outside the diff, read that code before asserting it.
- Do NOT flag something as wrong because it looks unusual in isolation. If the
  change follows the file's own established convention (return values, exports,
  call patterns, error handling), it is NOT a defect — verify by reading the
  rest of the file before judging.
- A false "fail" blocks correct work and erodes trust. When the change is
  correct, PASS it. Only fail on a defect you have actually verified.
- "fail" means a real, verified defect: incorrect logic, a broken contract, a
  missing test for behaviour that clearly needs one, or a genuine
  maintainability problem worth blocking on.
- Style nits, naming preferences, and speculative refactors are NOT failures.
- If it helps, run the project's tests read-only (e.g. `npm test` in `todo-api/`)
  to check your reasoning before deciding.

Do your reading and analysis first. Then your VERY LAST message must be ONLY a
single JSON object — no prose around it, no code fences, and do not end the
turn on a tool call. This message is the only thing the harness reads:

    {"verdict": "pass" | "fail", "summary": "<one paragraph, <250 words, cite specific files/lines>"}
"""

# Distinct stderr signature for "Pi never produced a parseable verdict". The
# eval runner matches this (INFRA_PATTERNS) so the trial is skipped, not graded
# as a fail — an unparseable run produced no gradeable outcome, and counting it
# as "fail" would manufacture the false positives this rewrite exists to avoid.
NO_VERDICT_SIGNATURE = "could not determine a code-review verdict"
NO_VERDICT_EXIT_CODE = 3


def dry_run_enabled() -> bool:
    return os.environ.get("DRY_RUN", "").lower() not in {"", "0", "false"}


def emit_artifact(artifact: dict) -> None:
    """Print the would-be side effect (PR comment) for the eval runner."""
    print(ARTIFACT_BEGIN, flush=True)
    print(json.dumps(artifact), flush=True)
    print(ARTIFACT_END, flush=True)


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        sys.exit(f"missing required env var: {name}")
    return value


def http_request(url: str, method: str = "GET", headers: dict | None = None, body: bytes | None = None) -> bytes:
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code} for {method} {url}: {e.read().decode('utf-8', 'replace')}\n")
        raise


def fetch_pr_diff(token: str, repo: str, pr_number: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": "talos-code-review-agent",
    }
    data = http_request(f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}", headers=headers)
    return data.decode("utf-8", "replace")


def _extract_json_object(content: str) -> dict:
    """Extract the first JSON object from a model response.

    Pi's final message should be a bare JSON object, but tolerate stray fences
    or trailing prose: find the first '{' and consume one JSON value.

    Safety: the stdlib `json` module decodes only JSON primitives/lists/dicts —
    it cannot execute code or instantiate classes. Trailing content after the
    first object is discarded; we only read `verdict`/`summary`.
    """
    s = content.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl >= 0:
            s = s[nl + 1:]
    start = s.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in model response: {content!r}")
    obj, _ = json.JSONDecoder().raw_decode(s[start:])
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object, got {type(obj).__name__}: {content!r}")
    return obj


# --- OpenInference span helpers (ported from the code agent) ----------------
#
# Pi runs as a subprocess, so we reconstruct OpenInference-compliant LLM/TOOL
# spans from its JSON event stream (conventions: docs/openinference-spec/).

WELL_KNOWN_LLM_SYSTEMS = {
    "anthropic", "openai", "vertexai", "cohere", "mistralai",
    "xai", "deepseek", "amazon", "meta", "ai21",
}


def llm_system_for(model: str) -> str:
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
    return out


def _token_count_attrs(usage: dict) -> dict:
    """Map Pi/OpenAI-style usage objects onto llm.token_count.* / llm.cost.*."""
    def grab(src: dict, *keys: str):
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
    span.set_attribute("llm.system", llm_system_for(model))
    span.set_attribute("llm.provider", "openrouter")
    span.set_attribute("llm.model_name", str(msg.get("model") or model))
    span.set_attribute("llm.invocation_parameters", json.dumps({"model": model}))
    for i, m in enumerate(conversation):
        for key, value in m.items():
            span.set_attribute(f"llm.input_messages.{i}.{key}", value)
    for key, value in _flatten_message(msg).items():
        span.set_attribute(f"llm.output_messages.0.{key}", value)
    text = _message_text(msg)
    if text:
        span.set_attribute("output.value", text)
        span.set_attribute("output.mime_type", "text/plain")
    usage = msg.get("usage")
    if isinstance(usage, dict):
        for key, value in _token_count_attrs(usage).items():
            span.set_attribute(key, value)


def build_review_prompt(diff: str) -> str:
    return (
        "Review the following change to this repository. The working tree is "
        "already at the post-change state; read whatever files you need to "
        "judge it. Verify, don't assume.\n\n"
        "## Unified diff under review\n\n"
        f"{diff}\n\n"
        "## Task\n"
        "Decide whether this change should be merged. Confirm any concern by "
        "reading the actual code before raising it. Then reply with ONLY the "
        "JSON verdict object specified in your instructions."
    )


def run_pi_review(workspace: str, prompt: str, model: str, openrouter_key: str, tracer) -> list[str]:
    """Invoke `pi --mode json` in the workspace; return assistant message texts.

    Returns the text of every assistant message in order. The caller scans
    these (last-first) for the JSON verdict — robust to Pi appending a chatty
    sign-off after the verdict, or ending on a tool call with no text.

    Reconstructs OpenInference CHAIN/LLM/TOOL spans from Pi's event stream so
    the review keeps the per-agent trace tree the other agents emit.
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
    sensitive = {"GITHUB_TOKEN", "GH_TOKEN", "ARIZE_API_KEY", "ARIZE_SPACE_ID"}
    env_vars = {k: v for k, v in os.environ.items() if k not in sensitive}
    env_vars["OPENROUTER_API_KEY"] = openrouter_key
    print(f"[code-review] launching pi in {workspace}: {' '.join(cmd[:6])} ... <prompt {len(prompt)} chars>", flush=True)
    proc = subprocess.Popen(
        cmd,
        cwd=workspace,
        env=env_vars,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    conversation: list[dict] = [
        {"message.role": "system", "message.content": PI_APPEND_SYSTEM_PROMPT},
        {"message.role": "user", "message.content": prompt},
    ]
    assistant_texts: list[str] = []
    delta_buffer: list[str] = []
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
            print(f"[code-review] non-JSON pi output: {raw[:200]}", flush=True)
            continue
        etype = evt.get("type", "")
        msg = evt.get("message") if isinstance(evt.get("message"), dict) else {}

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
                delta_buffer.append(inner.get("delta", ""))
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
                # Record this assistant message's text. Prefer the message's
                # own text; fall back to the streamed deltas.
                text = _message_text(msg) or evt.get("text") or "".join(delta_buffer)
                if text.strip():
                    assistant_texts.append(text)
                delta_buffer = []
            elif role in {"toolResult", "tool"}:
                conversation.append(_flatten_message(msg))
        elif etype in {"tool_execution_start", "toolExecutionStart"}:
            end_span(tool_handle)
            tool_name = str(evt.get("toolName") or evt.get("tool_name") or "tool")
            tool_handle = start_span(f"pi.tool.{tool_name}", "TOOL")
            if tool_handle is not None:
                tool_handle[1].set_attribute("tool.name", tool_name)
                args = evt.get("args") if "args" in evt else evt.get("arguments")
                if args is not None:
                    tool_handle[1].set_attribute(
                        "input.value", args if isinstance(args, str) else json.dumps(args)
                    )
                    tool_handle[1].set_attribute("input.mime_type", "application/json")
        elif etype in {"tool_execution_end", "toolExecutionEnd"}:
            result = evt.get("result")
            result_text = _message_text(result) if isinstance(result, dict) else str(result or "")
            if tool_handle is not None and result_text:
                tool_handle[1].set_attribute("output.value", result_text[:8000])
                tool_handle[1].set_attribute("output.mime_type", "text/plain")
            end_span(tool_handle)
            tool_handle = None

    end_span(llm_handle)
    end_span(tool_handle)
    end_span(turn_handle)
    proc.wait()
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.returncode != 0:
        sys.stderr.write(f"[code-review] pi exited {proc.returncode}: {stderr[-2000:]}\n")
    if not assistant_texts:
        raise ValueError(f"pi produced no assistant messages (exit {proc.returncode})")
    return assistant_texts


def parse_verdict(assistant_texts: list[str]) -> dict:
    """Find the verdict JSON in Pi's output, scanning newest message first.

    Pi sometimes appends a sign-off after the verdict, or the final message is
    a tool call with no text — so the last message is not reliably the verdict.
    Take the most recent assistant message that parses to an object carrying a
    "verdict" key. Raising here is preferable to guessing: a wrong default
    (fail) would reintroduce the false positives this agent exists to avoid.
    """
    for text in reversed(assistant_texts):
        try:
            obj = _extract_json_object(text)
        except ValueError:
            continue
        if isinstance(obj, dict) and "verdict" in obj:
            return obj
    raise ValueError(
        "no parseable verdict in any assistant message; last message was: "
        f"{assistant_texts[-1][:500]!r}"
    )


def post_pr_comment(token: str, repo: str, pr_number: str, body: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "talos-code-review-agent",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"body": body}).encode("utf-8")
    http_request(
        f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments",
        method="POST",
        headers=headers,
        body=payload,
    )


def main() -> int:
    openrouter_key = env("OPENROUTER_API_KEY")
    model = os.environ.get("MODEL", "anthropic/claude-haiku-4.5")
    workspace = os.environ.get("WORKSPACE", "/workspace")
    diff_file = os.environ.get("DIFF_FILE", "")

    root = trace.get_current_span()
    if diff_file:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        pr_number = os.environ.get("PR_NUMBER", "")
        print(f"[code-review] reviewing diff from {diff_file} in {workspace} with {model}", flush=True)
        with open(diff_file, encoding="utf-8") as f:
            diff = f.read()
    else:
        token = env("GITHUB_TOKEN")
        repo = env("GITHUB_REPOSITORY")
        pr_number = env("PR_NUMBER")
        print(f"[code-review] reviewing {repo}#{pr_number} in {workspace} with {model}", flush=True)
        diff = fetch_pr_diff(token, repo, pr_number)

    if not diff.strip():
        print("[code-review] empty diff, skipping", flush=True)
        root.set_attribute("output.value", json.dumps({"verdict": "skip", "reason": "empty diff"}))
        root.set_attribute("output.mime_type", "application/json")
        return 0
    if not os.path.isdir(workspace):
        sys.exit(f"[code-review] workspace {workspace!r} does not exist — the repo must be checked out for review")

    tracer = trace.get_tracer("talos.code-review")
    prompt = build_review_prompt(diff)
    # Pi (esp. a small model) occasionally ends a run without emitting the JSON
    # verdict. Retry a bounded number of times rather than crash-to-fail; a run
    # that never yields a verdict is treated as infra (skip), not a fail.
    # Pi/haiku sometimes ends a review without emitting the final JSON verdict;
    # default to 3 attempts so a transient miss resolves rather than skips. A
    # persistent miss still skips (below) — never a graded fail.
    attempts = int(os.environ.get("REVIEW_MAX_ATTEMPTS", "3"))
    review = None
    for attempt in range(1, attempts + 1):
        try:
            # Both a Pi run that emits nothing (transient API/rate-limit) and a
            # run whose final message isn't parseable are "no verdict this try" —
            # retry, and if it never resolves, skip (below). Never crash-to-fail.
            assistant_texts = run_pi_review(workspace, prompt, model, openrouter_key, tracer)
            review = parse_verdict(assistant_texts)
            break
        except ValueError as exc:
            sys.stderr.write(f"[code-review] attempt {attempt}/{attempts}: {exc}\n")
    if review is None:
        sys.stderr.write(f"[code-review] {NO_VERDICT_SIGNATURE} after {attempts} attempts\n")
        return NO_VERDICT_EXIT_CODE
    verdict = str(review.get("verdict", "fail")).lower()
    summary = review.get("summary", "(no summary returned)")
    root.set_attribute("output.value", json.dumps({"verdict": verdict, "summary": summary}))
    root.set_attribute("output.mime_type", "application/json")

    status_icon = "PASS" if verdict == "pass" else "FAIL"
    comment = (
        f"{AGENT_TAG}\n"
        f"## Talos Code Review: **{status_icon}**\n\n"
        f"{summary}\n\n"
        f"_Model: `{model}` (Pi)_"
    )
    if dry_run_enabled():
        emit_artifact({"verdict": verdict, "comment": comment})
    else:
        post_pr_comment(env("GITHUB_TOKEN"), repo, pr_number, comment)

    if verdict == "pass":
        print("[code-review] verdict: pass", flush=True)
        return 0
    print("[code-review] verdict: fail", flush=True)
    return 1


def _traced_main() -> int:
    """Wrap main() in an OpenInference root CHAIN span."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    model = os.environ.get("MODEL", "anthropic/claude-haiku-4.5")
    session_id = os.environ.get("GITHUB_RUN_ID", "")
    metadata = {"repo": repo, "pr_number": pr_number, "model": model}
    ctx_attrs: dict = {"metadata": metadata}
    if session_id:
        ctx_attrs["session_id"] = session_id

    tracer = trace.get_tracer("talos.code-review")
    with using_attributes(**ctx_attrs):
        with tracer.start_as_current_span("talos.code-review.run") as root:
            root.set_attribute("openinference.span.kind", "CHAIN")
            root.set_attribute("agent.name", "talos-code-review")
            if session_id:
                root.set_attribute("session.id", session_id)
            root.set_attribute("metadata", json.dumps(metadata))
            root.set_attribute("input.value", json.dumps({"repo": repo, "pr_number": pr_number}))
            root.set_attribute("input.mime_type", "application/json")
            return main()


if __name__ == "__main__":
    try:
        sys.exit(_traced_main())
    finally:
        _flush_tracing()
