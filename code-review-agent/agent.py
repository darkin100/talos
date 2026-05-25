"""Code-review agent: reviews a PR diff with an LLM and comments on the PR.

Reads configuration from environment variables (provided by GitHub Actions):

    GITHUB_TOKEN         token with PR write access
    GITHUB_REPOSITORY    owner/repo (e.g. darkin100/talos)
    PR_NUMBER            pull request number to review
    OPENROUTER_API_KEY   OpenRouter API key for LLM access
    MODEL                model id (default: deepseek/deepseek-v4-flash)
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
    """Initialise Arize AX tracing for the OpenAI/OpenRouter client.

    Must run before `openai` is imported so the instrumentor can patch the SDK.
    No-ops if ARIZE_SPACE_ID/ARIZE_API_KEY are not set.
    """
    space_id = os.environ.get("ARIZE_SPACE_ID")
    api_key = os.environ.get("ARIZE_API_KEY")
    if not space_id or not api_key:
        print("[code-review] ARIZE_SPACE_ID/ARIZE_API_KEY not set; tracing disabled", flush=True)
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


_setup_arize_tracing("talos-code-review")

import json  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

from openai import OpenAI  # noqa: E402

GITHUB_API = "https://api.github.com"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
AGENT_TAG = "<!-- talos:code-review -->"

SYSTEM_PROMPT = """You are a senior software engineer performing a code review.
Review the supplied unified diff and respond with a single JSON object of the form:

    {"verdict": "pass" | "fail", "summary": "<one-paragraph review>"}

Rules:
- "fail" means the change introduces a real defect, missing test, incorrect logic,
  or a clear maintainability problem worth blocking on.
- Style nits, naming preferences, or speculative refactors are NOT failures.
- Keep the summary concise (under 250 words) and reference specific files/lines
  where useful. Return ONLY the JSON object, no markdown fences.
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
        "User-Agent": "talos-code-review-agent",
    }
    data = http_request(f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}", headers=headers)
    return data.decode("utf-8", "replace")


def call_llm(client: OpenAI, model: str, diff: str) -> dict:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"PR diff:\n\n{diff}"},
        ],
        temperature=0.2,
    )
    content = (response.choices[0].message.content or "").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # If the model wrapped the JSON in fences, strip them and retry.
        stripped = content.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
        return json.loads(stripped)


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
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    pr_number = env("PR_NUMBER")
    openrouter_key = env("OPENROUTER_API_KEY")
    model = os.environ.get("MODEL", "deepseek/deepseek-v4-flash")

    print(f"[code-review] reviewing {repo}#{pr_number} with {model}", flush=True)
    diff = fetch_pr_diff(token, repo, pr_number)
    if not diff.strip():
        print("[code-review] empty diff, skipping", flush=True)
        return 0

    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=openrouter_key,
        default_headers={
            "HTTP-Referer": "https://github.com/darkin100/talos",
            "X-Title": "Talos Code Review Agent",
        },
    )
    review = call_llm(client, model, diff)
    verdict = review.get("verdict", "fail").lower()
    summary = review.get("summary", "(no summary returned)")

    status_icon = "PASS" if verdict == "pass" else "FAIL"
    comment = (
        f"{AGENT_TAG}\n"
        f"## Talos Code Review: **{status_icon}**\n\n"
        f"{summary}\n\n"
        f"_Model: `{model}`_"
    )
    post_pr_comment(token, repo, pr_number, comment)

    if verdict == "pass":
        print("[code-review] verdict: pass", flush=True)
        return 0
    print("[code-review] verdict: fail", flush=True)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _flush_tracing()
