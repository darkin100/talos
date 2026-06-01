"""Security-review agent: scans a PR diff for security issues.

Same I/O contract as the code-review agent but focused on security findings.
Reads configuration from environment variables (provided by GitHub Actions):

    GITHUB_TOKEN         token with PR write access
    GITHUB_REPOSITORY    owner/repo
    PR_NUMBER            pull request number to review
    OPENROUTER_API_KEY   OpenRouter API key
    MODEL                model id (default: anthropic/claude-haiku-4.5)
    ARIZE_SPACE_ID       (optional) Arize AX space id; enables tracing if set
    ARIZE_API_KEY        (optional) Arize AX API key; required with ARIZE_SPACE_ID
    ARIZE_PROJECT_NAME   (optional) Arize project name (default: talos-security-review)

Exit codes:
    0 = clean (no comment posted)
    1 = security issue(s) found (comment posted, workflow blocked)
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
        print("[security-review] ARIZE_SPACE_ID/ARIZE_API_KEY not set; tracing disabled", flush=True)
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


_setup_arize_tracing("talos-security-review")

import json  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

from openai import OpenAI  # noqa: E402

GITHUB_API = "https://api.github.com"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
AGENT_TAG = "<!-- talos:security-review -->"
IGNORE_FILE_PATH = "/workspace/.github/security-review-ignore"
FAIL_SEVERITIES = {"medium", "high", "critical"}

SYSTEM_PROMPT = """You are a security engineer reviewing a pull request diff.
Look for OWASP-class issues, secret leaks, unsafe deserialization, command/SQL
injection, broken authentication, insecure crypto, and similar real defects.

Respond with a single JSON object:

    {"verdict": "pass" | "fail", "findings": [{"severity": "low|medium|high|critical", "title": "...", "detail": "..."}]}

Rules:
- "fail" only when at least one finding is medium or higher severity.
- Theoretical concerns without a concrete vector are NOT findings.
- Return ONLY the JSON object, no markdown fences.
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


def fetch_pr_diff(token: str, repo: str, pr_number: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": "talos-security-review-agent",
    }
    return http_request(f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}", headers=headers).decode("utf-8", "replace")


def _extract_json_object(content: str) -> dict:
    """Extract the first JSON object from a model response.

    Models sometimes wrap JSON in ``` fences and/or surround it with prose.
    Find the first '{' and use raw_decode to consume one JSON value, ignoring
    any trailing text. Raises ValueError loud if no object is present.

    Safety note: the stdlib `json` module decodes only JSON primitives,
    lists, and dicts — it does not deserialize arbitrary Python objects
    (it is not `pickle`), so `raw_decode` of untrusted LLM output cannot
    execute code or instantiate classes. Trailing content after the first
    object is intentionally discarded; the consumer only reads `verdict`
    and `findings` from the returned dict, so a smuggled second object
    would have no execution path.
    """
    s = content.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl >= 0:
            s = s[nl + 1 :]
    start = s.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in model response: {content!r}")
    obj, _ = json.JSONDecoder().raw_decode(s[start:])
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object, got {type(obj).__name__}: {content!r}")
    return obj


def call_llm(client: OpenAI, model: str, diff: str) -> dict:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"PR diff:\n\n{diff}"},
        ],
        temperature=0.1,
    )
    return _extract_json_object((response.choices[0].message.content or "").strip())


def post_pr_comment(token: str, repo: str, pr_number: str, body: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "talos-security-review-agent",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"body": body}).encode("utf-8")
    http_request(f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments", method="POST", headers=headers, body=payload)


def load_ignore_patterns(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.readlines()
    except FileNotFoundError:
        return []
    patterns: list[str] = []
    for line in raw:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        patterns.append(s.lower())
    return patterns


def is_suppressed(finding: dict, patterns: list[str]) -> bool:
    if not patterns:
        return False
    hay = f"{finding.get('title', '')}\n{finding.get('detail', '')}".lower()
    return any(p in hay for p in patterns)


def format_findings(findings: list[dict]) -> str:
    if not findings:
        return "_No findings._"
    lines = []
    for f in findings:
        sev = f.get("severity", "unknown").upper()
        title = f.get("title", "(untitled)")
        detail = f.get("detail", "")
        lines.append(f"- **[{sev}] {title}** — {detail}")
    return "\n".join(lines)


def main() -> int:
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    pr_number = env("PR_NUMBER")
    openrouter_key = env("OPENROUTER_API_KEY")
    model = os.environ.get("MODEL", "anthropic/claude-haiku-4.5")

    print(f"[security-review] scanning {repo}#{pr_number} with {model}", flush=True)
    diff = fetch_pr_diff(token, repo, pr_number)
    if not diff.strip():
        print("[security-review] empty diff, skipping", flush=True)
        return 0

    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=openrouter_key,
        default_headers={
            "HTTP-Referer": "https://github.com/darkin100/talos",
            "X-Title": "Talos Security Review Agent",
        },
    )
    review = call_llm(client, model, diff)
    raw_findings = review.get("findings", [])

    ignore_patterns = load_ignore_patterns(IGNORE_FILE_PATH)
    if ignore_patterns:
        print(
            f"[security-review] loaded {len(ignore_patterns)} ignore pattern(s) from {IGNORE_FILE_PATH}",
            flush=True,
        )
    kept = [f for f in raw_findings if not is_suppressed(f, ignore_patterns)]
    suppressed = [f for f in raw_findings if is_suppressed(f, ignore_patterns)]

    # Verdict is recomputed locally so suppressions actually unblock the build,
    # regardless of what the LLM returned.
    has_blocking = any(f.get("severity", "").lower() in FAIL_SEVERITIES for f in kept)
    verdict = "fail" if has_blocking else "pass"

    # V1 pass criteria: clean security review = no comment posted at all.
    if verdict == "pass" and not kept and not suppressed:
        print("[security-review] verdict: clean (no comment)", flush=True)
        return 0

    status_icon = "PASS" if verdict == "pass" else "FAIL"
    sections = [
        AGENT_TAG,
        f"## Talos Security Review: **{status_icon}**",
        "",
        format_findings(kept),
    ]
    if suppressed:
        sections.extend(
            [
                "",
                "<details><summary>Suppressed findings</summary>",
                "",
                format_findings(suppressed),
                "",
                "_Suppressed by `.github/security-review-ignore`._",
                "</details>",
            ]
        )
    sections.extend(["", f"_Model: `{model}`_"])
    post_pr_comment(token, repo, pr_number, "\n".join(sections))

    if verdict == "pass":
        print(
            f"[security-review] verdict: pass ({len(kept)} kept, {len(suppressed)} suppressed)",
            flush=True,
        )
        return 0
    print(
        f"[security-review] verdict: fail ({len(kept)} kept, {len(suppressed)} suppressed)",
        flush=True,
    )
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _flush_tracing()
