"""Release-notes generator: writes human-friendly notes from a merged PR.

Reads the merged commit range and produces a markdown release. Designed to
run after the PR is merged in the workflow.

    GITHUB_TOKEN         token with releases:write access
    GITHUB_REPOSITORY    owner/repo
    PR_NUMBER            merged pull request number
    OPENROUTER_API_KEY   OpenRouter API key
    MODEL                model id (default: anthropic/claude-sonnet-4-6)
    RELEASE_TAG          optional tag to attach the release to (e.g. v0.1.0)

Outputs:
    - GitHub release (when RELEASE_TAG is set) with generated notes.
    - Always writes notes to /workspace/RELEASE_NOTES.md when /workspace exists.

Exit code: 0 on success, 1 on failure.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_API = "https://api.github.com"
OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a technical writer producing release notes for an
engineering audience. Given the PR title, body and commit messages, write
concise markdown release notes with these sections (omit empty ones):

    ## Summary
    ## Changes
    ## Notes for operators

Keep it under 300 words. Return ONLY the markdown, no preamble.
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


def github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "talos-release-notes-agent",
    }


def fetch_pr(token: str, repo: str, pr_number: str) -> dict:
    return json.loads(http_request(f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}", headers=github_headers(token)))


def fetch_pr_commits(token: str, repo: str, pr_number: str) -> list[dict]:
    return json.loads(http_request(f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/commits", headers=github_headers(token)))


def call_llm(api_key: str, model: str, prompt: str) -> str:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/darkin100/talos",
        "X-Title": "Talos Release Notes Agent",
    }
    raw = http_request(OPENROUTER_API, method="POST", headers=headers, body=body)
    return json.loads(raw)["choices"][0]["message"]["content"].strip()


def create_release(token: str, repo: str, tag: str, name: str, body: str) -> None:
    headers = github_headers(token) | {"Content-Type": "application/json"}
    payload = json.dumps({"tag_name": tag, "name": name, "body": body, "draft": False, "prerelease": False}).encode("utf-8")
    http_request(f"{GITHUB_API}/repos/{repo}/releases", method="POST", headers=headers, body=payload)


def main() -> int:
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    pr_number = env("PR_NUMBER")
    openrouter_key = env("OPENROUTER_API_KEY")
    model = os.environ.get("MODEL", "anthropic/claude-sonnet-4-6")
    release_tag = os.environ.get("RELEASE_TAG", "")

    print(f"[release-notes] generating for {repo}#{pr_number}", flush=True)
    pr = fetch_pr(token, repo, pr_number)
    commits = fetch_pr_commits(token, repo, pr_number)
    commit_lines = "\n".join(f"- {c['commit']['message'].splitlines()[0]}" for c in commits)

    prompt = (
        f"PR title: {pr.get('title', '')}\n\n"
        f"PR body:\n{pr.get('body') or '(empty)'}\n\n"
        f"Commits:\n{commit_lines}\n"
    )
    notes = call_llm(openrouter_key, model, prompt)

    workspace = Path("/workspace")
    if workspace.exists():
        output = workspace / "RELEASE_NOTES.md"
        output.write_text(notes + "\n", encoding="utf-8")
        print(f"[release-notes] wrote {output}", flush=True)
    else:
        print(notes, flush=True)

    if release_tag:
        name = f"{release_tag} — PR #{pr_number}"
        create_release(token, repo, release_tag, name, notes)
        print(f"[release-notes] created release {release_tag}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
