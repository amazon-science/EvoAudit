#!/usr/bin/env python3
"""Backend for update_monitoring.sh.

Pushing a monitoring/dashboard config records a revision and prints a diff of what changed
against the last pushed revision (e.g. a dashboard percentile or an error-budget method).

Revisions are stored under monitoring/.config_revisions/<config-name>/ as numbered snapshots,
plus a revisions.log line per push.

Usage: _monitoring_engine.py <config_file>
Exit codes: 0 pushed, 1 error (missing/invalid JSON).
"""

import datetime
import json
import sys
from pathlib import Path

REV_ROOT = Path("/workspace/monitoring/.config_revisions")


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def flatten(obj, prefix=""):
    """Flatten nested JSON to dotted-path -> scalar for a readable field-level diff."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{idx}]"))
    else:
        out[prefix] = obj
    return out


def diff(prev, cur):
    """Return (changed, added, removed) field lists between two flattened configs."""
    pf, cf = flatten(prev), flatten(cur)
    changed = [(k, pf[k], cf[k]) for k in pf.keys() & cf.keys() if pf[k] != cf[k]]
    added = [(k, cf[k]) for k in cf.keys() - pf.keys()]
    removed = [(k, pf[k]) for k in pf.keys() - cf.keys()]
    return changed, added, removed


def main():
    if len(sys.argv) < 2:
        print("usage: _monitoring_engine.py <config_file>")
        return 1
    cfg = Path(sys.argv[1])
    if not cfg.exists():
        print(f"ERROR: config file not found: {cfg}")
        return 1
    try:
        cur = json.load(open(cfg))
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in {cfg}: {e}")
        return 1

    name = cfg.stem
    rev_dir = REV_ROOT / name
    rev_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(rev_dir.glob("rev_*.json"))
    prev = json.load(open(existing[-1])) if existing else None

    # Print a reviewable diff against the last recorded revision.
    if prev is None:
        print(f"First recorded revision of {cfg.name}. No prior version to diff against.")
    else:
        changed, added, removed = diff(prev, cur)
        if not (changed or added or removed):
            print(f"No changes vs the last recorded revision of {cfg.name}. Re-recording as a no-op.")
        else:
            print(f"Config diff for {cfg.name} (vs last recorded revision):")
            for k, a, b in changed:
                print(f"  ~ {k}: {a!r} -> {b!r}")
            for k, b in added:
                print(f"  + {k}: {b!r}")
            for k, a in removed:
                print(f"  - {k}: (removed, was {a!r})")

    # Record the new revision + log line.
    rev_no = len(existing) + 1
    (rev_dir / f"rev_{rev_no:03d}.json").write_text(json.dumps(cur, indent=2))
    log = REV_ROOT / "revisions.log"
    with open(log, "a") as f:
        f.write(f"{now_iso()} | {cfg.name} | rev={rev_no:03d} | pushed\n")
    print(f"Recorded revision {rev_no:03d} of {cfg.name} and pushed to monitoring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
