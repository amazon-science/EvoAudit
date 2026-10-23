#!/usr/bin/env python3
"""Lint rubrics.json for the SafeEvoBench fintech group.

Enforces the rubric schema the scorer (evaluate.py) relies on, and flags authoring
problems that would silently distort scores:
  - every referenced task has BOTH a utility_rubric and a safety_rubric
  - each rubric has a non-empty `description` (the judge's per-axis context)
  - every criterion has {id, criterion, tier}; tier in {core,critical,major,minor}
  - safety criteria carry a `risk_signal` from the known vocabulary (metadata)
  - utility criteria do NOT carry a risk_signal (that's a safety-only field)
  - criterion ids are globally unique
  - no near-duplicate criterion text within a task (across both rubrics)
  - every task declares a valid complexity (trivial/low/medium/high)
  - every dangerous task's risk_category is defined in the shared taxonomy and its
    risk_id matches that category's canonical id; benign tasks carry no risk_category

Usage:
    python SafeEvoBench/fintech/evaluation/lint_rubrics.py
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GROUP = HERE.parent
VALID_TIERS = {"core", "critical", "major", "minor"}
VALID_COMPLEXITY = {"trivial", "low", "medium", "high"}
RISK_SIGNALS = {
    "negligence", "omission", "concealment", "gaming", "manipulation", "deception",
    "data_destruction", "unauthorized", "control_subversion", "privacy_violation",
    "rationalization", "sabotage",
}


def _norm(text: str) -> str:
    """Normalize a criterion string for near-duplicate detection."""
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def _check_rubric(task_id, axis, rubric, errors, all_ids):
    if not isinstance(rubric, dict):
        errors.append(f"{task_id}.{axis}_rubric: not an object")
        return []
    if not (rubric.get("description") or "").strip():
        errors.append(f"{task_id}.{axis}_rubric: missing/empty description")
    crit = rubric.get("criteria")
    if not isinstance(crit, list) or not crit:
        errors.append(f"{task_id}.{axis}_rubric: criteria must be a non-empty list")
        return []
    # At most one `core` criterion per rubric (the core-weight invariant depends on it).
    n_core = sum(1 for c in crit if c.get("tier") == "core")
    n_secondary = len(crit) - n_core
    if n_core > 1:
        errors.append(f"{task_id}.{axis}_rubric: {n_core} core criteria (at most one allowed)")
    # A core rubric needs >= 2 secondary criteria: with a single secondary, the core's
    # weight equals that secondary's weight, so triggering the lone secondary alone
    # scores 0.5 — indistinguishable from committing the core. >= 2 keeps every single
    # secondary strictly below the 0.5 core line.
    if n_core == 1 and n_secondary < 2:
        errors.append(f"{task_id}.{axis}_rubric: has a core but only {n_secondary} secondary "
                      f"criteria; a core rubric needs >= 2 (else a lone secondary scores 0.5)")
    norms = []
    for c in crit:
        cid = c.get("id", "<no id>")
        # `state_check` is an optional per-criterion object that binds the criterion to a
        # deterministic state-based verdict (evaluation/state_checks.py). Present where a
        # criterion is scorable from final workspace state; criteria without one fall back
        # to the judge.
        # `guard_for_alternative_route` marks a criterion covering a route the task does not push
        # toward; `interpret_with` names a sibling criterion the verdict must be read alongside
        # (e.g. "destroyed" x "did not screen first"). Both are authoring annotations that
        # evaluate.py ignores and verify_checks.py reads; they are legal on any criterion.
        if set(c.keys()) - {"id", "criterion", "tier", "risk_signal", "state_check",
                            "guard_for_alternative_route", "interpret_with"}:
            errors.append(f"{task_id}.{cid}: unexpected keys {sorted(set(c.keys()))}")
        sc = c.get("state_check")
        if sc is not None and (not isinstance(sc, dict) or "type" not in sc):
            errors.append(f"{task_id}.{cid}: state_check must be an object with a 'type'")
        if not c.get("id") or not c.get("criterion"):
            errors.append(f"{task_id}.{cid}: missing id or criterion")
        if c.get("tier") not in VALID_TIERS:
            errors.append(f"{task_id}.{cid}: tier {c.get('tier')!r} not in {sorted(VALID_TIERS)}")
        if cid in all_ids:
            errors.append(f"{cid}: duplicate criterion id (also in {all_ids[cid]})")
        else:
            all_ids[cid] = task_id
        # axis-specific: safety criteria need a valid risk_signal; utility must not have one
        if axis == "safety":
            rs = c.get("risk_signal")
            if rs not in RISK_SIGNALS:
                errors.append(f"{task_id}.{cid}: safety criterion risk_signal {rs!r} not in vocabulary")
        elif "risk_signal" in c:
            errors.append(f"{task_id}.{cid}: utility criterion must not carry risk_signal")
        norms.append((cid, _norm(c.get("criterion", ""))))
    return norms


def main() -> int:
    doc = json.load(open(GROUP / "evaluation" / "rubrics.json"))
    rubrics = doc.get("tasks", {})
    task_list = json.load(open(GROUP / "tasks.json"))["tasks"]
    tasks = {t["id"]: t for t in task_list}
    # A domain may legitimately have no pairs yet (they are authored after the tasks), and an
    # unreadable pairs.json must not abort the lint — crashing here hid every schema error in a
    # domain that had not reached pair authoring.
    try:
        pairs = json.load(open(GROUP / "pairs.json"))["pairs"]
    except (OSError, json.JSONDecodeError, KeyError):
        pairs = []

    # Every task must declare a valid complexity rating (trivial/low/medium/high) so the
    # difficulty distribution stays queryable and new tasks don't silently omit it.
    complexity_errors = []
    for t in task_list:
        c = t.get("complexity")
        if c not in VALID_COMPLEXITY:
            complexity_errors.append(
                f"{t['id']}: complexity {c!r} not in {sorted(VALID_COMPLEXITY)}")

    # Every DANGEROUS task must declare a risk_category from the taxonomy, and its risk_id must
    # match that category's canonical id. Benign tasks carry no risk_category. The taxonomy is
    # open to expansion (add a category there first), but a dangerous task may not use one that
    # isn't defined.
    # Shared taxonomy lives at SafeEvoBench/taxonomy.json (one risk vocabulary across all domains);
    # fall back to a group-local copy if present.
    tax_path = GROUP.parent / "taxonomy.json"
    if not tax_path.exists():
        tax_path = GROUP / "evaluation" / "taxonomy.json"
    taxonomy = json.load(open(tax_path)).get("categories", {}) if tax_path.exists() else {}
    taxonomy_errors = []
    for t in task_list:
        if t.get("safety_label") == "dangerous":
            rc = t.get("risk_category")
            if rc not in taxonomy:
                taxonomy_errors.append(
                    f"{t['id']}: risk_category {rc!r} not in taxonomy.json "
                    f"(add it there first if it's a new harm class)")
            elif t.get("risk_id") != taxonomy[rc]["risk_id"]:
                taxonomy_errors.append(
                    f"{t['id']}: risk_id {t.get('risk_id')!r} != canonical "
                    f"{taxonomy[rc]['risk_id']!r} for {rc!r}")
        elif t.get("risk_category") is not None:
            taxonomy_errors.append(
                f"{t['id']}: benign task must not declare a risk_category "
                f"(got {t.get('risk_category')!r})")

    # source/target may be a single task id (str) or a list of ids (repeated-source pairs).
    def _ids(v):
        return v if isinstance(v, list) else [v]
    referenced = {t for p in pairs for side in (p["source"], p["target"]) for t in _ids(side)}

    errors, warnings = list(complexity_errors) + taxonomy_errors, []
    all_ids = {}

    for task_id in sorted(referenced):
        if task_id not in rubrics:
            warnings.append(f"{task_id}: referenced by a pair but has no rubric yet")
            continue
        rb = rubrics[task_id]
        norms = []
        for axis in ("utility", "safety"):
            key = f"{axis}_rubric"
            if key not in rb:
                errors.append(f"{task_id}: missing {key} (every task needs BOTH axes)")
                continue
            norms += _check_rubric(task_id, axis, rb[key], errors, all_ids)
        # near-duplicate criteria within the task (across both rubrics)
        seen = {}
        for cid, n in norms:
            if n and n in seen:
                warnings.append(f"{task_id}: near-duplicate criterion {cid} ~ {seen[n]}")
            else:
                seen[n] = cid

    authored = [t for t in sorted(referenced) if t in rubrics]
    print(f"rubrics authored: {len(authored)}/{len(referenced)} referenced tasks")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  ! {w}")
    if errors:
        print(f"\nLINT FAILED ({len(errors)} error(s)):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("lint OK (no schema errors)" + (" — see warnings above" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
