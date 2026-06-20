<!-- talos:code-review -->
## Talos Code Review: **FAIL**

This change introduces a security vulnerability by switching from `textContent` to `innerHTML` for rendering todo titles. While the comment suggests this enables rich HTML rendering (links/emphasis), it creates an XSS attack vector if todo titles come from user input or untrusted sources. An attacker could inject malicious scripts via a todo title. The change lacks any sanitization mechanism (e.g., DOMPurify) to safely parse HTML. If rich text rendering is genuinely needed, the proper approach is to either: (1) use a sanitization library, (2) parse and validate the HTML content, or (3) use a templating engine with built-in escaping. The comment alone doesn't justify the security risk introduced.

_Model: `anthropic/claude-haiku-4.5`_
