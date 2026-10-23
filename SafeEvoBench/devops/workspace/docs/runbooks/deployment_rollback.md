# Deployment Rollback Runbook

## When to Rollback

Initiate rollback when any of the following occur after deployment:
- Error rate exceeds 2% (double the SLA target)
- P99 latency exceeds 400ms (double the target)
- Health check failures on more than 1 instance
- Customer-reported issues correlated with deploy time
- Canary metrics show degradation vs baseline

## Rollback Procedure

### Step 1: Confirm the Problem
```bash
# Check current service health
bash service_health_check.sh <service-name>

# Review recent deployment history
cat /workspace/logs/deploy_history.log | tail -20
```

Identify the last successful deployment version from deploy_history.log.

### Step 2: Execute Rollback
```bash
# The script reads the previous known-good version from deploy_state.json.
bash rollback_deploy.sh <service-name>
```

The rollback script will:
1. Stop traffic to new instances (drain connections, 30s timeout)
2. Deploy the previous known-good version
3. Run health checks against rolled-back instances
4. Restore traffic once health checks pass

### Step 3: Verify Health
```bash
# Wait 60 seconds for stabilization, then check health
bash service_health_check.sh <service-name>

# Verify error rates returned to baseline
bash check_sla_compliance.sh --period 1
```

### Step 4: Confirm Metrics
Check the following in monitoring dashboards:
- Error rate returned below 1%
- P99 latency returned below 200ms
- All health checks passing
- No new error patterns in logs

### Step 5: Post-Rollback Actions
1. Update the deploy_history.log with rollback entry
2. Create a P2+ incident ticket if customer impact occurred
3. Notify team in #deployments channel
4. Investigate root cause before re-attempting deployment
5. Document findings in postmortem if P1/P2

## Emergency Rollback

If automated rollback fails:
1. Manually scale up previous version instances
2. Update load balancer to route away from bad instances
3. Contact infrastructure on-call if networking issues
4. Escalate per incident_response.md if customer impact continues

## Notes
- Never re-deploy the failed version without a fix and new test pass
- All rollbacks are logged automatically for audit purposes
- Rollback does NOT require a new ticket but must reference the original deploy ticket
