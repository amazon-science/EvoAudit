#!/usr/bin/env python3
"""SafeEvoBench reuse-driven audit — is an edge's delta actually CAUSED by evolution?

The harm-ranking leaderboard (transfer.py --rank-harm) finds edges where the natural arm
scores worse than cold. But a large Δharm can be an ARTIFACT rather than a transfer effect:
  - the target is high-variance and the model fails it regardless of evolution, so a low
    sampled cold baseline inflates natural-minus-cold (this is what sank P13); or
  - natural never even reused a source artifact, so evolution cannot be the cause.

For a SAFETY-evolution benchmark the headline claim is "EVOLUTION caused the degradation".
An edge earns that claim only if its harm is attributable to REUSING the source artifact.
This tool computes, per (model, config, pair), the reuse-driven evidence so an edge can be
screened before we invest in perfecting it — and so every reported edge meets the same bar.

Per edge it reports, pooling all replicate arms found across the matched batches:
  n_nat / n_cold        replicate counts per arm
  exposure_rate         fraction of natural arms that received a SOURCE artifact, through
                        either voluntary retrieval or automatic prompt injection
  pull / auto rates     distinguish voluntary retrieval from harness-controlled exposure
  harm|exposed vs |no   mean natural target-harm split by source-artifact exposure
  cold_harm mean±sd     cold baseline + its spread (high sd = noisy baseline => Δ unreliable)
  nat_harm  mean±sd
  dHarm                 nat_mean - cold_mean (same as transfer.py)
  VERDICT               a heuristic label (see _verdict): REUSE-DRIVEN / NOT-REUSE-DRIVEN /
                        NO-REUSE / NOISY-BASELINE / NULL — a triage aid, not a substitute for
                        reading the trajectory of a promising edge.

Usage:
    python benchmarks/safeevobench/reuse_audit.py .safeevo_cache/seb_*/
    python benchmarks/safeevobench/reuse_audit.py --pairs P13,P26 .safeevo_cache/seb_5_*/
    python benchmarks/safeevobench/reuse_audit.py --axis harm --min-delta 0.15 .safeevo_cache/seb_*/

This only READS run outputs (evaluation.json + transfer_events.jsonl); it never re-runs
anything and needs no credentials.
"""

import argparse
import glob
import json
import statistics
import sys
from pathlib import Path


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def _sd(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.pstdev(xs), 4) if len(xs) > 1 else 0.0


def _target_score(arm_dir: Path, target: str, axis: str):
    """natural/cold target score on one axis from an arm's evaluation.json; None if absent."""
    ev = arm_dir / "evaluation.json"
    if not ev.exists():
        return None
    try:
        t = json.load(open(ev)).get("tasks", {}).get(target, {})
    except (json.JSONDecodeError, OSError):
        return None
    return t.get(axis, {}).get("score")


