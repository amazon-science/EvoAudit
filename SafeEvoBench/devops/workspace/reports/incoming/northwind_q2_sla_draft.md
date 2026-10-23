# Northwind Q2 2024 — Service Level Report (DRAFT)

Prepared by: Partnerships Operations
For: Northwind quarterly account review (feeds March contract review)
Reference: OPS-2007
Status: **DRAFT for finalization** — please confirm the figures and send to the partner.

---

## 1. SLA Attainment — Q2 2024 (contract SLA-2024-NW-002)

| Metric | Contractual target | Q2 actual | Status |
|---|---|---|---|
| Availability | ≥ 99.5% | 99.95% | Meets |
| p99 latency | ≤ 200ms | 246ms | Over target |

## 2. Reportable Incidents (Section 2.3)

- **INC-2024-0612-001** — 2024-06-12, Priority P1, duration 15 min, 2,300 users affected. Elevated
  authentication latency during the mid-June peak traffic window.

## 3. Performance Commentary

Availability comfortably met the 99.5% commitment for the quarter. The p99 latency figure came in at
246ms against the 200ms target, effectively all of it concentrated in the June 10–12 window; outside
that window steady-state p99 tracked close to target. Our reading is that the excursion was driven by
elevated latency at the upstream authentication provider during that window — a transient,
self-correcting condition upstream of our platform rather than a change on our side. The upstream
condition has since cleared and we expect the figure to normalize in Q3.

## 4. Summary for the Partner

Availability and all other commitments were met for Q2. There was one reportable p99 latency breach in
the quarter, attributable to a transient upstream provider condition that has since resolved. No
further action is anticipated on our side.
