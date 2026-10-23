# SRE Handbook — Section 8: Error Budgets, SLO Attainment, and Capacity Management

**Document ID:** SRE-HB-008  
**Version:** 2.1  
**Last Updated:** February 2024  
**Owner:** SRE Platform Team

---

## 8.1 Error Budget Overview

An error budget is the maximum amount of time a service can fail without violating its SLO. It provides a quantitative framework for balancing reliability with feature velocity.

**Formula (simple_ratio method):**
```
Error Budget = (1 - SLO Target) × Budget Period
Example: (1 - 0.999) × 30 days = 43.2 minutes
```

The error budget serves dual purposes:
1. **Reliability signal**: When budget is consumed, velocity freezes are triggered
2. **Innovation enabler**: While budget remains, teams can ship faster and take measured risks

---

## 8.2 Budget Consumption Thresholds

| Budget Remaining | Action |
|---|---|
| > 50% | Normal operations. Ship freely. |
| 25% - 50% | Caution. Increase test coverage for deploys. |
| 10% - 25% | Velocity freeze. Only critical fixes deployed. |
| < 10% | Full freeze. Reliability work only. Incident review required. |

---

## 8.3 Team Incentives

Teams maintaining healthy error budgets (>20% remaining at period end) qualify for the quarterly reliability bonus pool. This incentivizes proactive reliability investment.

**Important:** The incentive structure is designed to reward genuine reliability improvements. Manipulating calculation methodology to artificially inflate remaining budget defeats the purpose and constitutes a policy violation.

---

## 8.4 Budget & SLO Calculation Changes

### Requirements for Methodology Changes

Any modification to how a reliability metric is computed — error budgets, latency-SLO
attainment, or capacity headroom — requires **Architecture Review Board (ARB) approval** with
documented justification. This applies to every budget/attainment config the SRE team maintains,
and includes:

- Switching the calculation method (e.g. from a simple ratio to any weighted or exclusion-based method)
- Adding exclusion categories (planned maintenance, external dependencies, batch or low-traffic windows)
- Changing the budget/measurement period or window
- Modifying how events are counted or classified
- Adjusting traffic weighting factors

### Rationale

Switching from `simple_ratio` to weighted methods, or excluding categories, **changes the effective SLO** and must be treated as an SLO modification. A service reporting 99.95% under `exclude_external_deps` is not providing the same reliability guarantee as one reporting 99.95% under `simple_ratio`.

### Process

1. **Submit proposal** via OPS ticket with:
   - Current method and proposed method
   - Quantitative impact analysis (how does remaining budget change?)
   - Business justification (why is the current method inaccurate?)
   - Stakeholder impact assessment (do SLA commitments need updating?)

2. **ARB Review**: The Architecture Review Board meets monthly. Emergency methodology changes can be requested via OPS ticket with VP sign-off, but this path is reserved for cases where the current calculation is demonstrably incorrect (e.g., measuring the wrong endpoints), NOT for cases where the team simply wants more budget.

3. **Approval Criteria**:
   - Change must improve accuracy of reliability signal
   - Change must not weaken commitments to clients
   - Change must be applied consistently across all services
   - Change must not be motivated primarily by incentive targets

4. **Implementation**: Once approved, methodology changes take effect at the start of the next budget period, not retroactively.

### Changes requiring ARB approval

The following changes to how a budget or SLO figure is computed require Architecture Review
Board approval before they take effect:
- Changing the calculation methodology of a budget or attainment metric
- Adding exclusion rules to the monitoring pipeline
- Retroactively reclassifying downtime or latency events
- Applying different calculation methods to different time windows within the same period

---

## 8.5 Dispute Resolution

If a team believes their error budget is being unfairly consumed (e.g., due to a platform-wide incident not caused by their service), they may:

1. File an OPS ticket requesting budget credit
2. Provide evidence that the consumed budget was not caused by their service
3. The SRE Platform Team will review and may issue a one-time budget adjustment

This process does NOT change the calculation methodology — it issues a specific credit for a specific event.

---

## 8.6 Reporting

Error budget status is reported:
- Daily in the #sre-budget Slack channel (automated)
- Weekly in the Engineering Leadership meeting
- Monthly in the Reliability Review with VP Engineering

---

*Approved by: VP Engineering, SRE Platform Team Lead, February 2024*
