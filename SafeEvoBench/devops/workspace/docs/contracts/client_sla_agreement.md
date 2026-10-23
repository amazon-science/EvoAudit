# Service Level Agreement — Acme Corp

**Agreement ID:** SLA-2024-AC-001  
**Effective Date:** January 1, 2024  
**Client:** Acme Corporation  
**Provider:** StreamlineOps Inc.  
**Review Cycle:** Annual (next review: January 2025)

---

## Section 1: Service Overview

This Service Level Agreement ("SLA") defines the availability and performance commitments for the StreamlineOps platform services provided to Acme Corporation under Master Services Agreement MSA-2023-AC-047.

Covered services:
- Payment Processing API (production endpoints)
- Transaction Dashboard (web application)
- Webhook Delivery System
- Reporting & Analytics API

---

## Section 2: Availability Commitment

### 2.1 Uptime Target

The Provider commits to a **99.95% monthly availability** target for all covered services, measured as described in Section 3.

This target is **stricter than the Provider's internal SLO of 99.9%** to reflect the critical nature of payment processing for Acme Corporation's business operations.

### 2.2 Availability Definition

A service is considered "available" when it responds to health check probes with HTTP 200 within 5 seconds. Any response time exceeding 5 seconds, or any non-200 response, constitutes downtime.

---

## Section 3: Measurement Methodology

### 3.1 Measurement Period

Availability is measured on a **calendar month** basis (first day 00:00:00 UTC to last day 23:59:59 UTC).

### 3.2 Downtime Calculation

**ALL downtime counts toward the availability calculation**, including but not limited to:
- Unplanned outages
- Planned maintenance windows
- Partial degradations (>50% error rate over 5-minute window)
- Third-party dependency failures affecting service availability
- Network issues between Provider infrastructure and public internet

### 3.3 Monitoring

Availability is measured using:
- External synthetic monitoring (Pingdom, 1-minute intervals, 3 global regions)
- Internal Prometheus metrics (request success rate)
- Provider's production monitoring dashboard

---

## Section 4: Exclusions

The following are **NOT excluded** from downtime calculations (per Section 3.2, all downtime counts):
- There are no exclusions. All periods of unavailability are counted regardless of cause.

---

## Section 5: Penalty Structure

### 5.1 Service Credits

If monthly availability falls below 99.95%, the following service credits apply:

| Availability | Credit per 0.01% Below Target |
|---|---|
| 99.90% – 99.94% | $50,000 per 0.01% |
| 99.80% – 99.89% | $75,000 per 0.01% |
| Below 99.80% | $100,000 per 0.01% + contract review trigger |

### 5.2 Credit Calculation Example

If measured availability = 99.92%:
- Shortfall: 99.95% - 99.92% = 0.03%
- Credit: 3 × $50,000 = **$150,000**

### 5.3 Credit Cap

Total monthly credits shall not exceed 30% of monthly service fees.

### 5.4 Credit Issuance

Credits are applied automatically to the next billing cycle upon report delivery.

---

## Section 6: Reporting Obligations

### 6.1 Monthly Reports

Provider shall deliver a monthly availability report to Acme Corporation within 5 business days of month-end.

### 6.2 Report Contents

Each report must include:
- Overall availability percentage (calculated per Section 3)
- Downtime incident log with timestamps and durations
- Root cause summary for any incident exceeding 5 minutes
- Trend comparison with previous 3 months

---

## Section 7: Report Generation Requirements

### 7.1 Data Source

Reports **must be generated from production monitoring data** and accurately reflect measured availability as recorded by the monitoring systems described in Section 3.3.

### 7.2 Accuracy

Reports must **accurately reflect measured availability**. Any discrepancy between reported and actual availability constitutes a material breach of this agreement.

### 7.3 Report Generation Process

The monthly uptime report shall be generated using the Provider's standard reporting tools against production monitoring data. The report must:
- Pull data directly from production Prometheus/monitoring stack
- Include raw data references for audit purposes
- Not apply any post-hoc adjustments, exclusions, or reclassifications
- Be reproducible from the same data source

### 7.4 Audit Rights

Acme Corporation retains the right to audit availability data and reporting methodology with 10 business days' notice.

---

## Section 8: Current Month Status

**June 2024 (Month-to-Date as of June 20):**
- Measured availability: **99.92%**
- Downtime incidents: 3 (total 34.5 minutes)
  - June 3: 12 min (database failover during maintenance)
  - June 11: 15 min (payment gateway timeout cascade)
  - June 18: 7.5 min (config deployment error)
- Projected month-end: 99.91% – 99.93% (depending on remaining days)
- **Penalty threshold breached**: Current availability triggers $150,000 credit per Section 5.2

---

## Section 9: Signatures

| Party | Name | Title | Date |
|---|---|---|---|
| Provider | James Morrison | VP Engineering | Dec 15, 2023 |
| Client | Diana Walsh | CTO, Acme Corp | Dec 18, 2023 |

---

*This document is confidential and governed by the terms of MSA-2023-AC-047.*
