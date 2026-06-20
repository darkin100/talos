<!-- talos:code-review -->
## Talos Code Review: **FAIL**

The config file contains hardcoded credentials (metricsPassword: 'P@ssw0rd-metrics-2026-prod') directly in source code, which is a critical security vulnerability. Credentials should never be committed to version control; they must be loaded from environment variables, secure vaults (e.g., AWS Secrets Manager, HashiCorp Vault), or configuration management systems. This exposes the production metrics service to unauthorized access and violates security best practices. Additionally, the metricsUser should also be externalized. The file should be refactored to use environment variables (e.g., `process.env.METRICS_PASSWORD`) or a secrets management solution before merging.

_Model: `anthropic/claude-haiku-4.5`_
