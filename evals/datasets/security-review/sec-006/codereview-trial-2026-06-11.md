<!-- talos:code-review -->
## Talos Code Review: **FAIL**

The change introduces a security vulnerability by accepting user input directly as a RegExp pattern without escaping. If a user provides special regex characters (e.g., `.*`, `[a-z]`, `(foo|bar)`), it will be interpreted as regex syntax rather than literal text. This breaks the expected search behavior and could enable ReDoS (Regular Expression Denial of Service) attacks. The original implementation using `toLowerCase().includes()` was safer for a simple substring search. If regex support is genuinely needed, the input should be escaped using `RegExp.escape()` (or a polyfill for older Node versions) or the feature should be explicitly documented with clear warnings about regex syntax. Additionally, there are no tests shown for this new regex behavior, making it difficult to verify correctness or catch regressions.

_Model: `anthropic/claude-haiku-4.5`_
