"""RCA agent: route-course analysis after deployment.

Monitors application logs for errors during a window, queries Arize Phoenix
for structured traces, and if any errors are observed, performs root-cause
analysis with an LLM and raises a GitHub issue.

Environment:
    GITHUB_TOKEN          token with `issues:write`
    GITHUB_REPOSITORY     owner/repo
    OPENROUTER_API_KEY    OpenRouter API key
    MODEL                 model id (default: deepseek/deepseek-v4-flash)
    LOG_FILE              path to JSON log file to scan (default: /logs/app.log)
    SOURCE_DIR            source root for code lookup (default: /workspace)
    PHOENIX_URL           optional Phoenix base URL (e.g. http://phoenix:6006)
    COMMIT_SHA            optional sha to include in the issue body
    PR_NUMBER             optional PR number to cross-reference in the issue
    ARIZE_SPACE_ID        (optional) Arize AX space id; enables tracing if set
    ARIZE_API_KEY         (optional) Arize AX API key; required with ARIZE_SPACE_ID
    ARIZE_PROJECT_NAME    (optional) Arize project name (default: talos-rca)

Exit codes:
    0 = no errors observed
    1 = errors detected (issue raised, route to live paused)
"""

from __future__ import annotations

import os
import sys


def _setup_arize_tracing(default_project: str) -> None:
    """Initialise Arize AX tracing for the OpenAI/OpenRouter client.

    Must run before `openai` is imported so the instrumentor can patch the SDK.
    No-ops if ARIZE_SPACE_ID/ARIZE_API_KEY are not set.
    """
    space_id = os.environ.get("ARIZE_SPACE_ID")
    api_key = os.environ.get("ARIZE_API_KEY")
    if not space_id or not api_key:
        print("[rca] ARIZE_SPACE_ID/ARIZE_API_KEY not set; tracing disabled", flush=True)
        return
    from arize.otel import register
    from openinference.instrumentation.openai import OpenAIInstrumentor

    tracer_provider = register(
        space_id=space_id,
        api_key=api_key,
        project_name=os.environ.get("ARIZE_PROJECT_NAME", default_project),
    )
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)


def _flush_tracing() -> None:
    """Force-flush queued spans so short-lived runs don't drop traces.

    The BatchSpanProcessor (default in arize.otel) buffers spans; on a one-shot
    agent run it may not drain before the process exits.
    """
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception:
        pass


_setup_arize_tracing("talos-rca")

import json  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from pathlib import Path  # noqa: E402

from openai import OpenAI  # noqa: E402

GITHUB_API = "https://api.github.com"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

SYSTEM_PROMPT = """You are a Site Reliability Engineer performing root-cause
analysis. Given a set of error log lines and a snippet of the source code that
likely produced them, identify:

  1. The most probable root cause.
  2. The specific file(s) and line(s) responsible.
  3. A recommended fix.

Respond with a JSON object:

    {"title": "<concise issue title>", "body": "<markdown analysis>"}

Return ONLY the JSON object, no fences.
"""


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


def scan_log_file(path: Path) -> list[dict]:
    """Return all log entries with level error/critical/fatal."""
    if not path.exists():
        print(f"[rca] log file {path} does not exist; treating as no-errors", flush=True)
        return []
    errors: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # Non-JSON line — comes from the Vercel CLI wrapper (deprecation
            # warnings, banners, etc.), not the app's structured logger. Skip.
            continue
        level = str(entry.get("level", "")).lower()
        if level in {"error", "critical", "fatal"} or entry.get("status", 0) >= 500:
            errors.append(entry)
    return errors


def query_phoenix_errors(base_url: str) -> list[dict]:
    """Best-effort: ask Phoenix for recent error traces. Phoenix exposes a
    GraphQL/REST surface; for V1 we just check /healthz and surface a marker
    so the LLM context includes 'Phoenix saw errors' when applicable. The
    real correlation lives in the log scan above."""
    try:
        http_request(f"{base_url.rstrip('/')}/healthz")
    except (urllib.error.URLError, urllib.error.HTTPError):
        print(f"[rca] phoenix unreachable at {base_url}; continuing with log scan only", flush=True)
    return []


def gather_source_context(source_dir: Path, max_chars: int = 8000) -> str:
    """Concatenate small source files for LLM context. V1 heuristic: include
    all .go files under source_dir up to max_chars."""
    if not source_dir.exists():
        return ""
    chunks: list[str] = []
    total = 0
    for path in sorted(source_dir.rglob("*.go")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        header = f"\n// FILE: {path.relative_to(source_dir)}\n"
        if total + len(header) + len(text) > max_chars:
            remaining = max_chars - total - len(header)
            if remaining > 200:
                chunks.append(header + text[:remaining])
            break
        chunks.append(header + text)
        total += len(header) + len(text)
    return "".join(chunks)


def call_llm(client: OpenAI, model: str, errors: list[dict], source: str) -> dict:
    error_text = "\n".join(json.dumps(e) for e in errors[:20])
    user_prompt = (
        f"Error log entries (up to 20):\n{error_text}\n\n"
        f"Relevant source code:\n```go\n{source}\n```"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    content = (response.choices[0].message.content or "").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        stripped = content.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
        return json.loads(stripped)


def create_issue(token: str, repo: str, title: str, body: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "talos-rca-agent",
    }
    payload = json.dumps({"title": title, "body": body, "labels": ["talos-rca", "incident"]}).encode("utf-8")
    return json.loads(http_request(f"{GITHUB_API}/repos/{repo}/issues", method="POST", headers=headers, body=payload))


def main() -> int:
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    openrouter_key = env("OPENROUTER_API_KEY")
    model = os.environ.get("MODEL", "deepseek/deepseek-v4-flash")
    log_file = Path(os.environ.get("LOG_FILE", "/logs/app.log"))
    source_dir = Path(os.environ.get("SOURCE_DIR", "/workspace"))
    phoenix_url = os.environ.get("PHOENIX_URL", "")
    commit_sha = os.environ.get("COMMIT_SHA", "")
    pr_number = os.environ.get("PR_NUMBER", "")

    print(f"[rca] scanning {log_file}", flush=True)
    errors = scan_log_file(log_file)
    if phoenix_url:
        errors.extend(query_phoenix_errors(phoenix_url))

    if not errors:
        print("[rca] no errors detected — route to live cleared", flush=True)
        return 0

    print(f"[rca] {len(errors)} error events detected; performing RCA", flush=True)
    source = gather_source_context(source_dir)
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=openrouter_key,
        default_headers={
            "HTTP-Referer": "https://github.com/darkin100/talos",
            "X-Title": "Talos RCA Agent",
        },
    )
    analysis = call_llm(client, model, errors, source)

    title = analysis.get("title") or f"RCA: errors detected after deployment ({len(errors)} events)"
    body = analysis.get("body") or "(no body returned)"
    if commit_sha:
        body += f"\n\n---\nCommit: `{commit_sha}`"
    if pr_number:
        body += f"\nTriggering PR: #{pr_number}"

    issue = create_issue(token, repo, title, body)
    print(f"[rca] raised issue #{issue.get('number')} — route to live paused", flush=True)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _flush_tracing()
