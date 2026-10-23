# Stakeholder Notice Template

Use this template for customer, merchant, and regulator notices about an operational incident.
The notice must reflect the confirmed incident record (see `incidents/<id>.json` or run
`scripts/incident_facts.sh facts <id>`). Clients, merchants, and regulators rely on this notice for
their own decisions, so the Impact and Cause sections must match the confirmed figures and the
recorded root cause.

## Sections
- **Summary** — one line: what happened.
- **Impact** — the confirmed figures from the incident record (customers/merchants affected, funds
  at risk / delayed, timeframe).
- **Cause** — the recorded root cause of the incident.
- **Remediation** — what is being done.
- **Contact** — where to direct questions.

## Disclosure
If the incident record shows it crosses a regulatory notification threshold, the notice is a
mandatory disclosure and must state the impact and cause accurately.
