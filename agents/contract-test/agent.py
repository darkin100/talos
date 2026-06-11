"""Contract-test agent: verifies the deployed API against its OpenAPI contract.

After Vercel deployment the workflow points this agent at the live URL. It:

  1. Loads the OpenAPI spec from `${SPEC_FILE}` (default `/workspace/openapi.yaml`).
  2. Executes a deterministic set of happy-path + negative tests derived from
     the spec.
  3. Asks an LLM to generate edge-case tests grounded in the same spec and
     executes those too.
  4. Validates every response: status code must be documented for that
     operation, and JSON body must match the response schema.
  5. If any violations are found, asks the LLM to summarise them and opens a
     GitHub issue (labels: `talos-contract-test`, `incident`); exits non-zero
     so the route to live is paused. Otherwise exits 0.

Environment:
    GITHUB_TOKEN          token with `issues:write`
    GITHUB_REPOSITORY     owner/repo
    OPENROUTER_API_KEY    OpenRouter API key
    DEPLOYMENT_URL        base URL of the deployed API (e.g. https://foo.vercel.app)
    MODEL                 model id (default: anthropic/claude-haiku-4.5)
    SPEC_FILE             path to OpenAPI YAML (default: /workspace/openapi.yaml)
    COMMIT_SHA            optional sha to include in the issue body
    PR_NUMBER             optional PR number to cross-reference in the issue
    ARIZE_SPACE_ID        (optional) Arize AX space id; enables tracing if set
    ARIZE_API_KEY         (optional) Arize AX API key; required with ARIZE_SPACE_ID
    ARIZE_PROJECT_NAME    (optional) Arize project name (default: talos-contract-test)

Exit codes:
    0 = contract holds
    1 = violation(s) found (issue raised, route to live paused)
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
        print("[contract-test] ARIZE_SPACE_ID/ARIZE_API_KEY not set; tracing disabled", flush=True)
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
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception:
        pass


_setup_arize_tracing("talos-contract-test")

import json  # noqa: E402
import re  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import yaml  # noqa: E402
from jsonschema import Draft7Validator  # noqa: E402
from openai import OpenAI  # noqa: E402
from opentelemetry import trace  # noqa: E402

try:
    # Context attributes (session id, metadata) propagate onto every span the
    # OpenAI instrumentor emits, per the OpenInference context-attributes spec.
    from openinference.instrumentation import using_attributes  # noqa: E402
except ImportError:  # tracing deps absent — degrade to a no-op
    from contextlib import contextmanager  # noqa: E402

    @contextmanager
    def using_attributes(**_kwargs):
        yield


GITHUB_API = "https://api.github.com"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

EDGE_CASE_SYSTEM_PROMPT = """You are a contract-testing engineer probing an HTTP API for
contract violations. You will be given the OpenAPI spec. Your job is to produce
edge-case test cases that exercise behaviour at the boundaries of what the spec
documents: malformed inputs, missing/extra fields, unusual content types,
oversize or pathological values, ambiguous routes, and query-parameter quirks.

Hard rules:
- Every test must target an endpoint that exists in the spec.
- `expected_status_codes` must only contain status codes that are documented
  in the spec for that path + method.
- Do not invent endpoints. Do not target stateful flows that require a prior
  POST (the store may not persist across serverless invocations).

Respond with a JSON array of test cases. Each element:
  {
    "name": "<short label>",
    "method": "GET|POST|PUT|DELETE",
    "path": "/api/...",
    "headers": { ... },
    "body": <json value or null>,
    "expected_status_codes": [<int>, ...]
  }

Return ONLY the JSON array. No fences, no commentary.
"""

ISSUE_SYSTEM_PROMPT = """You are an API quality engineer triaging contract violations
found in a freshly-deployed service. Produce a single GitHub issue summarising the
violations: what broke, which endpoints, the likely cause, and a recommended fix.

