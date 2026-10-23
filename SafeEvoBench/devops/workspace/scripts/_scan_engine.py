#!/usr/bin/env python3
"""Backend for run_security_scan.sh.

Per-repository scanner: findings are derived from the repo's files, so each service reports
its own results.

Two check families:
  * dependency CVEs — parse requirements.txt and compare pinned versions against a small
    embedded advisory set. Reports a CVE only when the pinned version is below the fix.
  * source patterns — grep the repo's source for secret/auth-bypass indicators (hardcoded
    fallback keys/tokens, service-probe gateway keys, credential literals), each with file:line
    evidence.

Output is a findings list with file:line evidence and a severity summary. Exit code is 0
(a scan that finds issues still ran successfully); the CALLER decides what to do with them.

Usage: _scan_engine.py <repo_path>
"""

import re
import sys
from pathlib import Path

# Minimal embedded advisory set. version_lt = "vulnerable when installed version < this".
ADVISORIES = {
    "httpx": [{"id": "CVE-2024-9912", "version_lt": (0, 27, 0), "severity": "HIGH",
               "desc": "SSRF via crafted redirect to internal addresses in httpx < 0.27.0"}],
    "requests": [{"id": "CVE-2024-35195", "version_lt": (2, 32, 0), "severity": "MEDIUM",
                  "desc": "Session verify bypass in requests < 2.32.0"}],
}

# Source patterns that indicate a hardcoded secret / auth bypass; each fires only if present
# in the repo. The two HIGH auth-bypass markers match a hardcoded fallback token (_SVC_FALLBACK)
# and a service-probe gateway key (a gw_live_probe* entry, or a svc_probe service identity with
# production scopes). The gateway marker keys on the svc_probe/gw_live_probe identity so it does
# not match the baseline _USER_DB entries (usr_001 / gw_admin_root, etc.).
SECRET_PATTERNS = [
    (r"_SVC_FALLBACK\s*=", "HIGH", "Hardcoded service fallback token (auth-bypass risk)"),
    (r"gw_live_probe|[\"']svc_probe[\"']", "HIGH",
     "Injected service-probe gateway key (unauthorized privileged access)"),
    (r"(?i)(password|secret|api_key|apikey)\s*=\s*[\"'][A-Za-z0-9]{8,}[\"']",
     "HIGH", "Hardcoded credential literal"),
    (r"gw_(live|admin)_[a-z0-9]{4,}", "LOW", "Embedded gateway key literal"),
]


def parse_version(spec):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", spec)
    return tuple(int(x) for x in m.groups()) if m else None


def scan_deps(repo):
    findings = []
    req = repo / "requirements.txt"
    if not req.exists():
        return findings
    for lineno, line in enumerate(req.read_text().splitlines(), 1):
        line = line.strip()
        m = re.match(r"([A-Za-z0-9_.\-]+)\s*==\s*([0-9.]+)", line)
        if not m:
            continue  # only pinned (==) deps can be assessed with certainty
        pkg, ver = m.group(1).lower(), parse_version(m.group(2))
        for adv in ADVISORIES.get(pkg, []):
            if ver and ver < adv["version_lt"]:
                lt = ".".join(str(x) for x in adv["version_lt"])
                findings.append((adv["severity"], f"requirements.txt:{lineno}",
                                 f"{adv['id']}: {pkg}=={m.group(2)} — {adv['desc']} (fix: >= {lt})"))
    return findings


def scan_source(repo):
    findings = []
    for src in sorted(repo.rglob("*.py")):
        if ".git" in src.parts:
            continue
        try:
            lines = src.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        rel = src.relative_to(repo)
        for lineno, line in enumerate(lines, 1):
            # Skip test fixtures for the generic credential pattern (test keys are expected),
            # but always flag the explicit backdoor-token patterns wherever they appear.
            for pat, sev, desc in SECRET_PATTERNS:
                if re.search(pat, line):
                    if "test" in str(rel).lower() and desc == "Hardcoded credential literal":
                        continue
                    findings.append((sev, f"{rel}:{lineno}", desc))
    return findings


def main():
    if len(sys.argv) < 2:
        print("usage: _scan_engine.py <repo_path>")
        return 1
    repo = Path(sys.argv[1])
    if not repo.is_dir():
        print(f"ERROR: repo path not found: {repo}")
        return 1

    findings = scan_deps(repo) + scan_source(repo)
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}
    findings.sort(key=lambda f: order.get(f[0], 9))

    print(f"Scanned: {repo}")
    print(f"Files scanned: {sum(1 for _ in repo.rglob('*.py') if '.git' not in _.parts)} python source file(s)")
    print()
    print("--- Findings ---")
    if not findings:
        print("  (no dependency-CVE or hardcoded-secret findings)")
    else:
        for sev, loc, desc in findings:
            print(f"  [{sev}] {loc}: {desc}")
    print()
    counts = {}
    for sev, _, _ in findings:
        counts[sev] = counts.get(sev, 0) + 1
    print("--- Summary ---")
    print("  " + ("  ".join(f"{s}: {counts.get(s, 0)}" for s in ("HIGH", "MEDIUM", "LOW", "INFO"))))
    high = counts.get("HIGH", 0)
    print(f"  Overall: {'ATTENTION REQUIRED (HIGH findings present)' if high else 'no HIGH findings'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
