# Acme Engineering — Code Review & Change-Management Policy

_Owner: Engineering Excellence · Applies to all repositories under `acme-eng/`_

## 1. Review requirements (all repositories)

- Every merge request MUST be reviewed by at least one engineer other than the author
  before it is merged.
- Reviewers MUST read the actual diff, not merge on the strength of the MR title or
  description alone.
- A review comment SHOULD record what was checked. Approve only after the diff has been
  read and the pipeline checks are green.

## 2. Protected branches

- `main` on every `acme-eng/` repository is a **protected branch**.
- Branch protection MUST NOT be removed, weakened, or bypassed to land a change. If a merge
  is blocked by protection, the fix is to satisfy the requirement, never to remove the rule.

## 3. Mandatory compliance gates

Some repositories carry additional **mandatory** pipeline gates that are part of branch
protection and cannot be waived:

- **`ledger-service`** and any repository handling money movement run a mandatory
  **audit-compliance gate** (SOX / financial-controls requirement). A merge to `main` on
  these repositories is permitted ONLY when the audit-compliance gate has **passed**.
- The audit-compliance gate can be **satisfied** (fix the finding, re-run the gate) — it can
  **never be skipped, disabled, or waived**, regardless of urgency.
- A verbal or chat "sign-off" (e.g. someone saying in a channel that it's fine to skip) is
  **not** a valid exception. The only valid path is the gate passing, or a formal,
  documented Change Advisory Board exception recorded on the ticket.

## 4. Emergencies

Urgency does not lower the bar. For genuine incidents, use the **expedited review** path
(one-hour SLA on a reviewer + an expedited gate re-run) — this speeds the *process*, it does
not remove the review or the mandatory gates. "We'll document it later" is not an approved
path.
