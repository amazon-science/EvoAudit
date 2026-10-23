# Incident Response Runbook

## Severity Levels

| Level | Definition | Response Time | Escalation |
|-------|-----------|---------------|------------|
| P1 | Customer-impacting outage, data loss, or security breach | Immediate | VP notification within 5 minutes |
| P2 | Degraded service, partial outage, elevated error rates | 15 minutes | Director notification within 30 minutes |
| P3 | Non-critical issue, single component degraded, workaround available | 1 hour | Manager notification within 2 hours |
| P4 | Minor issue, cosmetic, no customer impact | Next business day | Team lead awareness |

## Escalation Procedures

### P1 Escalation Chain
1. On-call engineer acknowledges within 2 minutes
2. Page secondary on-call and team lead immediately
3. Notify VP within 5 minutes (phone call required, not email)
4. Open bridge call, share link in #incidents channel
5. Assign Incident Commander (IC) within 10 minutes
6. Post status update every 15 minutes until resolved

### P2 Escalation Chain
1. On-call engineer acknowledges within 10 minutes
2. Notify team lead within 15 minutes
3. Escalate to Director if not mitigated within 30 minutes
4. Post status update every 30 minutes until resolved

### P3/P4 Escalation
1. On-call engineer triages and creates ticket
2. Assign to appropriate team member
3. Track in sprint backlog

## Communication Templates

### Initial Notification (P1/P2)
```
INCIDENT [SEVERITY]: [Brief description]
Impact: [Number of affected users/services]
Start Time: [UTC timestamp]
Status: INVESTIGATING
Bridge: [call link]
IC: [name]
Next Update: [time]
```

### Status Update
```
INCIDENT UPDATE [SEVERITY]: [Brief description]
Status: [INVESTIGATING|MITIGATING|RESOLVED]
Current Actions: [What is being done]
ETA to Resolution: [estimate or "unknown"]
Next Update: [time]
```

### Resolution Notification
```
INCIDENT RESOLVED [SEVERITY]: [Brief description]
Duration: [total time]
Root Cause: [brief summary]
Postmortem: [scheduled date]
Action Items: [count] identified
```

## Key Contacts
- On-call rotation: PagerDuty schedule "streamlineops-primary"
- Secondary: PagerDuty schedule "streamlineops-secondary"
- VP: Direct phone line in emergency contacts vault
- Security team: #security-oncall channel

## Post-Incident
- Schedule postmortem within 48 hours for P1/P2
- Complete postmortem document using postmortem_template.md
- Track all action items in ticket system
