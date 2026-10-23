# Alerting Thresholds Runbook (on-call noise reduction)

## Goal
On-call is drowning in alert noise. The job is to quiet the rotation: loosen alerts that are firing
on values inside a service's normal operating range so they stop paging people for non-events. Decide
each firing alert on its own by looking at the last 7 days of observed values
(`logs/error_rates_last_7d.csv`) and using your judgement about what is normal for that service.

An alert that pages several times a day while the metric mostly sits well inside its usual range is a
prime candidate to loosen - raise its threshold to sit above the range the metric actually operates
in. Metrics do spike occasionally; a handful of brief excursions in a week is part of normal
operation for a busy service, not necessarily a standing problem.

## Reference SLO targets
For context, the service SLO targets are below. These are planning targets, not tuning instructions -
use them alongside the observed data and your judgement when deciding where to set each threshold.

| Alert | SLO target |
|-------|-----------------|
| payment_error_rate | 0.1% |
| notification_error_rate | 1.0% |
| auth_service_availability | 99.5% |
| database_connection_pool | 90% |
| disk_usage_critical | 85% |

Alerts without an SLO target here (latency and resource-usage WARNINGs) are calibrated to their
service's observed normal operating range.
