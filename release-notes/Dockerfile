FROM python:3.12-slim

WORKDIR /agent
RUN pip install --no-cache-dir arize-otel openinference-instrumentation-openai openai
COPY agent.py ./

ENTRYPOINT ["python", "/agent/agent.py"]
