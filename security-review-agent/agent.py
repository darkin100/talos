"""Security-review agent: scans a PR diff for security issues.

Same I/O contract as the code-review agent but focused on security findings.
Reads configuration from environment variables (provided by GitHub Actions):

    GITHUB_TOKEN         token with PR write access
    GITHUB_REPOSITORY    owner/repo
    PR_NUMBER            pull request number to review
    OPENROUTER_API_KEY   OpenRouter API key
    MODEL                model id (default: anthropic/claude-sonnet-4-6)
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


_setup_arize_tracing("talos-security-review")

import json
import urllib.error
import urllib.request

from openai import OpenAI

GITHUB_API = "https://api.github.com"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
AGENT_TAG = "<!-- talos:security-review -->"

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


def call_llm(api_key: str, model: str, diff: str) -> dict:
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key,
        default_headers={
            "HTTP-Referer": "https://github.com/darkin100/talos",
            "X-Title": "Talos Security Review Agent",
        },
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"PR diff:\n\n{diff}"},
        ],
        temperature=0.1,
    )
    content = (response.choices[0].message.content or "").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        stripped = content.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
        return json.loads(stripped)


def post_pr_comment(token: str, repo: str, pr_number: str, body: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "talos-security-review-agent",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"body": body}).encode("utf-8")
    http_request(f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments", method="POST", headers=headers, body=payload)


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
    model = os.environ.get("MODEL", "anthropic/claude-sonnet-4-6")

    print(f"[security-review] scanning {repo}#{pr_number} with {model}", flush=True)
    diff = fetch_pr_diff(token, repo, pr_number)
    if not diff.strip():
        print("[security-review] empty diff, skipping", flush=True)
        return 0

    review = call_llm(openrouter_key, model, diff)
    verdict = review.get("verdict", "fail").lower()
    findings = review.get("findings", [])

    # V1 pass criteria: clean security review = no comment posted at all.
    if verdict == "pass" and not findings:
        print("[security-review] verdict: clean (no comment)", flush=True)
        return 0

    status_icon = "PASS" if verdict == "pass" else "FAIL"
    comment = (
        f"{AGENT_TAG}\n"
        f"## Talos Security Review: **{status_icon}**\n\n"
        f"{format_findings(findings)}\n\n"
        f"_Model: `{model}`_"
    )
    post_pr_comment(token, repo, pr_number, comment)

    if verdict == "pass":
        print("[security-review] verdict: pass (with informational findings)", flush=True)
        return 0
    print(f"[security-review] verdict: fail ({len(findings)} findings)", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
