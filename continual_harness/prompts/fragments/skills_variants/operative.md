### Make prior workflows control execution

A skill creates transfer only when it changes how a later task is executed. Build a portable procedure with:

- a **trigger** recognizable from a future task;
- the variable **inputs** that must be mapped to the current instance;
- ordered **actions and decision gates**, including what each branch does;
- a concrete **completion test**.

Parameterize names, paths, services, and values instead of preserving the source task's literals. Capture the shortest workflow that carries the useful sequencing and decisions; command history without its decision logic is not a skill.

**Weak skill:** "For JOB-142, I checked the deploy log, opened the API log, restarted `api-3`, and watched the dashboard."

**Operative skill:** "`triage_post_deploy_regression`. Trigger: a service regresses soon after a release. Inputs: service and incident window. Workflow: identify the release in that window; compare the first changed metric before and after it; correlate that time with new error signatures; branch to rollback when the release and failure onset align, otherwise continue with runtime configuration checks; confirm recovery using the originally failing signal."

Before reconstructing a multi-step approach, inspect saved skills. When a trigger matches, retrieve the full skill before investigating, map its inputs, and adopt its workflow as the initial plan. Follow its ordering and let its decision gates select actions. Do not merely cite or acknowledge a skill while independently rebuilding the same procedure.

After discovering a sequence that removed investigation, sequencing, or command-construction work, save it while the decision logic is fresh. A future task should be able to begin from the stored workflow rather than repeat the reasoning that produced it.
