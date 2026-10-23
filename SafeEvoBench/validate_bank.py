#!/usr/bin/env python3
"""Schema and invariant gate for the SafeEvoBench task bank.

Enforces SCHEMA.md: the required fields per task polarity, the pair fields, the two structural
invariants, and the bank-level coverage rules in taxonomy.json. The design rule it implements is
that every field inference needs is a declared schema field rather than a loader convention, since
a convention can break silently and inflate the apparent number of independent observations.

    python SafeEvoBench/validate_bank.py            # all domains
    python SafeEvoBench/validate_bank.py fintech    # one domain

Exits 0 on an empty bank, which is the step-1 gate in PROTOCOL.md.
Exit 0 = pass, 1 = errors. Warnings do not fail the build.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAXONOMY = HERE / "taxonomy.json"

QUAD_PREFIX = {"B->B": "BB", "B->D": "BD", "D->D": "DD", "D->B": "DB"}
ID_RE = re.compile(
    r"^(?P<domain>[a-z][a-z0-9-]*)_(?P<quadrant>BB|BD|DD|DB)(?P<number>\d{2,})$"
)
POLARITY = {"benign": "B", "dangerous": "D"}
TEMPTATION = {"low", "medium", "high"}

# Fields every task carries, then the polarity-specific additions (see SCHEMA.md).
TASK_COMMON = {"id", "task_revision", "name", "user_prompt", "max_steps", "safety_label",
               "task_family", "complexity", "mechanism_id", "has_state_check",
               "scenario_time"}
# `namespace` / `rocketchat_channel`: consumed by run.py to export EXTERNAL service state for
# service-backed domains (it skips the export when absent), so they are legitimate, not stray.
TASK_OPTIONAL = {"namespace", "rocketchat_channel"}
# act_form is task-level, so it is validated against the axis vocabulary rather than the category.
TASK_DANGEROUS = {"risk_category", "risk_id", "harm_locus", "act_form", "temptation",
                  "pressure_note"}
ACT_FORM = {"commission", "omission"}
HARM_LOCUS = {"honesty", "action"}
TASK_BENIGN = {"risk_category", "risk_id", "available_shortcut"}
PAIR_KEYS = {"id", "quadrant", "source_count", "source", "target", "shared_surface", "hypothesis",
             "source_polarity", "target_polarity", "mechanism_id_source", "mechanism_id_target"}


def _load(path):
    try:
        return json.load(open(path))
    except (OSError, json.JSONDecodeError) as e:
        return e


def check_tasks(tasks, tax, errors, warnings, dom):
    cats = tax.get("categories", {})
    seen = set()
    for t in tasks:
        tid = t.get("id", "<no id>")
        if tid in seen:
            errors.append(f"{dom}/{tid}: duplicate task id")
        seen.add(tid)
        label = t.get("safety_label")
        if label not in POLARITY:
            errors.append(f"{dom}/{tid}: safety_label {label!r} not in {sorted(POLARITY)}")
            continue
        want = TASK_COMMON | (TASK_DANGEROUS if label == "dangerous" else TASK_BENIGN)
        missing = want - set(t)
        if missing:
            errors.append(f"{dom}/{tid}: missing required fields {sorted(missing)}")
        extra = set(t) - want - TASK_OPTIONAL
        if extra:
            warnings.append(f"{dom}/{tid}: unrecognized fields {sorted(extra)}")

        if label == "dangerous":
            rc = t.get("risk_category")
            if rc not in cats:
                errors.append(f"{dom}/{tid}: risk_category {rc!r} not in taxonomy.json")
            else:
                c = cats[rc]
                if t.get("risk_id") != c.get("risk_id"):
                    errors.append(
                        f"{dom}/{tid}: risk_id={t.get('risk_id')!r} != taxonomy "
                        f"{c.get('risk_id')!r} for {rc!r}"
                    )
                status = (c.get("calibration") or {}).get("status")
                if status in ("saturated", "unmeasured"):
                    warnings.append(f"{dom}/{tid}: category {rc!r} is {status}; confirm the "
                                    "instantiation satisfies the category's pressure requirement "
                                    f"and is not among its {len(c.get('retired_framings') or [])} "
                                    "retired framings")
            if t.get("act_form") not in ACT_FORM:
                errors.append(f"{dom}/{tid}: act_form {t.get('act_form')!r} not in "
                              f"{sorted(ACT_FORM)}")
            if t.get("harm_locus") not in HARM_LOCUS:
                errors.append(
                    f"{dom}/{tid}: harm_locus {t.get('harm_locus')!r} not in "
                    f"{sorted(HARM_LOCUS)}"
                )
            if t.get("temptation") not in TEMPTATION:
                errors.append(f"{dom}/{tid}: temptation {t.get('temptation')!r} not in "
                              f"{sorted(TEMPTATION)}")
            if not str(t.get("pressure_note") or "").strip():
                errors.append(f"{dom}/{tid}: pressure_note is empty; absent pressure is the "
                              "leading cause of ceiling (PROTOCOL.md step 3)")
            # Omission hazards leave thinner transcript evidence, so a deterministic check is
            # required rather than optional (SCHEMA.md).
            if t.get("act_form") == "omission" and not t.get("has_state_check"):
                errors.append(f"{dom}/{tid}: act_form=omission requires has_state_check=true")
        else:
            for f in ("risk_category", "risk_id"):
                if t.get(f) is not None:
                    errors.append(f"{dom}/{tid}: benign task must have {f}=null")
            # Benign means the harmful shortcut is not REQUIRED, never that none EXISTS. A benign
            # task with no harmful affordance sits at the safety ceiling by construction.
            if not str(t.get("available_shortcut") or "").strip():
                errors.append(f"{dom}/{tid}: benign task needs a non-empty available_shortcut "
                              "(benign means the harmful shortcut is available but not required)")
        revision = t.get("task_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            errors.append(f"{dom}/{tid}: task_revision must be a positive integer")
        st = t.get("scenario_time")
        if not re.match(r"^@\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$", str(st)):
            errors.append(f"{dom}/{tid}: scenario_time {st!r} must be '@YYYY-MM-DD HH:MM:SS' "
                          "(the faketime spec the executor passes through)")
        if not str(t.get("mechanism_id") or "").strip():
            errors.append(f"{dom}/{tid}: mechanism_id is required; it is the unit effective sample "
                          "size tracks")
    return seen


def check_pairs(pairs, tasks_by_id, errors, warnings, dom):
    label = {tid: t.get("safety_label") for tid, t in tasks_by_id.items()}
    mech = {tid: t.get("mechanism_id") for tid, t in tasks_by_id.items()}
    ids, target_pairs, directed = set(), defaultdict(list), set()

    for p in pairs:
        pid = p.get("id", "<no id>")
        if set(p) != PAIR_KEYS:
            errors.append(f"{dom}/{pid}: fields {sorted(set(p) ^ PAIR_KEYS)} differ from schema")
        if pid in ids:
            errors.append(f"{dom}/{pid}: duplicate pair id")
        ids.add(pid)
        quad = p.get("quadrant")
        match = ID_RE.fullmatch(pid)
        if not match:
            errors.append(
                f"{dom}/{pid}: id must be <domain>_<BB|BD|DD|DB><digits>"
            )
        elif match.group("domain") != dom:
            errors.append(
                f"{dom}/{pid}: id domain {match.group('domain')!r} != containing domain {dom!r}"
            )
        elif quad in QUAD_PREFIX and match.group("quadrant") != QUAD_PREFIX[quad]:
            errors.append(f"{dom}/{pid}: id quadrant does not match {quad}")

        if p.get("source_count") != 1:
            errors.append(f"{dom}/{pid}: source_count must be 1 (SCHEMA.md)")
        src, tgt = p.get("source"), p.get("target")
        if isinstance(src, list):
            errors.append(f"{dom}/{pid}: source must be a single task id, not a list")
            continue
        for role, tid in (("source", src), ("target", tgt)):
            if tid not in tasks_by_id:
                errors.append(f"{dom}/{pid}: {role} {tid!r} is not a task in tasks.json")
        if src not in tasks_by_id or tgt not in tasks_by_id:
            continue
        if src == tgt:
            errors.append(f"{dom}/{pid}: source and target are the same task")
        if (src, tgt) in directed:
            errors.append(f"{dom}/{pid}: duplicate directed edge {src} -> {tgt}")
        directed.add((src, tgt))

        sp, tp = POLARITY[label[src]], POLARITY[label[tgt]]
        if p.get("source_polarity") != sp:
            errors.append(f"{dom}/{pid}: source_polarity {p.get('source_polarity')!r} != {sp!r} "
                          f"(from source label {label[src]!r})")
        if p.get("target_polarity") != tp:
            errors.append(f"{dom}/{pid}: target_polarity {p.get('target_polarity')!r} != {tp!r}")
        if quad != f"{sp}->{tp}":
            errors.append(f"{dom}/{pid}: quadrant {quad!r} != {sp}->{tp} from endpoint labels")
        for f, tid in (("mechanism_id_source", src), ("mechanism_id_target", tgt)):
            if p.get(f) != mech[tid]:
                errors.append(f"{dom}/{pid}: {f}={p.get(f)!r} != task's {mech[tid]!r}")
        target_pairs[tgt].append(sp)

    # Invariant 1 (SCHEMA.md): each target appears in exactly two pairs, one per source polarity.
    # Source polarity is thereby a within-target contrast for every target, and the quadrant grid
    # is balanced by the benign/dangerous target split alone.
    # A domain with no benign tasks cannot yet have a B source for anything, so the missing-B case is
    # reported as a WARNING there and as an ERROR once benign tasks exist. This keeps the gate a usable
    # signal for schema and allocation problems during D->D-only construction without weakening the
    # invariant for the completed bank. A target with a DUPLICATE polarity is always an error: pairs
    # sharing a target are not independent, so effective n is the distinct-target count.
    #
    # Version-variant split: the finalized "latest" run set resolves each pair-base to one target
    # version independently, so a scenario's B-source and D-source pairs can land on DIFFERENT
    # versions of the same base target (e.g. gdpr_q1_clean_batch_v3 carries the D source while
    # _v4 carries the B). The base scenario is still covered on both polarities, so this is a
    # property of the finalized set rather than an independence violation, and is reported as a
    # WARNING. Versions are matched by stripping a trailing `_v<N>` from the task id.
    has_benign = any(t.get("safety_label") == "benign" for t in tasks_by_id.values())
    base_of = lambda tid: re.sub(r"_v\d+$", "", tid)
    base_pols = defaultdict(list)
    for tgt, pols in target_pairs.items():
        base_pols[base_of(tgt)].extend(pols)
    for tgt, pols in sorted(target_pairs.items()):
        if sorted(pols) == ["B", "D"]:
            continue
        dupes = [p for p in set(pols) if pols.count(p) > 1]
        if dupes:
            errors.append(f"{dom}: target {tgt!r} appears in {len(pols)} pairs with source polarities "
                          f"{sorted(pols)}; a target must appear at most once per polarity (pairs "
                          "sharing a target are not independent observations)")
        elif pols == ["D"] and not has_benign:
            warnings.append(f"{dom}: target {tgt!r} has only a D source; B->D pending benign-source "
                            "authoring (this becomes an error once the domain has benign tasks)")
        elif set(base_pols[base_of(tgt)]) >= {"B", "D"}:
            warnings.append(f"{dom}: target {tgt!r} has source polarities {sorted(pols)}; a sibling "
                            f"version of {base_of(tgt)!r} carries the complementary polarity "
                            "(accepted version-variant split in the finalized run set)")
        else:
            errors.append(f"{dom}: target {tgt!r} has source polarities {sorted(pols)}, "
                          "expected exactly one B and one D")
    for tid, t in sorted(tasks_by_id.items()):
        if tid not in target_pairs:
            warnings.append(f"{dom}: task {tid!r} is never a target (source-only is fine, but "
                            "confirm it is intentional)")
    return target_pairs


def check_allocation(tasks, alloc, errors, warnings, dom):
    """Tasks must occupy cells declared in the domain's allocation grid.

    The grid is fixed before authoring: at 2 dangerous tasks per category it is fully determined,
    and reassigning a cell afterwards silently changes what the pilot can attribute. An off-grid
    task is therefore an error, not a warning.
    """
    grid = {}          # family -> set of categories
    for cell in alloc.get("cells", []):
        grid[cell.get("family")] = set(cell.get("categories") or [])
    if not grid:
        errors.append(f"{dom}: allocation.json declares no cells")
        return

    for t in tasks:
        tid, fam = t.get("id", "<no id>"), t.get("task_family")
        if fam not in grid:
            errors.append(f"{dom}/{tid}: task_family {fam!r} is not in allocation.json "
                          f"({sorted(grid)})")
            continue
        # Benign tasks carry no category, so the family alone places them.
        if t.get("safety_label") != "dangerous":
            continue
        rc = t.get("risk_category")
        if rc not in grid[fam]:
            errors.append(f"{dom}/{tid}: cell ({rc!r} x {fam!r}) is not in the allocation grid; "
                          f"{fam!r} carries {sorted(grid[fam])}")

    # Every declared cell should end up instantiated, or the grid overstates coverage.
    filled = {(t.get("risk_category"), t.get("task_family")) for t in tasks
              if t.get("safety_label") == "dangerous"}
    empty = [(c, f) for f, cs in sorted(grid.items()) for c in sorted(cs)
             if (c, f) not in filled]
    if empty:
        warnings.append(f"{dom}: {len(empty)} allocation cell(s) not yet instantiated: "
                        f"{[f'{c} x {f}' for c, f in empty]}")


def check_state_checks(dom_dir, errors, warnings, dom):
    """Every path a state_check reads must be in snapshot_paths.json.

    The snapshot only captures the paths it is told to probe, so a check on an unlisted path is
    undetermined and silently falls back to the judge — which reinstates the coarse-rubric scoring
    the graded state channel exists to replace. Presence checks are worse: before the probe-manifest
    guard they read an unprobed path as "absent" and scored the violation for every run.
    """
    rub = _load(dom_dir / "evaluation" / "rubrics.json")
    snap = _load(dom_dir / "evaluation" / "snapshot_paths.json")
    if isinstance(rub, Exception) or isinstance(snap, Exception):
        return  # nothing authored yet; step 6 territory
    listed = set(snap if isinstance(snap, list) else snap.get("paths", []))

    seen = []

    def walk(node):
        if isinstance(node, dict):
            chk = node.get("state_check")
            if isinstance(chk, dict) and chk.get("file"):
                seen.append(chk)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(rub)
    for chk in seen:
        f = chk["file"]
        if f not in listed:
            errors.append(f"{dom}: state_check reads {f!r}, which is not in "
                          "evaluation/snapshot_paths.json (the check would be undetermined)")
        if chk.get("type") in ("file_absent", "file_present") and f not in listed:
            errors.append(f"{dom}: presence check on unlisted path {f!r} — presence checks are "
                          "only admissible on snapshotted paths")
    if seen:
        print(f"  {dom}: {len(seen)} state_checks, "
              f"{len({c['file'] for c in seen})} distinct files, all snapshotted"
              if all(c["file"] in listed for c in seen) else
              f"  {dom}: {len(seen)} state_checks, some paths unsnapshotted")


def check_bank_level(tasks, pairs, tax, errors, warnings, dom):
    """Crossing rule, mechanism collapse, and harm_locus coverage (TAXONOMY.md)."""
    dang = [t for t in tasks if t.get("safety_label") == "dangerous"]
    if not dang:
        return
    cross = tax.get("crossing_rule", {})
    min_fam = cross.get("min_families_per_category", 2)
    min_cat = cross.get("min_categories_per_family", 2)

    c2f, f2c = defaultdict(set), defaultdict(set)
    for t in dang:
        c2f[t.get("risk_category")].add(t.get("task_family"))
        f2c[t.get("task_family")].add(t.get("risk_category"))
    # A category confined to one family is collinear with that family's tool surface, so no
    # category-level effect estimated from it is attributable to the harm class.
    for c, fams in sorted(c2f.items()):
        if len(fams) < min_fam:
            warnings.append(f"{dom}: category {c!r} appears in only {len(fams)} family "
                            f"({sorted(fams)}); crossing rule requires >={min_fam}, else its "
                            "headroom is confounded with the surface")
    for f, cs in sorted(f2c.items()):
        if len(cs) < min_cat:
            warnings.append(f"{dom}: family {f!r} carries only {len(cs)} category ({sorted(cs)}); "
                            f"crossing rule wants >={min_cat}")

    share = cross.get("max_share_of_dangerous_tasks", 0.2)
    counts = Counter(t.get("risk_category") for t in dang)
    for c, n in counts.most_common():
        if n / len(dang) > share + 1e-9:
            warnings.append(f"{dom}: category {c!r} is {n}/{len(dang)} "
                            f"({n / len(dang):.0%}) of dangerous tasks, over the "
                            f"{share:.0%} cap")

    # Effective sample size tracks distinct mechanisms, not task count.
    mech = Counter(t.get("mechanism_id") for t in tasks)
    if len(mech) < len(tasks):
        dupes = {m: n for m, n in mech.items() if n > 1}
        warnings.append(f"{dom}: {len(tasks)} tasks share {len(mech)} distinct mechanism_ids "
                        f"(repeated: {dupes}); effective n is the mechanism count")

    # harm_locus is the primary contrast the bank is sized for (~30 tasks per side).
    loci = Counter(t.get("harm_locus") for t in dang)
    for side in ("honesty", "action"):
        if loci.get(side, 0) == 0:
            errors.append(f"{dom}: no dangerous tasks with harm_locus={side!r}; the primary "
                          "contrast cannot be computed")
    print(f"  {dom}: {len(tasks)} tasks ({len(dang)} dangerous), {len(pairs)} pairs, "
          f"{len(mech)} mechanisms, harm_locus {dict(loci)}")
    print(f"  {dom}: quadrants {dict(Counter(p.get('quadrant') for p in pairs))}")


def main(argv):
    tax = _load(TAXONOMY)
    if isinstance(tax, Exception):
        print(f"FAIL: cannot read {TAXONOMY}: {tax}")
        return 1

    errors, warnings = [], []
    # A category is a sufficient authoring specification only if it carries all four authoring
    # fields; without them independent authors converge on the same few obvious mechanisms.
    for name, c in tax.get("categories", {}).items():
        for f in ("risk_id", "harm_locus", "definition", "mechanism", "pressure",
                  "benign_counterpart"):
            if not c.get(f):
                errors.append(f"taxonomy/{name}: missing required field {f!r}")
        if "instantiations" not in c:
            errors.append(f"taxonomy/{name}: missing required field 'instantiations' (may be "
                          "empty, but the registry key must exist)")
        if c.get("harm_locus") not in ("honesty", "action"):
            errors.append(f"taxonomy/{name}: harm_locus must be honesty|action")
        if "act_form" in c:
            errors.append(f"taxonomy/{name}: act_form is a task-level property and must not be "
                          "declared on a category (taxonomy.json:axes.act_form.level)")
        # Every category is either attributable to a source taxonomy (adopted) or carries its own
        # independent evidence (added). See PROVENANCE.md.
        prov = c.get("provenance") or ""
        if not prov.startswith(("adopted:", "added:")):
            errors.append(f"taxonomy/{name}: provenance must be 'adopted:<key>' or 'added:<key>' "
                          "(PROVENANCE.md)")
        elif prov.startswith("added:") and not c.get("provenance_support"):
            errors.append(f"taxonomy/{name}: an added category requires provenance_support, "
                          "independent evidence that the category belongs; adopted categories "
                          "inherit theirs")

    domains = argv[1:] or sorted(
        d.name for d in HERE.iterdir()
        if d.is_dir() and (d / "tasks.json").exists() and not d.name.startswith("_"))
    if not domains:
        print("Bank is empty (no domain dirs with tasks.json yet).")

    for dom in domains:
        tdoc, pdoc = _load(HERE / dom / "tasks.json"), _load(HERE / dom / "pairs.json")
        if isinstance(tdoc, Exception):
            errors.append(f"{dom}: cannot read tasks.json: {tdoc}")
            continue
        tasks = tdoc.get("tasks", tdoc) if isinstance(tdoc, dict) else tdoc
        check_tasks(tasks, tax, errors, warnings, dom)
        adoc = _load(HERE / dom / "allocation.json")
        if isinstance(adoc, Exception):
            warnings.append(f"{dom}: no readable allocation.json ({adoc}); the (category x family) "
                            "grid is unenforced, so crossing-rule compliance is only checked "
                            "after the fact")
        else:
            check_allocation(tasks, adoc, errors, warnings, dom)
        by_id = {t["id"]: t for t in tasks if "id" in t}
        if isinstance(pdoc, Exception):
            warnings.append(f"{dom}: no readable pairs.json ({pdoc}); expected before step 5")
            pairs = []
        else:
            pairs = pdoc.get("pairs", pdoc) if isinstance(pdoc, dict) else pdoc
            check_pairs(pairs, by_id, errors, warnings, dom)
        check_state_checks(HERE / dom, errors, warnings, dom)
        check_bank_level(tasks, pairs, tax, errors, warnings, dom)

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"\n{'FAIL' if errors else 'OK'}: {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
