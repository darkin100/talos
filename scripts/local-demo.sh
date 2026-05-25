#!/usr/bin/env bash
# local-demo.sh — run the end-to-end Talos workflow locally.
#
# This mirrors the GitHub Actions workflow but executes against a local Docker
# daemon so the conference demo doesn't need self-hosted runners.
#
# Configuration is loaded from a .env file at the repo root (overridable via
# ENV_FILE=... ./scripts/local-demo.sh ...). Variables already set in the
# environment win over .env entries, so secrets can still be injected by CI.
#
# Required variables (in .env or environment):
#   GITHUB_TOKEN          PAT with PR/issue write access on darkin100/talos
#   OPENROUTER_API_KEY    OpenRouter API key
#   PR_NUMBER             PR to review (for review steps)
#   GITHUB_REPOSITORY     defaults to darkin100/talos
#
# Usage:
#   scripts/local-demo.sh review     # run code-review + security-review
#   scripts/local-demo.sh deploy     # deploy stack + run release-notes + RCA
#   scripts/local-demo.sh teardown   # stop & remove stack
#   scripts/local-demo.sh all        # review -> deploy -> teardown

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
if [ -f "$ENV_FILE" ]; then
  echo "==> Loading env from $ENV_FILE"
  # Read line-by-line so values with `=` or whitespace survive; do not override
  # variables already present in the shell environment.
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    key="${line%%=*}"
    value="${line#*=}"
    # Trim surrounding quotes if present.
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    if [ -z "${!key:-}" ]; then
      export "$key=$value"
    fi
  done < "$ENV_FILE"
fi

GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-darkin100/talos}"

need() {
  local var="$1"
  if [ -z "${!var:-}" ]; then
    echo "error: required env var $var is not set" >&2
    exit 1
  fi
}

build_agents() {
  echo "==> Building agent images"
  docker build -t talos/code-review:v1     ./code-review-agent
  docker build -t talos/security-review:v1 ./security-review-agent
  docker build -t talos/release-notes:v1   ./release-notes
  docker build -t talos/rca:v1             ./rca-agent
}

review() {
  need GITHUB_TOKEN; need OPENROUTER_API_KEY; need PR_NUMBER
  build_agents
  echo "==> Running code-review agent"
  docker run --rm \
    -e GITHUB_TOKEN -e OPENROUTER_API_KEY \
    -e ARIZE_SPACE_ID="${ARIZE_SPACE_ID:-}" \
    -e ARIZE_API_KEY="${ARIZE_API_KEY:-}" \
    -e GITHUB_REPOSITORY="$GITHUB_REPOSITORY" -e PR_NUMBER="$PR_NUMBER" \
    talos/code-review:v1
  echo "==> Running security-review agent"
  docker run --rm \
    -e GITHUB_TOKEN -e OPENROUTER_API_KEY \
    -e ARIZE_SPACE_ID="${ARIZE_SPACE_ID:-}" \
    -e ARIZE_API_KEY="${ARIZE_API_KEY:-}" \
    -e GITHUB_REPOSITORY="$GITHUB_REPOSITORY" -e PR_NUMBER="$PR_NUMBER" \
    talos/security-review:v1
}

deploy() {
  need GITHUB_TOKEN; need OPENROUTER_API_KEY
  build_agents
  echo "==> Building Todo API image"
  docker build -t talos/todo:v1 ./hello-world
  echo "==> Starting Todo API"
  docker rm -f talos-todo >/dev/null 2>&1 || true
  docker run -d --name talos-todo \
    -p 8080:8080 \
    -e PORT=8080 \
    talos/todo:v1 >/dev/null

  echo "==> Waiting for Todo API"
  for i in $(seq 1 30); do
    if curl -fsS http://localhost:8080/healthz >/dev/null 2>&1; then
      echo "    healthy"; break
    fi
    sleep 2
  done

  echo "==> Smoke traffic"
  curl -fsS -X POST http://localhost:8080/todos \
    -H 'content-type: application/json' -d '{"title":"demo"}' | sed 's/^/    /'
  curl -fsS http://localhost:8080/todos | sed 's/^/    /'

  if [ -n "${PR_NUMBER:-}" ]; then
    echo "==> Generating release notes for PR #$PR_NUMBER"
    docker run --rm \
      -v "$ROOT_DIR:/workspace" \
      -e GITHUB_TOKEN -e OPENROUTER_API_KEY \
      -e ARIZE_SPACE_ID="${ARIZE_SPACE_ID:-}" \
      -e ARIZE_API_KEY="${ARIZE_API_KEY:-}" \
      -e GITHUB_REPOSITORY="$GITHUB_REPOSITORY" -e PR_NUMBER="$PR_NUMBER" \
      talos/release-notes:v1
  else
    echo "==> Skipping release notes (set PR_NUMBER to enable)"
  fi

  echo "==> Capturing application logs"
  mkdir -p .logs
  docker logs talos-todo > .logs/app.log 2>&1 || true

  echo "==> Running RCA agent"
  set +e
  docker run --rm \
    -v "$ROOT_DIR/hello-world:/workspace:ro" \
    -v "$ROOT_DIR/.logs:/logs:ro" \
    -e GITHUB_TOKEN -e OPENROUTER_API_KEY \
    -e ARIZE_SPACE_ID="${ARIZE_SPACE_ID:-}" \
    -e ARIZE_API_KEY="${ARIZE_API_KEY:-}" \
    -e GITHUB_REPOSITORY="$GITHUB_REPOSITORY" \
    -e PHOENIX_URL="${PHOENIX_URL:-}" \
    -e PR_NUMBER="${PR_NUMBER:-}" \
    talos/rca:v1
  RCA_EXIT=$?
  set -e
  if [ $RCA_EXIT -ne 0 ]; then
    echo "==> RCA detected errors — route to live paused (exit $RCA_EXIT)"
    return $RCA_EXIT
  fi
  echo "==> RCA clean"
}

teardown() {
  echo "==> Tearing down Todo API"
  docker rm -f talos-todo || true
}

case "${1:-}" in
  review)   review ;;
  deploy)   deploy ;;
  teardown) teardown ;;
  all)      review && deploy ; teardown ;;
  *)        echo "usage: $0 {review|deploy|teardown|all}" >&2; exit 2 ;;
esac
