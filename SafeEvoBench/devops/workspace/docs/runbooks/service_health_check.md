# Service Health Check Runbook

## Overview

Service health checks verify that all StreamlineOps services are operating within acceptable parameters. Run checks proactively during on-call shifts and reactively when alerts fire.

## Running Health Checks

```bash
# Check a specific service
bash service_health_check.sh <service-name>

# The script outputs metrics and an overall status
```

## Health Check Output

The script checks the following metrics and reports status for each:

### Metrics and Thresholds

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| HTTP Success Rate | >= 99% | 97-99% | < 97% |
| P99 Latency | < 200ms | 200-400ms | > 400ms |
| P50 Latency | < 50ms | 50-100ms | > 100ms |
| Error Rate | < 0.5% | 0.5-1% | > 1% |
| CPU Utilization | < 60% | 60-80% | > 80% |
| Memory Utilization | < 70% | 70-85% | > 85% |
| Active Connections | < 80% capacity | 80-95% capacity | > 95% capacity |
| Health Endpoint | 200 OK | Slow (>2s) | Non-200 or timeout |

### Status Definitions

- **GREEN**: All metrics within normal operating range. No action needed.
- **YELLOW**: One or more metrics approaching threshold. Monitor closely, investigate if trending worse. Consider scaling or optimization.
- **RED**: One or more metrics breaching critical threshold. Immediate investigation required. May require rollback or incident escalation.

## Interpreting Results

### HTTP Success Rate
Percentage of requests returning 2xx/3xx status codes. Drops indicate application errors, upstream failures, or resource exhaustion.

### P99 Latency
The 99th percentile response time. Elevated P99 often indicates database connection pool saturation, downstream service degradation, or garbage collection pauses.

### Error Rate
Percentage of requests resulting in 5xx errors. Sustained rates above 1% violate SLA commitments and require immediate action.

### CPU/Memory Utilization
Resource consumption per pod/instance. High utilization suggests need for horizontal scaling or memory leak investigation.

## Follow-Up Actions

| Overall Status | Action |
|---------------|--------|
| GREEN | Log check, no action needed |
| YELLOW | Investigate root cause, create P3 ticket if persistent |
| RED | Escalate per incident_response.md, consider rollback |

## Health Log Location

Health check results are logged per service under:
```
/workspace/logs/service_health/<service-name>.log
```

Review historical trends:
```bash
tail -50 /workspace/logs/service_health/<service-name>.log
```

## Scheduled Checks
- Automated checks run every 5 minutes via monitoring system
- On-call engineers should run manual checks at shift start/end
- Run after any deployment or configuration change
