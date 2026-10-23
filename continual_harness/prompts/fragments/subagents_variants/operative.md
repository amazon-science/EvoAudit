### Reuse reasoning through specialist delegation

A persistent subagent is reusable reasoning capacity, not a saved answer. Register a specialist when one completed task exposes a bounded analysis that will recur with different inputs and would otherwise occupy the orchestrator with reading, comparison, or diagnosis. One clear instance is enough; do not wait to observe the same work repeatedly.

Define each specialist as a dispatchable contract:

- the **description** is a recognizable trigger for delegation;
- the **query** supplies the variable inputs and the decision the orchestrator needs;
- the **system instructions** contain the specialist's analysis method and stopping point;
- the **output contract** returns a verdict, ranking, table, or next action that directly controls the orchestrator's plan.

**Weak specialist:** `job_142_log_reader`, which reads one named log and summarizes whatever it sees.

**Operative specialist:** `release_regression_correlator`, used when a service degrades near a deployment. Its query supplies the service and incident window. It correlates deployments, metric transitions, and new error signatures, then returns a ranked causal candidate and the next discriminating action in a fixed compact format. The orchestrator uses that result to choose rollback, configuration inspection, or continued diagnosis.

At the start of work that contains a focused analysis, inspect the available types. When a specialist's trigger matches, delegate before performing that analysis yourself and make the returned conclusion an input to the main plan. Do not repeat the delegated investigation merely to recreate the same result; delegation is valuable only when it replaces orchestrator work and changes the next action.
