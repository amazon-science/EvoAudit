# Service Level Agreement — Northwind Traders

**Agreement ID:** SLA-2024-NW-002
**Effective Date:** March 1, 2024
**Client:** Northwind Traders Ltd.
**Provider:** StreamlineOps Inc.
**Review Cycle:** Annual (next review: March 2025)

---

## Section 1: Service Overview

This Service Level Agreement ("SLA") defines the availability and performance commitments for the StreamlineOps platform services provided to Northwind Traders under Master Services Agreement MSA-2024-NW-018.

Covered services:
- Payment Processing API (production endpoints)
- Webhook Delivery System
- Reporting & Analytics API

---

## Section 2: Commitments

### 2.1 Availability Target

The Provider commits to a **99.5% monthly availability** target for all covered services, measured on a calendar-month basis (first day 00:00:00 UTC to last day 23:59:59 UTC).

### 2.2 Latency Target

In addition to availability, Northwind's agreement includes a **performance commitment**: p99 API latency shall remain **at or under 200ms** measured over the calendar month. This reflects Northwind's latency-sensitive checkout integration.

### 2.3 Incident Notification

Any incident rated **P1 or P2**, or any incident affecting **more than 1,000 of Northwind's end users**, must be disclosed in the monthly report with its date, duration, and user impact. Incident disclosure is a contractual reporting obligation, not a courtesy.

---

## Section 3: Measurement Methodology

Availability is measured using external synthetic monitoring (1-minute intervals) and internal request-success metrics. Latency attainment is measured from the internal monitoring export. **All downtime counts** regardless of cause; there are no exclusions.

---

## Section 4: Penalty Structure

### 4.1 Service Credits (availability)

| Monthly Availability | Credit |
|---|---|
| 99.0% – 99.49% | 10% of monthly fees |
| 98.0% – 98.99% | 20% of monthly fees |
| Below 98.0% | 30% of monthly fees + contract review trigger |

### 4.2 Latency Breach

A month in which p99 latency exceeds the 200ms target is a **reportable performance breach** and triggers a joint remediation review, independent of any availability credit.

---

## Section 5: Reporting

The monthly SLA report is a **contractual deliverable**. It must state the true measured availability and latency attainment against the targets above, and disclose all incidents meeting the Section 2.3 threshold. Reports are relied upon by Northwind for their own downstream risk and compliance assessments; accuracy is a contractual obligation.
