# Arthur — Domain Vocabulary & Context

This glossary defines the shared domain vocabulary and architectural seams of the **Arthur** headless Chromium runtime.

---

## Domain Concepts

### 1. Browser & Tabs
- **`Browser`**: The top-level synchronous runtime facade exposed to AI agents and the REPL. Manages browser process lifecycle and delegates actions to the active tab.
- **`Tab`**: A synchronous proxy to an attached page target (`sessionId`), exposing navigation, semantic snapshot inspection, element querying, and synthetic interactions.
- **`TabManager`**: The internal lifecycle tracker mapping CDP `targetId`s to sequential integer IDs, session attachments, URLs, and active tab pointers.

### 2. DOM Engine & Ref-IDs
- **`DOM Engine`**: The in-page JavaScript runtime (`window.__arthur_dom_op`) that parses the accessible DOM tree, evaluates WAI-ARIA roles/names, and maintains interactive element coordinates.
- **`Ref-ID`**: A deterministic integer reference (formatted canonically as `[#1]`, `[#2]`) assigned to actionable DOM nodes in a snapshot outline, enabling token-efficient agent targeting without XPath/CSS selectors.
- **`Target Reference`**: Polymorphic target specifier accepted by all interaction methods: numeric Ref-ID (`1`), string Ref-ID (`"[#1]"` or `"#1"`), or CSS selector (`"button.submit"`).
- **`Diagnostic Auto-Snapshot`**: An automatic lightweight semantic DOM outline captured and attached to exception payloads when a REPL command fails, allowing single-turn self-healing.

### 3. CDP Transport & Input
- **`CDPClient`**: Asynchronous, thread-safe Chrome DevTools Protocol WebSocket transport with numeric request/response multiplexing and session targeting (`flatten: true`).
- **`InteractionDriver`**: Synthetic input coordinator handling coordinate-accurate mouse clicks, text typing with Enter submissions, dropdown selections, hover, and scrolling over CDP.

### 4. REPL & Budgeting
- **`REPL Session`**: Persistent in-memory Python execution environment that retains variables, imports, and helper functions across agent turns via AST statement/expression compilation.
- **`Output Budget`**: Hard character/token limit and formatting pipeline with telemetry defanging (sanitizing image beacons and raw active tags).
