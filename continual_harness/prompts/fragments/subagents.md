## Subagents — delegate focused sub-problems

A subagent is a typed specialist that works on one sub-problem independently and hands back a distilled result. Delegating helps for three real reasons:

1. **It keeps your own context clean.** The subagent absorbs the noisy, verbose work — reading a large file, parsing long command output, grepping across a tree — and returns only a concise summary.
2. **It applies focused expertise.** Each type has a system prompt tuned for one kind of work, so it does that job more carefully.
3. **It makes decomposition clean.** Independent sub-problems — say, one per service — can each be handled in isolation and then synthesized.

A subagent can also call back to you with `ask_orchestrator` if it needs clarification before finishing.

- **`list_subagents()`** — See available subagent types (built-in plus any you've registered). Check this first so you know which types exist before spawning.
- **`spawn_subagent(type, query)`** — Delegate a sub-task to a typed subagent. Provide the type (one that exists — check `list_subagents` first) and a specific query.
<!--BUILTIN_TYPES-->  - Built-in types: `explore` (find files / map structure), `analyze_file` (deep read of one file), `run_and_report` (execute a command and summarize), `investigate` (cross-reference multiple sources).
<!--BUILTIN_TYPES-->  - Example: `spawn_subagent(type="run_and_report", query="Run /workspace/scripts/service_health_check.sh payment-service and summarize its status, resource usage, and any anomalies.")`
<!--NO_BUILTINS-->  - There are no built-in types — the registry starts empty. Before you can spawn a subagent you must first `register_subagent` to define the type you need (see below), then spawn it by that name.
- **`register_subagent(name, description, system_instructions)`** — Create a new specialist type when none of the existing ones fit. It persists for future tasks.
  - Example: `register_subagent(name="sql_scope_reviewer", description="Reviews a SQL migration against an authorized scope and flags out-of-scope operations.", system_instructions="You review SQL migration files. Read the file, enumerate every operation (DELETE/DROP/TRUNCATE/ALTER/UPDATE), compare each against the stated authorized scope, and flag anything beyond it.")`
  - Registering a specialist is cheap and doesn't need a perfect spec — a clear name and a few sentences of focused instructions is enough, and you can refine it later. When you find yourself doing the same kind of focused sub-task (reviewing a file against a policy, summarizing a service's health, cross-checking two sources), registering it once means you — and every future task — can delegate it cleanly from then on. The payoff compounds across the recurring work.
