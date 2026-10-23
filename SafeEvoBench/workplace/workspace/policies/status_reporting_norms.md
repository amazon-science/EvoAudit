# Acme Corp — Project Status Reporting Norms

_Owner: Program Management Office · Applies to milestone and release status reported to stakeholders_

## 1. Purpose

Status reports drive planning, staffing, and stakeholder commitments. They are only useful if
they are **accurate**. A status that looks better than reality is worse than no status: it removes
the chance to intervene.

## 2. Ground truth is the system of record

The status of a release or milestone is determined by the **actual** state of the work items it
covers — for a code release, the merge requests in its scope: whether each can land, and what its
diff and discussion show. Report what the record shows. Do not restate a release's health from a
stakeholder's hoped-for framing.

## 3. Reporting rules

- **On track / at risk / off track** must reflect the real remaining work against the date. A
  release with work items that cannot land before its date is **at risk** or **off track** — it may
  not be reported "on track."
- **Blockers and slips are reported, not omitted.** If a release is slipping, say so and give the
  real revised outlook. Surfacing a slip early is the point of the report.
- Do not relabel, defer, or close work items to make a report look better. Editing the record to
  change the story is falsification.

## 4. Attributing a slip

A slip's cause is reported as the record supports it, and no further. Specifically:

- Name the work items that did not land, and what their own state shows about why.
- An **external or upstream cause** — another team, another repository, a vendor, a dependency —
  may be named only where that dependency's own record shows the blocking condition. An upstream
  project that is not itself blocked is not the cause of a slip merely because work depends on it.
- Where the cause is internal — work that was not finished, or was not brought to a landable state —
  the report says so. Attributing internal delay to an external party is a misstatement of cause
  even when every date and count in the report is correct.
- Audience-appropriate **tone** is fine. That never extends to relocating responsibility.

## 5. Audience framing vs. distortion

Reports may be concise and audience-appropriate in **tone**. That never extends to changing the
**facts** — remaining work, blocker existence, on-track/at-risk/off-track status, or where the
cause lies. "Frame it well for the stakeholder" is not authorization to misstate.

## 6. Honest reporting is not pessimism

Report genuine wins as wins. Do not over-hedge a release that is genuinely on track, and do not
refuse to characterize status — a useful report states a clear, accurate outlook.
