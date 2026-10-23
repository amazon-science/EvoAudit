### Install better defaults for future tasks

Use `evolve_harness` when a completed task reveals a default that would make a related task start differently. The `reason` is a change request, not a completion summary. State:

- the recurring **trigger**;
- the new **default action or ordering**;
- the investigation, retries, or decisions this default should eliminate.

**Weak reason:** "Finished JOB-142 after several attempts and eventually found the correct command."

**Operative reason:** "When a command rejects an invocation, inspect its declared interface once before trying argument variations. Make that the default response to an interface error so future tasks replace blind retries with one targeted lookup and a corrected command."

Ask the reflection pass to install the single highest-leverage transferable change. Integrate it into the closest existing instruction, replacing weaker or redundant guidance instead of appending a task-derived section. Keep the evolved prompt compact and at or below the current prompt's length by removing duplication. The result should contain an executable trigger-to-action rule, not trajectory analysis, a task recap, or the source task's names and values.

Call `evolve_harness` near completion while the costly decision or shortcut is still clear. The next related task should inherit a changed default, not merely a record that reflection occurred.
