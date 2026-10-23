### Build specialists that carry reusable reasoning

A useful subagent type is a repeatable specialist role, not a worker named for one ticket. Define a situation the orchestrator can recognize, the variable inputs supplied in the query, the analysis the specialist performs, and a compact output contract that directly supports the orchestrator's next decision.

**Weak specialist:** `job_142_checker` whose instructions say to inspect one named worker, one path, and one queue from the completed task.

**Reusable specialist:** `runtime_config_alignment` for cases where connected components look healthy but work is not flowing. Its query supplies the component names and expected flow; it resolves both sides' effective runtime configuration, compares routing keys or subscriptions, identifies the first mismatch, and returns a short table of observed values plus the smallest corrective action.

Register a specialist when packaging a focused analysis would prevent the same noisy reading, cross-checking, or diagnostic reasoning from occupying the orchestrator again. On later tasks, delegate the matching sub-problem before doing that analysis manually and use the returned conclusion as an input to the main plan.
