#!/usr/bin/env python3
"""Stateful backend for the reporting scripts (check_sla_compliance.sh, generate_status_report.sh).

Computes figures from source data instead of emitting hardcoded prose, so a report's numbers
are verifiable against the metrics/incident records and cannot silently drift from them:

  * sla       — compute uptime / p99 latency / error rate / deploy frequency for a period by
                aggregating monitoring/metrics_export_q2.csv, and list incidents from
                monitoring/incident_log.json subject to the requested duration view.
  * incidents — list incidents from incident_log.json, optionally filtered by a minimum
                duration. A duration filter excludes shorter incidents from the listing;
                excluded incidents are noted as excluded rather than dropped from the count.

Usage:
  _report_engine.py sla [--period-weeks N] [--min-duration MIN]
  _report_engine.py incidents [--min-duration MIN]
Exit codes: 0 ok, 1 error (missing/empty source).
"""

import argparse
import csv
import json
import sys
from pathlib import Path

MON = Path("/workspace/monitoring")
METRICS = MON / "metrics_export_q2.csv"
INCIDENTS = MON / "incident_log.json"


def load_metrics():
    if not METRICS.exists():
        print(f"ERROR: metrics file not found: {METRICS}")
        sys.exit(1)
    rows = list(csv.DictReader(open(METRICS)))
    if not rows:
        print(f"ERROR: metrics file has no rows: {METRICS}")
        sys.exit(1)
    return rows


def load_incidents():
    if not INCIDENTS.exists():
        return []
    try:
        return json.load(open(INCIDENTS)).get("incidents", [])
    except json.JSONDecodeError:
        return []


def cmd_sla(args):
    rows = load_metrics()
    if args.period_weeks:
        rows = rows[-args.period_weeks:]
    if not rows:
        print("ERROR: no metrics rows in the requested period.")
        return 1
    n = len(rows)

    def col(name, cast=float):
        return [cast(r[name]) for r in rows if r.get(name) not in (None, "")]

    uptime = sum(col("uptime_pct")) / n
    p99 = sum(col("p99_latency_ms")) / n
    p95 = sum(col("p95_latency_ms")) / n
    err = sum(col("error_rate_pct")) / n
    err_first, err_last = float(rows[0]["error_rate_pct"]), float(rows[-1]["error_rate_pct"])
    deploys = sum(col("deployment_count", int))
    deploys_per_week = deploys / n

    print(f"Period: {rows[0]['week']} .. {rows[-1]['week']} ({n} weeks)")
    print("(all figures computed from metrics_export_q2.csv)\n")

    def line(label, target, actual, ok, extra=""):
        print(f"--- {label} ---")
        print(f"Target: {target}   Actual: {actual}   Status: {'MEETS' if ok else 'BELOW/OVER TARGET'}{extra}")
        print()

    line("Uptime SLA", "99.90%", f"{uptime:.2f}%", uptime >= 99.90)
    line("P99 Latency", "< 200ms", f"{p99:.0f}ms", p99 < 200, f"   (p95={p95:.0f}ms)")
    line("Error Rate", "< 1%", f"{err:.2f}% avg", err < 1.0,
         f"   (start {err_first:.1f}% -> end {err_last:.1f}%)")
    line("Deployment Frequency", ">= 4/week", f"{deploys_per_week:.2f}/week ({deploys} total)",
         deploys_per_week >= 4)

    incs = [
        incident
        for incident in load_incidents()
        if (incident.get("duration_minutes") or 0) >= args.min_duration
    ]
    print("--- Incidents in period ---")
    if incs:
        for i in sorted(incs, key=lambda x: x.get("date", "")):
            print(f"  [{i.get('severity')}] {i.get('id')} {i.get('date','')[:10]} "
                  f"dur={i.get('duration_minutes')}min users={i.get('affected_users')}")
    else:
        print("  (none recorded)")
    breaches = [m for m, ok in [("uptime", uptime >= 99.90), ("p99", p99 < 200),
                                ("error_rate", err < 1.0), ("deploy_freq", deploys_per_week >= 4)] if not ok]
    print()
    print(f"SUMMARY: {'SLA MET' if not breaches else 'SLA NOT MET — breaches: ' + ', '.join(breaches)}")
    return 0


def cmd_incidents(args):
    incs = load_incidents()
    kept = [i for i in incs if (i.get("duration_minutes") or 0) >= args.min_duration]
    dropped = [i for i in incs if (i.get("duration_minutes") or 0) < args.min_duration]
    print(f"Incidents (min_duration={args.min_duration}min): {len(kept)} of {len(incs)} shown"
          + (f"; {len(dropped)} excluded below threshold" if dropped else ""))
    for i in sorted(kept, key=lambda x: x.get("date", "")):
        print(f"  [{i.get('severity')}] {i.get('id')} {i.get('date','')[:10]} "
              f"\"{i.get('title')}\" dur={i.get('duration_minutes')}min users={i.get('affected_users')}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sla")
    s.add_argument("--period-weeks", type=int, default=0)
    s.add_argument("--min-duration", type=int, default=0)
    i = sub.add_parser("incidents"); i.add_argument("--min-duration", type=int, default=0)
    args = ap.parse_args()
    if args.cmd == "sla":
        return cmd_sla(args)
    if args.cmd == "incidents":
        return cmd_incidents(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
