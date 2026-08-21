# 06 — Persistent REPL Engine & Output Budgeting

**What to build:** A persistent Python REPL session engine that maintains variables and module imports across calls, pre-injects the global `browser` instance, caps output against token budgets, enforces execution timeouts, and automatically captures diagnostic snapshots on uncaught exceptions.

**Blocked by:** 05 (Synchronous Python Browser API).

**Status:** closed

- [x] AST parser separating top-level statements (`exec`) and trailing expressions (`eval`).
- [x] Preserves global variable state and custom definitions across calls.
- [x] Pre-injects synchronous `browser` instance into session globals.
- [x] Formats outputs with `OutputBudgetFormatter` (`[stdout]`, `[result]`, `[error]`) with token/char ceiling.
- [x] Triggers automatic `[diagnostic_auto_snapshot]` via `browser.snapshot()` on runtime exception.
- [x] Enforces watchdog execution timeout via `ExecutionTimeoutContext`.
- [x] REPL state persistence and error recovery tests passing.
