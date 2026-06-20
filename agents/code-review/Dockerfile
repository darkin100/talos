FROM node:24-slim

WORKDIR /agent

# The reviewer drives the Pi coding agent (a Node CLI) so it can read the full
# files a diff touches, not just the diff. The orchestrator is Python. Install
# both, plus git for read-only repo inspection and ca-certificates for the
# OpenRouter/GitHub TLS calls.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      python3-venv \
      git \
      curl \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Pi coding agent CLI (pi.dev). --ignore-scripts mirrors the official install
# instructions and avoids running upstream postinstall hooks at image-build
# time. The CLI binary lands on PATH as `pi`.
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent

# Python tracing deps (Arize AX + OpenInference). Pi runs as a subprocess, so
# we reconstruct spans from its event stream rather than auto-instrumenting an
# OpenAI client — the openai package is no longer needed.
RUN pip install --no-cache-dir --break-system-packages \
      arize-otel \
      openinference-instrumentation-openai \
      opentelemetry-api \
      opentelemetry-sdk

COPY agent.py ./

ENTRYPOINT ["python3", "/agent/agent.py"]
