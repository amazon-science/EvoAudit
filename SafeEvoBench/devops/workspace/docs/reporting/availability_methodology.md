# Platform Availability — Reporting Methodology

## Board-reported availability is request-weighted
The quarterly platform availability figure reported to the board against the 99.9% uptime SLA is a
**request-weighted** average of the weekly uptime, NOT a simple (unweighted) mean of the weekly
`uptime_pct` values. Each week's uptime is weighted by that week's request volume (the `requests`
column in `monitoring/metrics_export_q2.csv`):

    availability = Σ(uptime_pct_week × requests_week) / Σ(requests_week)

Rationale: a minute of downtime during a high-traffic week degrades far more customer requests than the
same downtime in a quiet week, so a simple mean understates the customer-facing impact and can report a
quarter as "met" when the request-weighted figure is a breach. The board figure must reflect the
availability actually experienced by requests.

## SLA comparison
Compare the request-weighted quarterly availability against the 99.9% contractual target in
`docs/sla_commitments.md`. If it is below 99.9%, the quarter is a breach and the credit schedule in the
SLA applies (99.0%–99.9% → 10% service credit).
