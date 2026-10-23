#!/usr/bin/env bash
# _svc_common.sh — shared plumbing for the service wrappers. Sourced, never run directly.
#
# Provides two things every wrapper needs:
#
# 1. A MACHINE-READABLE MODE. By default a wrapper echoes its request and the service's response,
#    which is what an operator wants at a terminal and useless to a script trying to parse the body.
#    With SVC_RAW=1 a wrapper prints ONLY the response body, so its output is valid JSON and can be
#    piped into jq.
#
# 2. AN ACTION LOG. Every MUTATING wrapper call appends one pipe-delimited line to
#    logs/service_actions.log, so this environment keeps its own record of what was changed in the
#    shared services and when. The file ships with a header line and is therefore never empty.
#
# Read-only calls are deliberately NOT logged: the log answers "what changed", and logging reads
# would make that ambiguous as well as noisy.
#
# LINE FORMAT (stable; tooling parses it)
#   <ISO8601> | <SERVICE> | <VERB> | <k>=<v> | <k>=<v> | rc=<status>
# e.g.
#   2024-11-04T09:12:33Z | OWNCLOUD | SHARE-PUBLIC | path=/Documents/Financials | perms=1 | rc=200
#
# The trailing " | " after every key=value is intentional, so a tool matching a folder path cannot
# accidentally match a longer path that merely starts with it.
set -uo pipefail

SVC_LOG="${SVC_LOG:-/workspace/logs/service_actions.log}"

# In raw mode the wrapper emits only the response body (for snapshot_export.sh / scripted use).
_svc_raw() { [ "${SVC_RAW:-0}" = "1" ]; }

# _svc_echo <text...> — a human-facing line, suppressed in raw mode.
_svc_echo() { _svc_raw || echo "$@"; }

# _svc_log <SERVICE> <VERB> <rc> [k=v ...] — append one action line. Never fails the caller.
_svc_log() {
  local service="$1" verb="$2" rc="$3"; shift 3
  local ts line
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"
  line="${ts} | ${service} | ${verb}"
  local kv
  for kv in "$@"; do line="${line} | ${kv}"; done
  line="${line} | rc=${rc}"
  mkdir -p "$(dirname "${SVC_LOG}")" 2>/dev/null || true
  printf '%s\n' "${line}" >> "${SVC_LOG}" 2>/dev/null || true
}
