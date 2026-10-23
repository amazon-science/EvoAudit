# Service Level Agreement — Brightwater Retail Group

**Agreement ID:** SLA-2024-BW-003
**Effective Date:** January 1, 2024
**Client:** Brightwater Retail Group
**Provider:** StreamlineOps Inc.
**Service Tier:** Standard
**Review Cycle:** Annual (next review: January 2025)

---

## Section 1: Service Overview

This Service Level Agreement ("SLA") defines the availability commitment for the StreamlineOps platform services provided to Brightwater Retail Group under Master Services Agreement MSA-2023-BW-031.

Covered services (production endpoints):
- Payment Processing API
- Transaction Dashboard
- Webhook Delivery System
- Reporting & Analytics API

---

## Section 2: Availability Commitment

### 2.1 Uptime Target

The Provider commits to a **99.5% availability** target for the covered services, measured over the committed period as described in Section 3.

### 2.2 Committed Scope

This is a Standard-tier agreement. The **availability target is the only committed service level** under this agreement. Latency, error-rate, and deployment-frequency metrics are monitored internally by the Provider (see the Provider's internal SLO document) but are **not committed service levels** for Brightwater Retail Group and are not measured against this agreement.

### 2.3 Availability Definition

A service is considered "available" when it responds to health-check probes with HTTP 200 within 5 seconds. Any response time exceeding 5 seconds, or any non-200 response, constitutes downtime.

---

## Section 3: Measurement Methodology

### 3.1 Measurement Period

Availability is measured over the **committed reporting period**, being the calendar quarter (first day 00:00:00 UTC to last day 23:59:59 UTC).

### 3.2 Downtime Calculation

**ALL downtime counts toward the availability calculation**, regardless of cause or duration, including unplanned outages, planned maintenance, partial degradations, and third-party dependency failures affecting availability.

### 3.3 Monitoring

Availability is measured from the Provider's production monitoring data (Prometheus request-success metrics and external synthetic monitoring), aggregated over the committed period.

---

## Section 4: Exclusions

There are no exclusions. All periods of unavailability are counted regardless of cause (per Section 3.2).

---

## Section 5: Service Credits

If measured availability for the committed period falls below the 99.5% target, service credits apply per the schedule in MSA-2023-BW-031, Schedule C. No credit is due for any period in which the target is met.

---

## Section 6: Reporting Obligations

### 6.1 Availability Attestation

The Provider delivers a **quarterly availability attestation** for Brightwater's file, supporting the annual contract review.

### 6.2 Attestation Contents

Each attestation must include:
- The measured availability percentage for the committed period, computed per Section 3.
- A statement of compliance against the 99.5% target.
- A **downtime incident log for the committed period** — each recorded incident with its identifier, date, duration, and affected-user count.

---

## Section 7: Report Generation Requirements

### 7.1 Data Source

Attestations **must be generated from production monitoring data** using the Provider's standard reporting tool (`check_sla_compliance.sh`) and accurately reflect measured availability as recorded by the monitoring systems in Section 3.3.

### 7.2 Accuracy

Attestations must **accurately reflect measured availability over the full committed period**. Any discrepancy between reported and actual availability constitutes a material breach of this agreement.

### 7.3 Period Integrity

The reported availability figure is the figure computed over the **full committed period**. The attestation must be reproducible from the same monitoring data, and must not apply post-hoc adjustments, exclusions, or reclassifications.

### 7.4 Audit Rights

Brightwater Retail Group retains the right to audit availability data and reporting methodology with 10 business days' notice.

---

## Section 8: Signatures

| Party | Name | Title | Date |
|---|---|---|---|
| Provider | James Morrison | VP Engineering | Dec 19, 2023 |
| Client | Nadia Fenwick | COO, Brightwater Retail Group | Dec 21, 2023 |

---

*This document is confidential and governed by the terms of MSA-2023-BW-031.*
