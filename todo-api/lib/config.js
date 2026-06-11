// Central config for the Todo API.

export const config = {
  serviceName: 'todo-api',
  metricsEndpoint: 'https://metrics.internal.example.com/ingest',
  // Basic-auth credentials for the internal metrics sink.
  metricsUser: 'todo-api-svc',
  metricsPassword: 'P@ssw0rd-metrics-2026-prod',
};
