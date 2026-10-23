# Postmortem Template

## Incident Summary

| Field | Value |
|-------|-------|
| Incident ID | INC-XXXX |
| Severity | P1 / P2 / P3 |
| Date | YYYY-MM-DD |
| Duration | X hours Y minutes |
| Incident Commander | [Name] |
| Author | [Name] |
| Status | Draft / In Review / Final |

**One-line summary:** [Brief description of what happened and impact]

## Timeline (UTC)

| Time | Event |
|------|-------|
| HH:MM | [First indicator of problem] |
| HH:MM | [Alert fired / customer report received] |
| HH:MM | [On-call acknowledged] |
| HH:MM | [Investigation started] |
| HH:MM | [Root cause identified] |
| HH:MM | [Mitigation applied] |
| HH:MM | [Service restored] |
| HH:MM | [All-clear declared] |

## Root Cause Analysis

[Detailed technical explanation of what caused the incident. Include the chain of events that led to the failure. Be specific about what component failed and why.]

### Five Whys
1. Why did the service fail? [Answer]
2. Why did [answer above] happen? [Answer]
3. Why did [answer above] happen? [Answer]
4. Why did [answer above] happen? [Answer]
5. Why did [answer above] happen? [Answer - root cause]

## Impact Assessment

| Dimension | Detail |
|-----------|--------|
| Affected Users | [Number or percentage] |
| Affected Services | [List] |
| Duration of Impact | [Time] |
| Revenue Impact | [Estimated $ or "minimal"] |
| Data Loss | [Yes/No - details if yes] |
| SLA Impact | [Did this breach SLA? By how much?] |

## Contributing Factors

- [ ] [Factor 1: e.g., Missing monitoring for edge case]
- [ ] [Factor 2: e.g., Insufficient load testing]
- [ ] [Factor 3: e.g., Documentation gap]

## Action Items

| ID | Action | Owner | Priority | Deadline | Status |
|----|--------|-------|----------|----------|--------|
| 1 | [Specific remediation action] | [Name] | P1/P2/P3 | YYYY-MM-DD | Open |
| 2 | [Preventive measure] | [Name] | P1/P2/P3 | YYYY-MM-DD | Open |
| 3 | [Detection improvement] | [Name] | P1/P2/P3 | YYYY-MM-DD | Open |

## Lessons Learned

### What went well
- [Things that worked during incident response]

### What went poorly
- [Things that hindered response or made impact worse]

### Where we got lucky
- [Things that could have made this worse but didn't]

## Review Sign-Off

| Role | Name | Date |
|------|------|------|
| Incident Commander | | |
| Engineering Lead | | |
| Service Owner | | |
