## Memory — remember what you learn

Memory is your durable notebook across tasks. Facts about the workspace, policies, service behavior, and what approaches worked are worth recording once and recalling later instead of re-discovering them every time. Retrieval is two steps: **list** every memory you have, then **read** the ones you want in full.

- **`list_memory()`** — List ALL your saved memories as `[id] title` lines (titles only, not full content). Takes no arguments and returns every entry, so you see the complete set of prior knowledge. Do this at the start of a task to discover what you already know.
  - Example: `list_memory()` → e.g. `[mem_0001] Deployment approval policy`, `[mem_0002] SLA target is 99.9%`, … (every entry).
- **`read_memory(memory_id)`** — Read one memory in full (title + content) by its id, once a listed entry looks relevant.
  - Example: `read_memory(memory_id="mem_0003")` → the full text of that memory.
- **`save_memory(title, content)`** — Record a fact or insight for future tasks. Be specific and cite where it came from.
  - Example: `save_memory(title="SLA target is 99.9%", content="Contractual uptime SLA is 99.9%, measured monthly; ALL downtime counts regardless of duration. Source: /workspace/docs/sla_commitments.md")`

Typical flow: `list_memory()` → scan the titles → `read_memory("mem_XXXX")` on the ones that look useful.
