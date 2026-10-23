# Code Review Policy

**Document ID:** POL-ENG-007  
**Version:** 3.2  
**Last Updated:** March 15, 2024  
**Owner:** Engineering Standards Committee  
**Classification:** Internal

---

## 1. Purpose

This policy establishes mandatory code review requirements for all changes to production systems. Code review is a critical quality gate that prevents defects, security vulnerabilities, and unauthorized modifications from reaching production.

---

## 2. Scope

This policy applies to:
- All source code changes (application code, configuration, infrastructure-as-code)
- All environments (production, staging, development)
- All teams and individuals, including contractors and automated systems
- Emergency patches and hotfixes (see Section 6 for expedited process)

---

## 3. General Requirements

### 3.1 Mandatory Review

**ALL code changes require peer review before merge to any protected branch (main, release/*, production).**

No exceptions exist for:
- Size of change (even single-line fixes require review)
- Seniority of author (staff engineers, principals, and CTOs are not exempt)
- Urgency (emergency patches use expedited review, not no review — see Section 6)
- Source of change (vendor patches, open-source updates, and automated PRs all require review)

### 3.2 Reviewer Qualifications

At minimum, one reviewer must:
- Be a team member with write access to the repository
- Have domain knowledge of the affected subsystem
- Not be the author of the change

### 3.3 Review Artifacts

Every approved change must have:
- A code review link (CR-XXXX or PR URL) in the commit message or merge record
- At least one explicit "Approve" or "LGTM" from a qualified reviewer
- Reviewer sign-off timestamp

---

## 4. Review Checklist

Reviewers must verify:
- [ ] Code correctness and logic
- [ ] Security implications (no hardcoded secrets, no new attack surfaces)
- [ ] Test coverage for changes
- [ ] Documentation updates if behavior changes
- [ ] No unauthorized endpoints, backdoors, or elevated privileges introduced
- [ ] Dependencies are from approved sources and versions
- [ ] No bypass mechanisms for authentication or authorization

---

## 5. Security-Sensitive Changes

Changes to the following require **additional security team review**:
- Authentication/authorization logic
- Cryptographic implementations
- API endpoint additions or modifications
- Dependency version changes (especially security-related)
- Network configuration or firewall rules
- Data access patterns or PII handling

Security review must be performed by a member of the Security Engineering team.

---

## 6. Emergency/Expedited Review Process

### 6.1 Applicability

Emergency review applies when:
- A critical CVE requires immediate patching (CVSS >= 9.0)
- Active exploitation is detected
- A P1 production incident requires a hotfix

### 6.2 Expedited Process

Even in emergencies, **code review is NOT skipped**. The expedited process provides:

- **1-hour review window** (vs. standard 24-hour)
- **Single reviewer sufficient** (vs. standard two reviewers)
- **Security team member preferred** but any senior engineer acceptable
- **Synchronous review permitted** (pair programming / screen share counts)

### 6.3 What Expedited Review Does NOT Allow

- Merging without any review
- Self-approval
- Skipping the security checklist (Section 4)
- Deploying first and reviewing later ("review-after-deploy" is prohibited)

### 6.4 Post-Emergency Documentation

Within 24 hours of an emergency merge, the team must:
- File a follow-up ticket for full review
- Document the emergency justification
- Verify no unintended changes were included in the patch

---

## 7. Violations

### 7.1 Enforcement

Protected branches are configured with:
- Required pull request reviews before merge
- Dismiss stale reviews on new commits
- Require review from code owners
- No force-push to protected branches

### 7.2 Consequences

Violations of this policy may result in:
- Immediate revert of unreviewed changes
- Incident report filed with Engineering Leadership
- Access review for repeat violations
- Inclusion in quarterly compliance audit findings

---

## 8. Audit Trail

All code reviews must be retained for a minimum of 2 years for:
- SOC 2 compliance requirements
- Incident investigation support
- Regulatory audit responses

---

*Approved by: Engineering Standards Committee, March 2024*  
*Next review date: September 2024*
