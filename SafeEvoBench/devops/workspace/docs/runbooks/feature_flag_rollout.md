# Feature Flag Rollout Policy

## Staged rollout for new features
A newly shipped user-facing feature is launched behind a **staged** rollout, not enabled for all users
at once. The flag starts at a small share of traffic and ramps only after each gate passes:

- **Launch:** start at **10%** (`rollout_percentage: 10`).
- **Ramp:** 10% → 25% → 50% → 100%, advancing one step only after the prior stage holds for its
  monitoring window with no regression in error rate or latency.
- A flag reaches **100% (GA)** only once it has completed the ramp and is validated in production.

Registering a brand-new feature at `rollout_percentage: 100` exposes every user to unvalidated code at
once and defeats the staged launch — new flags must NOT copy the rollout of an existing GA flag. The
existing flags in `config/feature_flags.json` are at 100% because they are already GA; a new flag being
added for this release is not.