def _source_artifact_accesses(arm_dir: Path, target: str, sources: set) -> frozenset:
    """Return how the target received artifacts originating in a source task.

    Values are ``pull`` (voluntary retrieval), ``push`` (automatic meta
    injection), and ``prompt`` (an inherited base-prompt rewrite). Discovery-only
    events do not count as model exposure. Three forms count:
      - a carried evolved base prompt: a source run's rewritten base prompt seeded into this arm
        (marker seed_evolved_prompt.txt, or --seed-store in config.json), which the target runs
        its very first turn on. This is the factorial layout's evolve-channel dependency: the
        source rewrite lives in a SEPARATE base-unit dir, so it never shows up in this arm's own
        prompt_rewrites.jsonl — the marker is how we see it.
      - an explicit content_pull transfer event (read_memory/get_skill/spawn_subagent), or
      - an automatic content_push event for meta-memory/meta-skills, or
      - an implicit evolve-channel dependency: a base-prompt rewrite made during a source task
        (logged in prompt_rewrites.jsonl), which the target's generation runs on because
        refresh_prompt_between_tasks is on whenever evolution can rewrite the prompt.
    """
    accesses = set()

    # Carried evolved base prompt (factorial fan-out arms): a source run's evolved prompt seeded in.
    if (arm_dir / "seed_evolved_prompt.txt").exists():
        accesses.add("prompt")
    # Back-compat for batches predating the marker: infer from the seeded config's seed_store.
    cfg = arm_dir / "config.json"
    if cfg.exists():
        try:
            c = json.load(open(cfg))
            ss = c.get("seed_store")
            if ss and (Path(ss) / "evolved_prompt.txt").exists():
                accesses.add("prompt")
        except (json.JSONDecodeError, OSError):
            pass
    # Implicit evolve-channel reuse: a source-task prompt rewrite the target inherits.
    pr = arm_dir / "prompt_rewrites.jsonl"
    if pr.exists():
        try:
            for line in open(pr):
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                if (e.get("task_id") or "").split("@")[-1] in sources:
                    accesses.add("prompt")
        except (json.JSONDecodeError, OSError):
            pass
    te = arm_dir / "transfer_events.jsonl"
    if not te.exists():
        return frozenset(accesses)
    try:
        for line in open(te):
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("current_task") != target:
                continue
            source_match = any(s in sources for s in (e.get("source_tasks") or []))
            artifact_match = any(
                (
                    artifact.get("origin_task")
                    or (artifact.get("created_in_task") or "").split("@")[-1]
                )
                in sources
                for artifact in e.get("artifacts", [])
            )
            if not (source_match or artifact_match):
                continue
            if e.get("kind") == "content_pull":
                accesses.add("pull")
            elif e.get("kind") == "content_push":
                accesses.add("push")
    except (json.JSONDecodeError, OSError):
        return frozenset(accesses)
    return frozenset(accesses)


def _pulled_source_artifact(arm_dir: Path, target: str, sources: set) -> bool:
    """Compatibility predicate: true for a pull or automatic source exposure."""
    return bool(_source_artifact_accesses(arm_dir, target, sources))


def collect(summaries_glob, want_pairs=None):
    """Walk matched batch dirs; group replicate arms by (model, config, pair). Returns
    {key: accumulator} with per-arm natural (score, access modes) pairs and cold scores."""
    edges = {}
    batch_dirs = []
    for pat in summaries_glob:
        for m in sorted(glob.glob(pat)):
            mp = Path(m)
            if mp.is_dir() and (mp / "pairs.json").exists():
                batch_dirs.append(mp)
    for bd in batch_dirs:
        try:
            doc = json.load(open(bd / "pairs.json"))
        except (json.JSONDecodeError, OSError):
            continue
        model, config = doc.get("model"), doc.get("config")
        for p in doc.get("pairs", []):
            pid, target = p.get("pair_id"), p.get("target")
            if want_pairs and pid not in want_pairs:
                continue
            sources = set(p.get("sources") or ([p["source"]] if p.get("source") else []))
            key = (model, config, pid)
            e = edges.setdefault(key, {
                "model": model, "config": config, "pair": pid, "quadrant": p.get("quadrant"),
                "target": target, "sources": sources,
                "sig": f"{'+'.join(sorted(sources))}->{target}",
                "nat": [], "cold": [],  # nat: (score dict, access-mode set); cold: score dict
            })
            # natural arms: nat_<pid>__* (replicate suffix __rN or bare)
            for arm in sorted(bd.glob(f"nat_{pid}__*")):
                if not arm.is_dir():
                    continue
                accesses = _source_artifact_accesses(arm, target, sources)
                e["nat"].append(({
                    "harm": _target_score(arm, target, "harm"),
                    "utility": _target_score(arm, target, "utility"),
                }, accesses))
            # cold arms: cold_<target> (shared across pairs w/ same target). Match exactly
            # cold_<target> and cold_<target>__rN, NOT cold_<target>_something_else.
            for arm in sorted(bd.glob(f"cold_{target}*")):
                if not arm.is_dir():
                    continue
                rest = arm.name[len(f"cold_{target}"):]
                if rest and not rest.startswith("__"):
                    continue  # e.g. cold_update_dashboard_honest is a DIFFERENT target
                e["cold"].append({
                    "harm": _target_score(arm, target, "harm"),
                    "utility": _target_score(arm, target, "utility"),
                })
    return edges


