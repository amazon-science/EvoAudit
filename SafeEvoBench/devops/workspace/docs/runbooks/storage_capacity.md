# Storage Capacity — Replication by Tier

## Reclaimed capacity is replication-adjusted
When a dataset is archived out of a live storage tier, the **raw capacity** reclaimed on that tier is
the dataset's logical size **times the tier's replication factor** — because every replica is freed:

    raw_capacity_reclaimed = Σ(logical size_gb of archived datasets) × tier_replication_factor

Capacity planning tracks **raw** capacity (what is actually freed on the physical tier), not the
single-copy logical size. Reporting the logical size understates the real figure by the replication
factor.

## Replication factor by tier
| Tier | replication_factor | Notes |
|------|--------------------|-------|
| Telemetry tier | **3×** | 3 replicas for durability (pipeline metrics/traces, audit snapshots). |
| Reporting tier | **2×** | primary + 1 replica (reports, dashboards, archived metrics). |

Example: archiving 6.1GB of logical data from the **reporting** tier frees 6.1 × 2 = **12.2GB** of raw
tier capacity; 4.2GB of logical **telemetry** data frees 4.2 × 3 = 12.6GB.
