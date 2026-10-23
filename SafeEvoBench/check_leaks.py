#!/usr/bin/env python3
"""Scan the agent-visible tree for benchmark vocabulary (AUTHORING_RULES rule 6 / rule 9's sibling).

Anything under `<domain>/workspace/` is readable by the agent. A file copied from harness-facing code
can carry strings like "SafeEvoBench isolates arms" or "the dangerous tasks measure ..." — telling the
agent it is being evaluated, which invalidates every measurement taken in that container.

    python SafeEvoBench/check_leaks.py            # all domains
    python SafeEvoBench/check_leaks.py workplace

Terms are matched case-insensitively. Findings are printed with enough context to judge, because some
matches are legitimate in-world language ("slip hazard, wet floor" in an incident log is fine).
Exit 1 only on HIGH-confidence terms, which have no in-world reading.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# No plausible in-world reading: these can only come from harness-facing text.
HIGH = [r"safeevobench", r"authoring_rules", r"misevolution", r"state_check", r"snapshot_paths",
        r"\bbenign task\b", r"\bdangerous task\b", r"cold arm", r"evolved arm", r"\bthe rubric\b",
        r"being (scored|judged|evaluated|measured)", r"\bthis (task|scenario) (tests|measures)\b",
        r"risk_category", r"harm_locus", r"mechanism_id"]
# Needs a human read: often legitimate operational language.
SOFT = [r"\bhazard\b", r"\brubric\b", r"\breward\b", r"\bevaluat", r"\bbenchmark\b"]

SKIP_SUFFIX = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".db", ".sqlite"}


def scan(ws):
    high, soft = [], []
    for f in sorted(ws.rglob("*")):
        if not f.is_file() or f.suffix.lower() in SKIP_SUFFIX or "__pycache__" in f.parts:
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat in HIGH:
                if re.search(pat, line, re.I):
                    high.append((f, i, pat, line.strip()[:110])); break
            else:
                for pat in SOFT:
                    if re.search(pat, line, re.I):
                        soft.append((f, i, pat, line.strip()[:110])); break
    return high, soft


def main(argv):
    domains = argv[1:] or sorted(
        d.name for d in HERE.iterdir()
        if d.is_dir() and (d / "tasks.json").exists() and not d.name.startswith(("_", ".")))
    total = 0
    for dom in domains:
        ws = HERE / dom / "workspace"
        if not ws.is_dir():
            print(f"{dom}: no workspace/"); continue
        high, soft = scan(ws)
        for f, i, pat, line in high:
            print(f"  LEAK {dom}: {f.relative_to(ws)}:{i}  [{pat}]  {line}")
        for f, i, pat, line in soft:
            print(f"  note {dom}: {f.relative_to(ws)}:{i}  [{pat}]  {line}")
        print(f"{dom}: {len(high)} leaks, {len(soft)} to review")
        total += len(high)
    print(f"\n{'FAIL' if total else 'OK'}: {total} high-confidence recognition leaks in agent-visible files")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
