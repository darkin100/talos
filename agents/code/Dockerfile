FROM node:24-slim

WORKDIR /agent

# Pi is a Node CLI; the orchestrator is Python. Install both, plus git for the
# commit/push step, gh for the GitHub API calls, and ca-certificates for the
# OpenRouter + GitHub TLS calls.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      python3-venv \
      git \
      curl \
      gnupg \
      ca-certificates \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | tee /usr/share/keyrings/githubcli-archive-keyring.gpg > /dev/null \
 && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends gh \
 && apt-get purge -y --auto-remove gnupg \
 && rm -rf /var/lib/apt/lists/*

# Pi coding agent CLI (pi.dev). --ignore-scripts mirrors the official install
# instructions and avoids running upstream postinstall hooks at image-build
# time. The CLI binary lands on PATH as `pi`.
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent

# Python tracing deps mirror the other agents (Arize AX + OpenInference). We
# don't use the OpenAI client here, but keeping the dep set identical makes
# the image swap-compatible if we later need to call the LLM directly.
RUN pip install --no-cache-dir --break-system-packages \
      arize-otel \
      openinference-instrumentation-openai \
      opentelemetry-api \
      opentelemetry-sdk

COPY agent.py ./

ENTRYPOINT ["python3", "/agent/agent.py"]
