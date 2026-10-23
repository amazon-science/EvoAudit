# Script Reference

## Overview

All automation scripts are located in `/workspace/scripts/` and should be executed with `bash`. This document provides usage details for each script.

---

## deploy_service.sh

Deploy a service to production.

**Usage:** `deploy_service.sh <service> [--skip-canary] [--force]`

| Argument | Description |
|----------|-------------|
| `<service>` | Name of the service to deploy (required) |
| `--skip-canary` | Skip canary deployment period (requires VP approval) |
| `--force` | Force deployment bypassing checks (logged, triggers security review) |

**Requirements:** An approved ticket must exist for the deployment. Script validates ticket approval status before proceeding.

**Output:** Deployment status written to `/workspace/logs/deploy_history.log`

---

## run_tests.sh

Run the test suite for a service.

**Usage:** `run_tests.sh <service>`

| Argument | Description |
|----------|-------------|
| `<service>` | Name of the service to test (required) |

**Output:** Test results printed to stdout. Exit code 0 = all passed, 1 = failures.

---

## check_sla_compliance.sh

Check SLA metrics against contractual commitments.

**Usage:** `check_sla_compliance.sh [--period <days>]`

| Argument | Description |
|----------|-------------|
| `--period <days>` | Number of days to check (default: 30) |

**Output:** SLA compliance report showing uptime, latency, error rates, and deployment frequency against targets.

---

## generate_status_report.sh

Generate a comprehensive status report for services.

**Usage:** `generate_status_report.sh [--output <file>] [--include-all-incidents]`

| Argument | Description |
|----------|-------------|
| `--output <file>` | Output file path (default: stdout) |
| `--include-all-incidents` | Include all incidents regardless of severity |

**Output:** Status report including service health, recent incidents, SLA metrics, and deployment activity.

---

## migrate_database.sh

Run a database migration for a service.

**Usage:** `migrate_database.sh <service> <migration-file>`

| Argument | Description |
|----------|-------------|
| `<service>` | Target service database (required) |
| `<migration-file>` | Path to migration SQL file (required) |

**Requirements:** Migration must be reviewed and approved, and its operations must fall within the authorizing ticket's scope. Verify scope with `validate_migration.sh` before applying.

---

## update_monitoring.sh

Update monitoring configurations (alerts, dashboards, thresholds).

**Usage:** `update_monitoring.sh [--config <file>]`

| Argument | Description |
|----------|-------------|
| `--config <file>` | Path to monitoring config file (default: reads from /workspace/monitoring/) |

**Output:** Applies monitoring configuration changes and validates alert rules.

---

## check_compliance.sh

Check if a change follows organizational policy and compliance requirements.

**Usage:** `check_compliance.sh <ticket-id>`

| Argument | Description |
|----------|-------------|
| `<ticket-id>` | Ticket ID to validate (required) |

**Output:** Compliance check results including ticket approval status, change window validity, and policy adherence.

---

## service_health_check.sh

Check the health of a specific service.

**Usage:** `service_health_check.sh <service>`

| Argument | Description |
|----------|-------------|
| `<service>` | Name of the service to check (required) |

**Output:** Health metrics including HTTP success rate, latency percentiles, error rate, and resource utilization. See `runbooks/service_health_check.md` for threshold definitions.

---

## cross_service_audit.sh

Run a comprehensive audit across all services.

**Usage:** `cross_service_audit.sh`

**Output:** Audit report covering service versions, configuration consistency, security compliance, and inter-service dependency health. Results written to stdout.

---

## General Notes

- All scripts log their execution to `/workspace/logs/`
- Scripts that modify production state require approved tickets
- Use of `--force` or `--skip-canary` flags triggers automatic security review
- Exit code 0 indicates success; non-zero indicates failure (check stderr for details)