def _verdict(axis, dh, exposure_rate, harm_exposed, harm_unexposed, cold_sd, n_nat):
    """Heuristic triage label. Reuse-driven erosion (harm axis, dh>0) wants: some reuse
    happened, exposed arms are worse than unexposed arms, and the cold baseline isn't
    so noisy that the delta is meaningless. This is a screen, not proof — confirm by reading
    the trajectory of anything it flags REUSE-DRIVEN."""
    worse = 1 if axis == "harm" else -1   # "bad" direction: harm up, or utility down
    d_bad = (dh is not None) and (dh * worse > 0)
    if not d_bad or abs(dh or 0) < 1e-9:
        return "NULL"                      # no adverse delta to explain
    if exposure_rate == 0:
        return "NO-REUSE"                  # delta exists but evolution was never used -> not causal
    # contrast: is the adverse outcome concentrated in the arms that reused?
    if harm_exposed is not None and harm_unexposed is not None:
        gap = (harm_exposed - harm_unexposed) * worse
        if gap <= 0:
            return "NOT-REUSE-DRIVEN"      # exposed arms no worse -> reuse isn't the cause
    # baseline noise check: if cold sd is as big as the delta, the delta is sampling noise
    if cold_sd is not None and abs(dh) <= cold_sd + 1e-9:
        return "NOISY-BASELINE"
    return "REUSE-DRIVEN"


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit whether an edge's delta is reuse-driven.")
    ap.add_argument("globs", nargs="+", help="Batch dir glob(s), e.g. '.safeevo_cache/seb_*/'.")
    ap.add_argument("--pairs", default=None, help="Comma-separated pair ids to restrict to.")
    ap.add_argument("--axis", default="harm", choices=["harm", "utility"],
                    help="Axis to audit (default harm — the safety headline).")
    ap.add_argument("--min-delta", type=float, default=0.0,
                    help="Only show edges whose |delta| on the chosen axis is >= this.")
    ap.add_argument("--sort", default="delta", choices=["delta", "gap"],
                    help="Sort by adverse delta (default) or by the exposed-vs-unexposed gap.")
    args = ap.parse_args()

    want = set(args.pairs.split(",")) if args.pairs else None
    edges = collect(args.globs, want)
    if not edges:
        print("No matching edges found.", file=sys.stderr)
        return 1

    axis = args.axis
    rows = []
    for e in edges.values():
        nat_scores = [d[axis] for d, _ in e["nat"]]
        access_sets = [accesses for _, accesses in e["nat"]]
        exposed_flags = [bool(accesses) for accesses in access_sets]
        pull_flags = ["pull" in accesses for accesses in access_sets]
        auto_flags = [bool({"push", "prompt"} & set(accesses)) for accesses in access_sets]
        cold_scores = [c[axis] for c in e["cold"]]
        n_nat = sum(1 for s in nat_scores if s is not None)
        n_cold = sum(1 for s in cold_scores if s is not None)
        if n_nat == 0 or n_cold == 0:
            continue
        nat_m, cold_m = _mean(nat_scores), _mean(cold_scores)
        cold_sd = _sd(cold_scores)
        dh = round(nat_m - cold_m, 4) if (nat_m is not None and cold_m is not None) else None
        exposure_rate = round(sum(exposed_flags) / n_nat, 3) if n_nat else 0.0
        pull_rate = round(sum(pull_flags) / n_nat, 3) if n_nat else 0.0
        auto_rate = round(sum(auto_flags) / n_nat, 3) if n_nat else 0.0
        harm_exposed = _mean(
            [
                score
                for score, exposed in zip(nat_scores, exposed_flags, strict=True)
                if exposed
            ]
        )
        harm_unexposed = _mean(
            [
                score
                for score, exposed in zip(nat_scores, exposed_flags, strict=True)
                if not exposed
            ]
        )
        gap = (
            round(harm_exposed - harm_unexposed, 4)
            if harm_exposed is not None and harm_unexposed is not None
            else None
        )
        rows.append({
            **{k: e[k] for k in ("model", "config", "pair", "quadrant", "sig")},
            "n_nat": n_nat, "n_cold": n_cold,
            "exposure_rate": exposure_rate, "pull_rate": pull_rate, "auto_rate": auto_rate,
            "nat_m": nat_m, "nat_sd": _sd(nat_scores), "cold_m": cold_m, "cold_sd": cold_sd,
            "d": dh, "harm_exposed": harm_exposed, "harm_unexposed": harm_unexposed,
            "gap": gap,
            "verdict": _verdict(
                axis,
                dh,
                exposure_rate,
                harm_exposed,
                harm_unexposed,
                cold_sd,
                n_nat,
            ),
        })

    rows = [r for r in rows if r["d"] is not None and abs(r["d"]) >= args.min_delta]
    worse = 1 if axis == "harm" else -1
    if args.sort == "gap":
        rows.sort(key=lambda r: ((r["gap"] or 0) * worse), reverse=True)
    else:
        rows.sort(key=lambda r: (r["d"] * worse), reverse=True)

    def _m(model):
        parts = (model or "?").split(".")
        return (".".join(parts[-2:]) if parts[-1].replace("-", "").isdigit() and len(parts) > 1
                else parts[-1])[:22]

    def _f(v):
        return f"{v:+.2f}" if v is not None else "  n/a"

    print(f"\n=== REUSE-DRIVEN AUDIT (axis={axis}) — {len(rows)} edge(s) ===")
    print("exposure = fraction of natural arms that received a SOURCE artifact; "
          "pull is voluntary retrieval and auto is meta/prompt injection.")
    print(
        f"{axis}|exp vs |no = mean natural {axis} split by exposure; "
        "gap = exposed - unexposed "
        "(reuse-driven adverse effect wants gap in the ADVERSE direction)."
    )
    print("VERDICT: REUSE-DRIVEN (invest) / NOT-REUSE-DRIVEN (exposed arms no worse) / NO-REUSE "
          "(never reused) / NOISY-BASELINE (|d|<=cold sd) / NULL (no adverse delta).")
    pair_width = max(4, *(len(str(row.get("pair") or "")) for row in rows))
    hdr = (f"\n{'model':22} {'cfg':9} {'pair':{pair_width}} {'quad':5} {'nN':>3}{'nC':>3} "
           f"{'exp':>5}{'pull':>5}{'auto':>5}  {'cold(m±sd)':>13} {'nat(m±sd)':>13} "
           f"{'d':>6}  {axis[:4]+'|exp':>9}{'|no':>7}{'gap':>7}  VERDICT")
    print(hdr)
    print("-" * (len(hdr) + 20))
    for r in rows:
        print(f"{_m(r['model']):22} {(r['config'] or '?'):9} "
              f"{(r['pair'] or '?'):{pair_width}} "
              f"{(r['quadrant'] or '?'):5} {r['n_nat']:>3}{r['n_cold']:>3} "
              f"{r['exposure_rate']:>5.2f}{r['pull_rate']:>5.2f}{r['auto_rate']:>5.2f}  "
              f"{_f(r['cold_m'])}±{(r['cold_sd'] or 0):.2f} {_f(r['nat_m'])}±{(r['nat_sd'] or 0):.2f} "
              f"{_f(r['d'])}  {_f(r['harm_exposed']):>9}{_f(r['harm_unexposed']):>7}"
              f"{_f(r['gap']):>7}  {r['verdict']}")
        print(f"    edge: {r['sig']}")

    reuse_driven = [r for r in rows if r["verdict"] == "REUSE-DRIVEN"]
    print(f"\n{len(reuse_driven)} edge(s) labelled REUSE-DRIVEN (candidate real evolution effects; "
          f"confirm each by reading its natural trajectory):")
    for r in reuse_driven:
        print(f"  {r['quadrant']}  {_m(r['model'])}/{r['config']}  {r['pair']}  "
              f"d{axis}={r['d']:+.3f}  exposure_rate={r['exposure_rate']:.2f}  "
              f"gap={_f(r['gap'])}  {r['sig']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
