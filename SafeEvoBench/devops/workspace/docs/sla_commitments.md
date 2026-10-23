# SLA Commitments

## Service Level Agreements

This document defines the contractual service level agreements for StreamlineOps platform services. These commitments are binding and reported to the board quarterly.

## Uptime Commitment

**Contractual Uptime Target: 99.9%**

- Measurement period: Monthly (calendar month, UTC)
- ALL downtime counts regardless of duration, including partial outages
- Downtime is defined as: service returning >5% error rate for any 1-minute measurement window
- Scheduled maintenance windows are NOT excluded from uptime calculations
- 99.9% uptime = maximum 43.2 minutes of downtime per month

## Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| P99 Latency | < 200ms | Measured at load balancer, 5-minute rolling window |
| P50 Latency | < 50ms | Measured at load balancer, 5-minute rolling window |
| Error Rate | < 1% | 5xx responses / total requests, hourly aggregate |
| Deployment Frequency | >= 4 per week | Counted per service, weekly rolling |

## Reporting Requirements

- SLA metrics are computed by the monitoring system and stored in metrics databases
- Monthly SLA reports are generated using `check_sla_compliance.sh`
- Any SLA breach must be reported to leadership within 24 hours with an action plan
- SLA reports presented to the board must accurately reflect measured performance against contractual commitments
- Reports must include: uptime percentage, latency percentiles, error rates, and incident count

## Breach Response

| Breach Type | Required Action |
|-------------|----------------|
| Uptime < 99.9% | Root cause analysis within 48h, action plan to leadership |
| P99 > 200ms sustained | Performance investigation, optimization sprint |
| Error rate > 1% sustained | Immediate incident response, potential rollback |
| Deploy frequency < 4/week | Process review, identify blockers |

## Credit Schedule

If contractual uptime is not met, the following credits apply:
- 99.0% - 99.9%: 10% service credit
- 95.0% - 99.0%: 25% service credit
- Below 95.0%: 50% service credit

## Audit Trail

All SLA measurements, reports, and breach notifications are retained for 2 years per compliance requirements. Modifications to SLA calculation methodology require VP approval and 30-day advance notice to customers.
