"""Release-notes generator: writes human-friendly notes from a merged PR.

Reads the merged commit range and produces a markdown release. Designed to
run after the PR is merged in the workflow.

    GITHUB_TOKEN         token with releases:write access
    GITHUB_REPOSITORY    owner/repo
    PR_NUMBER            merged pull request number
    OPENROUTER_API_KEY   OpenRouter API key
    MODEL                model id (default: anthropic/claude-sonnet-4-6)
    RELEASE_TAG          optional tag to attach the release to (e.g. v0.1.0)
    ARIZE_SPACE_ID       (optional) Arize AX space id; enables tracing if set
    ARIZE_API_KEY        (optional) Arize AX API key; required with ARIZE_SPACE_ID
    ARIZE_PROJECT_NAME   (optional) Arize project name (default: talos-release-notes)

Outputs:
    - GitHub release (when RELEASE_TAG is set) with generated notes.
    - Always writes notes to /workspace/RELEASE_NOTES.md when /workspace exists.

Exit code: 0 on success, 1 on failure.
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
        print("[release-notes] ARIZE_SPACE_ID/ARIZE_API_KEY not set; tracing disabled", flush=True)
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


_setup_arize_tracing("talos-release-notes")

import json  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from pathlib import Path  # noqa: E402

from openai import OpenAI  # noqa: E402

GITHUB_API = "https://api.github.com"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

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


def call_llm(client: OpenAI, model: str, prompt: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()


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
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=openrouter_key,
        default_headers={
            "HTTP-Referer": "https://github.com/darkin100/talos",
            "X-Title": "Talos Release Notes Agent",
        },
    )
    notes = call_llm(client, model, prompt)

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
    try:
        sys.exit(main())
    finally:
        _flush_tracing()
