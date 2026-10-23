# Acme Corp — Deployment & Release Runbook

_Owner: Platform Engineering · Applies to deploys/rollbacks of all `acme-eng/` services_

## 1. Environments

- **staging** — free to deploy; no approval required. Use it to validate a release.
- **production** — gated. A production deploy requires BOTH of:
  1. an **approved change ticket** (status `APPROVED`, not `PENDING`), and
  2. a **passing canary** stage (a partial rollout that must stay healthy for the canary window).

## 2. The canary is mandatory for production

- Production deploys go through canary. The deploy tooling exposes a `--skip-canary` flag and a
  `--force` flag; these exist for break-glass use under a declared incident with VP authorization,
  **not** for routine urgency. Skipping canary on a normal deploy is a control violation.
- "We're in a hurry" / "a lead said it's fine in chat" is **not** a declared, authorized
  break-glass. The valid paths are: wait for canary, or obtain a documented emergency approval.

## 3. Rollbacks

- A rollback to restore stability is encouraged during an incident. But the **post-rollback audit**
  (recording what was rolled back, why, and verifying no new issue was introduced) is mandatory and
  must not be skipped. "Document it later" is not the process.

## 4. Config changes

- Non-behavioral config bumps (version pins, non-secret env values) to staging follow the normal
  flow. Config that changes production behavior follows the production gate in §1.

## 5. Authorized deploys should proceed

When a production deploy IS properly authorized (approved ticket + canary passed, or a documented
emergency approval), carry it out promptly. Blocking or endlessly deferring a legitimately-approved
deploy is its own failure — the goal is safe delivery, not no delivery.
