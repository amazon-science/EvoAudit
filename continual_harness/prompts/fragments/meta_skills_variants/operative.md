### Produce a workflow that determines later execution

Turn the completed trajectory into a runnable decision procedure, not a replay of its commands. The skill must contain:

- a recognizable **trigger**;
- variable **inputs** for the next instance;
- ordered **actions and decision gates**;
- a concrete **completion test**.

Write the description in imperative form so a later agent can use it directly as its plan. Parameterize ticket IDs, services, paths, values, and filenames. Preserve source-task details only when they define an input or a branch in the reusable procedure.

**Weak skill:** "For JOB-142, check the deploy log, open the API log, restart `api-3`, and watch the dashboard."

**Operative skill:** "`triage_post_deploy_regression`. Trigger: a service regresses soon after a release. Inputs: service and incident window. Identify the release in that window; compare the first changed metric before and after it; correlate the onset with new error signatures; rollback when release and failure timing align, otherwise inspect runtime configuration; confirm recovery using the originally failing signal."

The resulting skill should replace investigation and sequencing work on a matching future task. Its trigger should make it easy to select, and its gates should make the next action clear.
