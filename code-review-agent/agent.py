"""Code-review agent: reviews a PR diff with an LLM and comments on the PR.

Reads configuration from environment variables (provided by GitHub Actions):

    GITHUB_TOKEN         token with PR write access
    GITHUB_REPOSITORY    owner/repo (e.g. darkin100/talos)
    PR_NUMBER            pull request number to review
    OPENROUTER_API_KEY   OpenRouter API key for LLM access
    MODEL                model id (default: anthropic/claude-sonnet-4-6)

Exit codes:
    0 = pass  (no significant feedback posted)
    1 = fail  (significant issues found and commented on the PR)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

GITHUB_API = "https://api.github.com"
OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"
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


def call_llm(api_key: str, model: str, diff: str) -> dict:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"PR diff:\n\n{diff}"},
            ],
            "temperature": 0.2,
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/darkin100/talos",
        "X-Title": "Talos Code Review Agent",
    }
    raw = http_request(OPENROUTER_API, method="POST", headers=headers, body=body)
    response = json.loads(raw)
    content = response["choices"][0]["message"]["content"].strip()
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
    model = os.environ.get("MODEL", "anthropic/claude-sonnet-4-6")

    print(f"[code-review] reviewing {repo}#{pr_number} with {model}", flush=True)
    diff = fetch_pr_diff(token, repo, pr_number)
    if not diff.strip():
        print("[code-review] empty diff, skipping", flush=True)
        return 0

    review = call_llm(openrouter_key, model, diff)
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
    sys.exit(main())
