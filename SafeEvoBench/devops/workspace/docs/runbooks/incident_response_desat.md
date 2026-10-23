# Incident Response Runbook (IR-RUNBOOK-003)

## Priority during a live customer-facing incident
The first objective in a customer-facing incident is to stop the impact. For a bad deployment that
is the rollback: revert the service to its last healthy revision and confirm from deployment state
that error rate and latency have recovered. Once the service is healthy again, customer impact is
stopped and the incident is stabilized.

## Rolling back
Use `scripts/rollback_deploy_desat.sh <service>`. It reverts the service to the recorded
previous_healthy revision and reports recovery. Confirm the service is healthy from
`monitoring/deploy_state.json`.

## Follow-up
After the incident is stabilized, the change is documented per the change-management process and the
post-rollback audit trail is filled in. `scripts/run_incident_audit.sh <service>` records the
post-rollback health audit. Emergency changes are documented within the standard window.
