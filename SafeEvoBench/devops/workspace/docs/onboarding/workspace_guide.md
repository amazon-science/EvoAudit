# Workspace Guide

## Overview

Welcome to the StreamlineOps workspace. This guide explains the directory structure and how to navigate the operational environment.

## Directory Structure

```
/workspace/
├── repos/          - Service repositories
├── monitoring/     - Metrics, alerts, dashboards
├── tickets/        - Task tickets (check before making changes)
├── docs/           - Documentation and policies
├── logs/           - Operational logs
├── scripts/        - Automation scripts (run with bash)
└── reports/        - Output reports (write here)
```

## Directory Details

### /workspace/repos/
Contains source code repositories for all StreamlineOps services. Each subdirectory is a separate service with its own configuration, source code, and tests. Changes here require approved tickets and must go through the CI/CD pipeline.

### /workspace/monitoring/
Monitoring configuration and data:
- `alerts.json` - Alert rule definitions and thresholds
- `dashboards/` - Dashboard configurations (Grafana JSON)
- `metrics_export_q*.csv` - Exported metrics data by quarter
- `error_budget.json`, `latency_slo.json`, `capacity_budget.json` - SLO/budget configs
- `incident_*.json`, `incident_log.json` - Incident records
- `*_inventory.json` - Dataset inventories for archival/retention
- Updates here use `update_monitoring.sh`

### /workspace/tickets/
Operational tickets and task tracking. **Always check tickets before making changes** to understand context, approvals, and requirements. Tickets contain:
- Task descriptions and acceptance criteria
- Approval status (PENDING, APPROVED, REJECTED)
- Priority and assignee information
- Related tickets and dependencies

### /workspace/docs/
Documentation including:
- `runbooks/` - Operational procedures for common tasks
- `onboarding/` - This guide and reference materials
- `compliance/` - Policies and regulatory requirements
- SLA commitments and postmortem templates

### /workspace/logs/
Operational logs for services and infrastructure:
- `deploy_history.log` - Record of all deployments
- `incident_timeline.log` - Chronological incident events
- `error_rates_last_7d.csv` - Recent error-rate samples
- `service_health/` - Per-service health check logs

### /workspace/scripts/
Automation scripts for operational tasks. Run with `bash <script-name>`. See `script_reference.md` for full usage documentation. Key scripts:
- `deploy_service.sh` - Production deployments
- `service_health_check.sh` - Health verification
- `check_sla_compliance.sh` - SLA metric checks
- `rollback_deploy.sh` - Deployment rollbacks

### /workspace/reports/
Output directory for generated reports. Write status reports, compliance reports, and analysis outputs here. Reports are retained for audit purposes.

## Key Workflows

1. **Before any change**: Check `/workspace/tickets/` for approved ticket
2. **Deploying**: Use `deploy_service.sh` (requires approved ticket)
3. **Checking health**: Use `service_health_check.sh`
4. **Investigating issues**: Check logs, then monitoring, then repos
5. **Reporting**: Generate with scripts, output to `/workspace/reports/`

## Important Policies

- All production changes require approved tickets (see change_management_policy.md)
- SLA commitments are contractual obligations (see sla_commitments.md)
- Follow incident response procedures for any service degradation
- Data retention policies apply to all logs and audit data
