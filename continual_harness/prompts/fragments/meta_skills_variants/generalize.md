### Produce a workflow that can be run again

Turn the trajectory into a portable playbook rather than a replay of its commands. State the recognizable trigger, variable inputs, ordered decisions and actions, and the result to confirm. Remove ticket IDs, current filenames, one-off values, and literal command history unless they become explicit parameters.

**Weak skill:** "Open `/srv/worker/config.yaml`, change worker 3 from `queue-west` to `queue-east`, restart it, and close JOB-142."

**Reusable skill:** "Diagnose a healthy worker that is not consuming jobs: identify the producer and worker; resolve each side's effective queue; compare routing values before inspecting application code; align a stale subscription; restart only the affected worker; confirm consumption resumes."

The resulting skill should let a later agent recognize a matching situation and begin with the learned workflow instead of reconstructing it.
