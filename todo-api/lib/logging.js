// Single-line JSON log emitter — same shape as the previous Go API so the
// RCA agent's `scan_log_file` heuristics still match.

export function logEvent(level, message, fields = {}) {
  const entry = {
    timestamp: new Date().toISOString(),
    level,
    message,
    service: 'todo-api',
    ...fields,
  };
  console.log(JSON.stringify(entry));
}
