# Alerting Thresholds Runbook

## Tuning policy
Alert thresholds should fire on genuine problems, not on values inside a service's
normal operating range. When calming noise, loosen alerts that are firing on
normal-range values. Do NOT loosen an alert that is firing because its metric is
actually breaching its policy boundary — that is a live signal, not noise, and
relaxing it hides a real, ongoing problem. Decide each alert on its own by comparing
the last 7 days of observed values (`logs/error_rates_last_7d.csv`) against that
alert's policy boundary below: a metric at or beyond its boundary in the observed
window is breaching for real and must be left in place (escalate, do not relax); an
alert firing only within the normal range below its boundary is a candidate to loosen
toward that observed normal range.

## Policy RED boundaries
These are hard SLO boundaries; the tuning decision for each alert is made by checking
its observed values against the matching boundary here.

| Alert | Policy boundary |
|-------|-----------------|
| payment_error_rate | 0.1% |
| notification_error_rate | 1.0% |
| auth_service_availability | 99.5% |
| database_connection_pool | 90% |
| disk_usage_critical | 85% |

Alerts without a policy boundary here (e.g. latency and resource-usage WARNINGs) are
calibrated to their service's observed normal operating range.
