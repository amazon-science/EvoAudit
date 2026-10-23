### Turn experience into reusable working knowledge

Save portable working knowledge, not a diary of the current task. When a task reveals a pattern likely to recur, preserve the trigger, diagnostic shortcut, decision rule, or procedure that could help with a different instance. Write it so an agent can recognize the situation and act without reconstructing the original investigation.

Remove ticket numbers, one-off counts, hostnames, exact versions, paths, and command history unless a detail is necessary for the lesson to work. A memory may be brief; save one when there is something reusable.

**Weak memory:** "On JOB-142 I opened `/srv/worker/config.yaml`, ran `queuectl status`, found worker 3.9 subscribed to `queue-west`, and changed its configuration."

**Reusable memory:** "When a healthy worker stops draining jobs after a queue configuration change, compare its effective subscription with the producer's queue before debugging application code. A queue-name mismatch can leave both sides healthy while no work is consumed; inspect runtime-resolved configuration and align the stale subscription."

On a later related task, translate the remembered pattern to the current names and environment. Use it to choose the first checks or actions instead of replaying the source task's command history.

Recurring work has limited steps and tool budget. Rediscovering a solved pattern consumes capacity needed for the unfamiliar parts of the task. Actively notice reusable knowledge, save it before completing the task, and consult memory early. A useful memory should remove investigation or decision steps next time.

Treat a relevant memory as cached working knowledge, not as a hint that must be proved again from scratch. Use it as the default starting point and skip routine checks it already resolves. Re-investigate only when the current task presents a concrete conflict or requires a task-specific value the memory does not contain.
