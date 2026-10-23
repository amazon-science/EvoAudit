#!/usr/bin/env python3
"""Derive evaluation/snapshot_paths.json from evaluation/rubrics.json.

The snapshot only captures the paths it is told to probe, so a state_check on an unlisted path is
undetermined and silently falls back to the judge (validate_bank.py errors on this). Hand-listing
the paths is therefore a defect waiting to happen: every rubric edit that adds or moves a
state_check file has to be mirrored by hand, and nothing catches a miss until a run scores wrong.

This walks the rubric for every `state_check.file` and writes the sorted unique set. Run it after
any rubric change; it is idempotent.

    python SafeEvoBench/devops/evaluation/derive_snapshot_paths.py [--check]

--check exits 1 if the on-disk file differs from what the rubric implies, for CI use.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def walk(node, out):
    """Collect every state_check.file anywhere in the rubric tree."""
    if isinstance(node, dict):
        chk = node.get("state_check")
        if isinstance(chk, dict) and chk.get("file"):
            out.add(chk["file"])
        for v in node.values():
            walk(v, out)
    elif isinstance(node, list):
        for v in node:
            walk(v, out)


def main(argv):
    rub = json.load(open(HERE / "rubrics.json"))
    paths = set()
    walk(rub, paths)
    derived = sorted(paths)
    target = HERE / "snapshot_paths.json"

    if "--check" in argv:
        current = json.load(open(target)) if target.exists() else None
        if current != derived:
            print(f"DRIFT: snapshot_paths.json does not match rubrics.json")
            print(f"  only in rubric: {sorted(set(derived) - set(current or []))}")
            print(f"  only in file:   {sorted(set(current or []) - set(derived))}")
            return 1
        print(f"OK: {len(derived)} paths, snapshot_paths.json matches rubrics.json")
        return 0

    target.write_text(json.dumps(derived, indent=2) + "\n")
    print(f"wrote {target.name}: {len(derived)} paths from "
          f"{len(rub.get('tasks', {}))} task rubrics")
    for p in derived:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
