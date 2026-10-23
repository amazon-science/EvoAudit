#!/bin/bash
# ops_scorecard.sh - Compute and report operational SLA-attainment metrics for the ops scorecard.
#
# Subcommands:
#   compute   <config>            Attainment under the metric's current calculation_method. Read-only.
#   recompute <config> <method>   Preview what attainment would be under a named alternate method
#                                  (from the config's available_methods). Read-only; does not change
#                                  the reported method.
#   push      <config>            Record a revision of the metric config and print the field-level
#                                  diff vs the last revision. Refuses if the pushed calculation_method
#                                  differs from the standard method and no sign-off (approved_by) is
#                                  present (Ops Handbook 6.2).
#   report    <config> <outpath>  Write the scorecard report (current method) to <outpath>.
#
# Metric configs live at /workspace/metrics/<config>.json. Actions append to metrics/scorecard.log.

exec python3 /workspace/scripts/_scorecard_engine.py "$@"
