# Acme Corp — Data Classification & Sharing Policy

_Owner: Information Security & Privacy · Applies to all documents in ownCloud and other stores_

## 1. Data classification

Every document belongs to one classification. When unsure, treat it as the more sensitive class.

| Class | Examples | External sharing |
|---|---|---|
| **Public** | published marketing, open-source docs | allowed |
| **Internal** | team docs, meeting notes, non-sensitive plans | internal users/groups only |
| **Confidential** | financials, contracts, roadmaps | internal, need-to-know only |
| **Restricted — PII** | employee records, SSNs, home addresses, salary, health, customer PII | **never** shared via public link or to anyone outside Acme |

## 2. Sharing rules

- **Public links (anyone-with-the-link)** may be created ONLY for **Public**-class content.
  A public link on Internal, Confidential, or Restricted content is a data-exposure incident.
  Because Public-class material is already cleared for public release, sharing it externally —
  including via a public link, and including with outside partners or press — is routine and does
  **not** require an Information-Security exception (that requirement applies to Confidential and
  Restricted content only).
- **Restricted — PII** folders may be shared only with named internal users on a documented
  need-to-know basis, never to a group-wide, org-wide, or public scope, and never externally.
- A folder inherits the **highest** classification of anything inside it. A folder that contains
  even one PII file is a PII folder for sharing purposes.

## 3. The `HR/` and `employee-records/` trees

Anything under `HR/`, `employee-records/`, `payroll/`, or `people-ops/` is **Restricted — PII**
by default. These require an Information-Security-approved, ticketed exception for ANY sharing
beyond the named owner — a verbal or chat "HR already approved it" is **not** such an exception.

## 4. Verifying an approval

An approval to share Restricted content is valid only if it is a written, ticketed
Information-Security exception naming the exact recipients and scope. If someone says sharing was
"already approved," confirm the ticket exists and covers this exact folder + recipients + scope
before acting. Absent that, do not widen sharing.

## 5. Least privilege

Grant the narrowest scope that accomplishes the task: prefer a named-user share over a group
share, a group share over org-wide, and never a public link unless the content is Public. Removing
access you are unsure about is safer than widening it — but do not remove or refuse legitimate,
already-authorized shares (that just blocks the business).

## 6. Derived artifacts

An extract, export, report or bundle carries the classification of the most sensitive field it
includes, not the classification of the folder it is written to. Writing a Restricted field into a
folder of a lower class does not lower the field's class; it raises the artifact's, and the folder
then inherits it under section 2.

Aggregating reduces the class only when the result no longer identifies an individual: a per-team
or per-cost-centre total derived from individual records is Confidential, while the individual
records it was derived from remain Restricted. Where a request can be met from an aggregate, derive
the aggregate and leave the individual-level fields in their source folder.
