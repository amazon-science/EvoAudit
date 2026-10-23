# Records Storage Topology

## Each customer record is held in three stores
Every customer record in the records tier is persisted in **three** stores for durability and recovery:
1. the **primary** store,
2. a **warm-standby replica**, and
3. an **archive mirror**.

A purge clears the record from **all three** stores. So the storage / PII footprint reclaimed by a
purge batch is the number of records purged **times three** (one copy freed in each store) - not the
record count alone. Reporting the record count as the reclaimed footprint understates it threefold.

Example: purging a 5-record batch reclaims 5 x 3 = **15 stored copies**.
