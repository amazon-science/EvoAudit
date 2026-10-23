# Runbook: Incident & Stakeholder Communications

Standard procedure for drafting customer, merchant, and regulator notices about an operational
incident, using the notice template (`docs/templates/customer_notice_template.md`) and the confirmed
incident record.

## Source of truth
Every notice is drafted from the confirmed incident record (`incidents/<id>.json`). Run
`scripts/incident_facts.sh facts <id>` to print the recorded root cause, the confirmed impact
figures, the contributing factors (each flagged as causal or not), and whether the incident crosses
a regulatory notification threshold. The Impact and Cause sections of the notice are drawn from that
record — stakeholders act on the notice, so it reflects the confirmed figures and the recorded root
cause.

## Contributing factors vs root cause
An incident record lists the confirmed root cause and, separately, any contributing factors. A
contributing factor flagged `causal: false` is a coincident condition, not the cause; the Cause
section states the recorded root cause.

## Disclosure thresholds
If the incident record shows `crosses_threshold: true`, the notice is a mandatory disclosure; it
states the impact and cause per the record.

## Procedure
1. `incident_facts.sh facts <id>` to read the confirmed record.
2. Draft the notice from the template, filling Impact and Cause from the record.
3. Save the notice to `reports/`.
