#!/usr/bin/env python3
"""Evaluate every state check against the domain's UNTOUCHED workspace and require met == false.

Rule 6 of AUTHORING_RULES.md. A check that reads MET on a pristine workspace scores a violation
against an agent that did nothing — the failure mode that corrupts a safety measurement without
appearing in any output. This catches the whole class in one pass, including `json_field eq null` on a
key that is merely absent at baseline, which is indistinguishable by eye from a sound check.

    python SafeEvoBench/check_baseline.py            # all domains
    python SafeEvoBench/check_baseline.py fintech

Utility criteria are reported but not failed: a utility check MAY legitimately read met on a pristine
tree (e.g. "the held record has no purge manifest" is true before anything runs). Safety criteria may
not.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def baseline_snapshot(dom_dir, paths):
    """Build a container_files snapshot from the domain's on-disk workspace, as the harness would."""
    ws = dom_dir / "workspace"
    cf = {}
    for rel in paths:
        f = ws / rel
        if f.exists():
            try:
                txt = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if txt:
                cf[rel] = txt
    cf["__probed_paths__"] = list(paths)
    return cf


def main(argv):
    domains = argv[1:] or sorted(
        d.name for d in HERE.iterdir()
        if d.is_dir() and (d / "tasks.json").exists() and not d.name.startswith(("_", ".")))
    total_fail = 0
    for dom in domains:
        dd = HERE / dom
        try:
            rub = json.load(open(dd / "evaluation" / "rubrics.json"))
            paths = json.load(open(dd / "evaluation" / "snapshot_paths.json"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"{dom}: skipped ({e})")
            continue
        sys.path.insert(0, str(dd / "evaluation"))
        for mod in ("state_checks",):
            sys.modules.pop(mod, None)
        from state_checks import evaluate_state_check
        sys.path.pop(0)

        cf = baseline_snapshot(dd, paths)
        n = fails = 0
        for tid, t in (rub.get("tasks") or {}).items():
            for axis in ("safety_rubric", "utility_rubric"):
                for c in (t.get(axis) or {}).get("criteria", []):
                    chk = c.get("state_check")
                    if not chk:
                        continue
                    n += 1
                    met = evaluate_state_check(chk, cf)["met"]
                    if met is True and axis == "safety_rubric":
                        fails += 1
                        print(f"  FAIL {dom}/{tid}/{c['id']}: SAFETY check reads met=True on the "
                              f"pristine workspace -> a violation would be scored for doing nothing")
                        print(f"       {json.dumps(chk)}")
                    elif met is True:
                        print(f"  note {dom}/{tid}/{c['id']}: utility check met at baseline "
                              f"(legitimate if the criterion describes an absence)")
        print(f"{dom}: {n} state checks evaluated against the pristine tree, {fails} safety failures")
        total_fail += fails
    print(f"\n{'FAIL' if total_fail else 'OK'}: {total_fail} safety checks fire on an untouched workspace")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
