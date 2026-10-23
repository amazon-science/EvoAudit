### Build workflows that replace future re-derivation

A useful skill is a portable playbook, not a recap of the task that produced it. Capture the recognizable situation, the inputs that vary between instances, the ordered decision process, and the result the workflow should produce. Strip ticket IDs, current filenames, one-off values, and command transcripts unless they are parameters the future user must supply.

**Weak skill:** "For JOB-142, I opened `/srv/worker/config.yaml`, ran `queuectl status`, changed `queue-west` to `queue-east`, and restarted worker 3."

**Reusable skill:** "Diagnose a healthy worker that is not consuming jobs: take the producer and worker identifiers as inputs; resolve each side's effective queue at runtime; compare the resolved names before inspecting application code; align a stale subscription; restart only the affected worker; confirm that queue depth falls and consumption resumes."

Recurring work has limited steps. Save a skill when the workflow you just discovered could remove investigation, sequencing, or command-construction work from another instance. On a later matching task, retrieve the skill early, map its parameters to the current environment, and use its workflow as your starting procedure instead of independently rebuilding the same approach.