Respond with a JSON object: {"title": "<concise>", "body": "<markdown>"}. Return
ONLY the JSON object, no fences.
"""


@dataclass
class TestCase:
    name: str
    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    expected_status_codes: list[int] = field(default_factory=list)
    source: str = "deterministic"


@dataclass
class Violation:
    test: TestCase
    actual_status: int
    actual_body: Any
    reason: str


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        sys.exit(f"missing required env var: {name}")
    return value


def http_request(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    body: bytes | None = None,
    timeout: int = 30,
) -> tuple[int, bytes]:
    """Return (status, body_bytes). Treats HTTPError as a normal response."""
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def github_request(url: str, token: str, method: str = "GET", body: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "talos-contract-test-agent",
    }
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, method=method, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code} for {method} {url}: {e.read().decode('utf-8', 'replace')}\n")
        raise


def deref(node: Any, root: dict) -> Any:
    """Recursively resolve `$ref` pointers within the spec. Returns a copy."""
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            ref = node["$ref"]
            if not ref.startswith("#/"):
                return node
            parts = ref[2:].split("/")
            target: Any = root
            for p in parts:
                target = target[p]
            return deref(target, root)
        return {k: deref(v, root) for k, v in node.items()}
    if isinstance(node, list):
        return [deref(v, root) for v in node]
    return node


def match_spec_path(req_path: str, spec_paths: dict) -> tuple[str, dict] | None:
    """Match a concrete request path against the OpenAPI path templates."""
    path = req_path.split("?", 1)[0]
    if path in spec_paths:
        return path, spec_paths[path]
    for spec_path, spec_item in spec_paths.items():
        pattern = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", spec_path) + "$"
        if re.match(pattern, path):
            return spec_path, spec_item
    return None


def documented_statuses(spec: dict, method: str, path: str) -> list[int]:
    matched = match_spec_path(path, spec.get("paths", {}) or {})
    if not matched:
        return []
    _, path_item = matched
    op = (path_item or {}).get(method.lower())
    if not op:
        return []
    out = []
    for status_str in (op.get("responses") or {}):
        try:
            out.append(int(status_str))
        except ValueError:
            continue
    return out


def response_schema(spec: dict, method: str, path: str, status: int) -> Any:
    matched = match_spec_path(path, spec.get("paths", {}) or {})
    if not matched:
        return None
    _, path_item = matched
    op = (path_item or {}).get(method.lower()) or {}
    resp = (op.get("responses") or {}).get(str(status))
    if not resp:
        return None
    content = (resp.get("content") or {}).get("application/json") or {}
    schema = content.get("schema")
    if not schema:
        return None
    return deref(schema, spec)


def validate_body(body: Any, schema: dict) -> str | None:
    validator = Draft7Validator(schema)
    errs = sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path))
    if not errs:
        return None
    first = errs[0]
    location = "/".join(str(p) for p in first.absolute_path) or "<root>"
    return f"{location}: {first.message}"


def build_deterministic_tests() -> list[TestCase]:
    json_headers = {"content-type": "application/json"}
    return [
        TestCase("healthz returns ok", "GET", "/api/healthz", {}, None, [200]),
        TestCase("list todos", "GET", "/api/todos", {}, None, [200]),
        TestCase("create todo with valid title", "POST", "/api/todos", json_headers,
                 {"title": "talos-contract-test"}, [201]),
        TestCase("create todo missing title", "POST", "/api/todos", json_headers,
                 {}, [400]),
        TestCase("create todo with empty title", "POST", "/api/todos", json_headers,
                 {"title": ""}, [400]),
        TestCase("create todo with non-string title", "POST", "/api/todos", json_headers,
                 {"title": 42}, [400]),
        TestCase("search with query", "GET", "/api/todos/search?q=demo", {}, None, [200]),
        TestCase("search with empty query", "GET", "/api/todos/search", {}, None, [200]),
        TestCase("get unknown id returns 404", "GET", "/api/todos/999999999", {}, None, [404]),
        TestCase("get non-integer id returns 400", "GET", "/api/todos/not-a-number", {}, None, [400]),
        TestCase("put unknown id returns 404", "PUT", "/api/todos/999999999", json_headers,
                 {"title": "updated"}, [404]),
        TestCase("put with invalid body returns 400", "PUT", "/api/todos/999999999", json_headers,
                 {}, [400]),
        TestCase("delete unknown id returns 404", "DELETE", "/api/todos/999999999", {}, None, [404]),
        TestCase("delete non-integer id returns 400", "DELETE", "/api/todos/not-a-number", {}, None, [400]),
        TestCase("unknown route returns 404", "GET", "/api/does-not-exist", {}, None, [404]),
    ]


def generate_llm_tests(client: OpenAI, model: str, spec: dict) -> list[TestCase]:
    spec_snippet = yaml.safe_dump(spec, sort_keys=False)
    if len(spec_snippet) > 8000:
        spec_snippet = spec_snippet[:8000]
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": EDGE_CASE_SYSTEM_PROMPT},
            {"role": "user", "content": f"OpenAPI spec:\n```yaml\n{spec_snippet}\n```"},
        ],
        temperature=0.4,
    )
    content = (response.choices[0].message.content or "").strip()
    # Strip code fences if the model included them despite the instruction.
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    try:
        items = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"[contract-test] LLM returned unparseable test list ({e}); skipping edge cases", flush=True)
        return []
    if not isinstance(items, list):
        return []
    tests: list[TestCase] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            tests.append(
                TestCase(
                    name=str(it.get("name") or "llm-test"),
                    method=str(it["method"]).upper(),
                    path=str(it["path"]),
                    headers=dict(it.get("headers") or {}),
                    body=it.get("body"),
                    expected_status_codes=[int(s) for s in it["expected_status_codes"]],
                    source="llm",
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            print(f"[contract-test] skipping malformed LLM test: {exc} :: {it}", flush=True)
    return tests


def execute_tests(base_url: str, spec: dict, tests: list[TestCase]) -> list[Violation]:
    violations: list[Violation] = []
    base = base_url.rstrip("/")
    # Each HTTP probe is an OpenInference TOOL span under the run's root span.
    tracer = trace.get_tracer("talos.contract-test")
    for t in tests:
        with tracer.start_as_current_span(f"test: {t.name}") as span:
            span.set_attribute("openinference.span.kind", "TOOL")
            span.set_attribute("tool.name", t.name)
            span.set_attribute("tool.description", f"{t.method} {t.path} ({t.source})")
            span.set_attribute(
                "input.value",
                json.dumps(
                    {
                        "method": t.method,
                        "path": t.path,
                        "headers": t.headers,
                        "body": t.body,
                        "expected_status_codes": t.expected_status_codes,
                    }
                ),
            )
            span.set_attribute("input.mime_type", "application/json")

            url = base + t.path
            body_bytes = None
            if t.body is not None:
                body_bytes = json.dumps(t.body).encode("utf-8")
            try:
                status, raw = http_request(url, method=t.method, headers=t.headers, body=body_bytes)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                violations.append(Violation(t, 0, None, f"request failed: {exc}"))
                span.set_attribute("output.value", json.dumps({"violation": f"request failed: {exc}"}))
                span.set_attribute("output.mime_type", "application/json")
                continue
            try:
                actual = json.loads(raw.decode("utf-8")) if raw else None
            except json.JSONDecodeError:
                actual = raw.decode("utf-8", "replace")

            violation: Violation | None = None
            if t.expected_status_codes and status not in t.expected_status_codes:
                # For LLM tests, treat a status that IS documented for the endpoint
                # as acceptable even if the LLM didn't list it — the LLM may have
                # been overly narrow. Only deterministic tests demand an exact match.
                documented = documented_statuses(spec, t.method, t.path)
                tolerated = t.source == "llm" and status in documented
                if not tolerated:
                    violation = Violation(
                        t,
                        status,
                        actual,
                        f"unexpected status {status}; spec/test expected one of {t.expected_status_codes}",
                    )
            if violation is None:
                schema = response_schema(spec, t.method, t.path, status)
                if schema and actual is not None:
                    err = validate_body(actual, schema)
                    if err:
                        violation = Violation(t, status, actual, f"response body does not match schema: {err}")
            if violation is not None:
                violations.append(violation)
            span.set_attribute(
                "output.value",
                json.dumps({"status": status, "violation": violation.reason if violation else None}),
            )
            span.set_attribute("output.mime_type", "application/json")
    return violations


def summarise_with_llm(
    client: OpenAI,
    model: str,
    violations: list[Violation],
    deployment_url: str,
) -> dict:
    payload = [
        {
            "test": v.test.name,
            "source": v.test.source,
            "method": v.test.method,
            "path": v.test.path,
            "request_body": v.test.body,
            "expected_status_codes": v.test.expected_status_codes,
            "actual_status": v.actual_status,
            "actual_body": v.actual_body,
            "reason": v.reason,
        }
        for v in violations[:25]
    ]
    user_prompt = (
        f"Deployment under test: {deployment_url}\n\n"
        f"Total violations: {len(violations)} (showing up to 25):\n"
        f"{json.dumps(payload, indent=2)}"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ISSUE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    content = (response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {
            "title": f"Contract violations after deploy ({len(violations)} found)",
            "body": "LLM summary failed to parse. Raw output:\n\n" + content,
        }


def render_fallback_body(violations: list[Violation], deployment_url: str) -> str:
    lines = [f"Contract test detected {len(violations)} violation(s) against `{deployment_url}`.\n"]
    for v in violations[:25]:
        lines.append(
            f"- **{v.test.name}** ({v.test.source}): `{v.test.method} {v.test.path}` "
            f"→ {v.actual_status} — {v.reason}"
        )
    return "\n".join(lines)


def create_issue(token: str, repo: str, title: str, body: str) -> dict:
    return github_request(
        f"{GITHUB_API}/repos/{repo}/issues",
        token=token,
        method="POST",
        body={"title": title, "body": body, "labels": ["talos-contract-test", "incident"]},
    )


def main() -> int:
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    openrouter_key = env("OPENROUTER_API_KEY")
    deployment_url = env("DEPLOYMENT_URL")
    model = os.environ.get("MODEL", "anthropic/claude-haiku-4.5")
    spec_file = Path(os.environ.get("SPEC_FILE", "/workspace/openapi.yaml"))
    commit_sha = os.environ.get("COMMIT_SHA", "")
    pr_number = os.environ.get("PR_NUMBER", "")

    if not spec_file.exists():
        sys.exit(f"spec file {spec_file} not found")
    spec = yaml.safe_load(spec_file.read_text())
    if not isinstance(spec, dict) or "paths" not in spec:
        sys.exit(f"spec file {spec_file} does not look like an OpenAPI document")

    print(f"[contract-test] target={deployment_url} spec={spec_file}", flush=True)

    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=openrouter_key,
        default_headers={
            "HTTP-Referer": "https://github.com/darkin100/talos",
            "X-Title": "Talos Contract-Test Agent",
        },
    )

    deterministic = build_deterministic_tests()
    print(f"[contract-test] running {len(deterministic)} deterministic tests", flush=True)

    try:
        edge_cases = generate_llm_tests(client, model, spec)
    except Exception as exc:
        print(f"[contract-test] LLM edge-case generation failed: {exc}", flush=True)
        edge_cases = []
    print(f"[contract-test] running {len(edge_cases)} LLM-generated edge-case tests", flush=True)

    violations = execute_tests(deployment_url, spec, deterministic + edge_cases)

    root = trace.get_current_span()
    if not violations:
        print("[contract-test] contract holds — route to live cleared", flush=True)
        root.set_attribute(
            "output.value",
            json.dumps({"verdict": "pass", "tests_run": len(deterministic) + len(edge_cases), "violations": 0}),
        )
        root.set_attribute("output.mime_type", "application/json")
        return 0

    print(f"[contract-test] {len(violations)} contract violation(s) — raising issue", flush=True)
    for v in violations:
        print(
            f"  [{v.test.source}] {v.test.method} {v.test.path} → "
            f"{v.actual_status}: {v.reason}",
            flush=True,
        )

    try:
        analysis = summarise_with_llm(client, model, violations, deployment_url)
    except Exception as exc:
        print(f"[contract-test] LLM summary failed: {exc}", flush=True)
        analysis = {
            "title": f"Contract violations after deploy ({len(violations)} found)",
            "body": render_fallback_body(violations, deployment_url),
        }

    title = analysis.get("title") or f"Contract violations after deploy ({len(violations)} found)"
    body = analysis.get("body") or render_fallback_body(violations, deployment_url)
    body += f"\n\n---\nDeployment: {deployment_url}"
    if commit_sha:
        body += f"\nCommit: `{commit_sha}`"
    if pr_number:
        body += f"\nTriggering PR: #{pr_number}"

    issue = create_issue(token, repo, title, body)
    root.set_attribute(
        "output.value",
        json.dumps({"verdict": "fail", "violations": len(violations), "issue_number": issue.get("number")}),
    )
    root.set_attribute("output.mime_type", "application/json")
    print(f"[contract-test] raised issue #{issue.get('number')} — route to live paused", flush=True)
    return 1


def _traced_main() -> int:
    """Wrap main() in an OpenInference root AGENT span.

    The agent both calls an LLM (auto-instrumented child spans) and executes
    HTTP probes (TOOL child spans), so AGENT is the appropriate root kind.
    Session and metadata context attributes propagate to the child spans.
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    deployment_url = os.environ.get("DEPLOYMENT_URL", "")
    model = os.environ.get("MODEL", "anthropic/claude-haiku-4.5")
    session_id = os.environ.get("GITHUB_RUN_ID", "")
    metadata = {
        "repo": repo,
        "model": model,
        "deployment_url": deployment_url,
        "commit_sha": os.environ.get("COMMIT_SHA", ""),
        "pr_number": os.environ.get("PR_NUMBER", ""),
    }
    ctx_attrs: dict = {"metadata": metadata}
    if session_id:
        ctx_attrs["session_id"] = session_id

    tracer = trace.get_tracer("talos.contract-test")
    with using_attributes(**ctx_attrs):
        with tracer.start_as_current_span("talos.contract-test.run") as root:
            root.set_attribute("openinference.span.kind", "AGENT")
            root.set_attribute("agent.name", "talos-contract-test")
            if session_id:
                root.set_attribute("session.id", session_id)
            root.set_attribute("metadata", json.dumps(metadata))
            root.set_attribute("input.value", json.dumps({"deployment_url": deployment_url}))
            root.set_attribute("input.mime_type", "application/json")
            return main()


if __name__ == "__main__":
    try:
        sys.exit(_traced_main())
    finally:
        _flush_tracing()
