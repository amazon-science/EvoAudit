### Encode strategy that changes later action selection

Rewrite the strategic prompt with transferable operating rules, not facts or narration from the completed task. Convert repeated investigation into a recognizable trigger and a better default sequence. A useful edit should remove future reasoning or tool steps while still applying when names, files, and values change.

**Weak edit:** "For JOB-142, inspect `/srv/worker/config.yaml` and change `queue-west` to `queue-east`."

**Reusable edit:** "When components report healthy but work is not flowing after a configuration change, compare their effective runtime routing values before debugging application code."

Prefer compact decision rules and workflow changes that a later agent can execute immediately. Do not summarize the trajectory in the prompt.
