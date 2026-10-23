#!/usr/bin/env bash
# snapshot_export.sh — dump the current state of a session's service surface to local files.
#
# The services are shared and persistent, so the only durable record of how they looked at the end of
# a session is one taken deliberately. This writes that record to /workspace/_snapshots/<session>/ as
# ordinary JSON files: the folder listing, the share table, the merge requests, the channel history.
#
# Every capture runs the wrapper with SVC_RAW=1 (response body only) and pipes it through `jq .`, so
# a file named .json is always valid JSON. A response that is not JSON produces an {"error": ...}
# stub rather than a file that merely looks parseable.
#
# Usage: snapshot_export.sh <session_id> <namespace> [rocketchat_channel]
#   <namespace> — the surface this session touched, dispatched by prefix:
#       owncloud:/path/to/folder      -> folder listing + the share table
#       ocshares:                     -> the full share table (no path filter)
#       chat:<channel>                -> channel history + members
#       (empty)                       -> nothing beyond the optional channel below
#   [rocketchat_channel] — optional extra channel to capture
#
# Best-effort: a failing capture writes an {"error": ...} stub rather than aborting, so a partly
# available stack never breaks the export.
set -uo pipefail

TASK_ID="${1:?usage: snapshot_export.sh <task_id> <namespace> [channel]}"
NAMESPACE="${2:-}"
CHANNEL="${3:-}"

OUT="/workspace/_snapshots/${TASK_ID}"
mkdir -p "${OUT}"

SCRIPTS="$(cd "$(dirname "$0")" && pwd)"

# _capture <outfile> <cmd...> — run cmd in RAW mode, require the output to be JSON, else stub.
_capture() {
  local out="$1"; shift
  if SVC_RAW=1 "$@" 2>"${out}.err" | jq . > "${out}.tmp" 2>>"${out}.err" \
     && [ -s "${out}.tmp" ]; then
    mv "${out}.tmp" "${out}"; rm -f "${out}.err"
  else
    jq -nc --arg e "$(head -c 400 "${out}.err" 2>/dev/null)" \
      '{error:"capture failed or response was not JSON", detail:$e}' > "${out}"
    rm -f "${out}.tmp" "${out}.err"
  fi
}

# _capture_text <outfile> <cmd...> — for a response that is legitimately NOT JSON (WebDAV XML).
# Wrapped into a JSON envelope so a `contains` check has a stable, parseable file to read.
_capture_text() {
  local out="$1"; shift
  local body
  body="$(SVC_RAW=1 "$@" 2>/dev/null)"
  jq -n --arg b "${body}" '{body:$b}' > "${out}"
}

case "${NAMESPACE}" in
  ocshares:*|ocshares)
    _capture "${OUT}/owncloud_shares.json" bash "${SCRIPTS}/owncloud_api.sh" shares
    ;;
  owncloud:*)
    path="${NAMESPACE#owncloud:}"
    # The folder's own listing, plus the FULL share table. The full table rather than a path-filtered
    # query, because a share that conveys this folder may sit on one of its parents, and a filtered
    # query does not report those.
    _capture_text "${OUT}/owncloud_listing.json" bash "${SCRIPTS}/owncloud_api.sh" tree "${path}"
    _capture      "${OUT}/owncloud_shares.json" bash "${SCRIPTS}/owncloud_api.sh" shares
    ;;
  chat:*)
    ch="${NAMESPACE#chat:}"
    [ -n "${ch}" ] && CHANNEL="${ch}"
    ;;
  "") : ;;
  *)  : ;;
esac

if [ -n "${CHANNEL}" ]; then
  _capture "${OUT}/rocketchat_${CHANNEL}.json" \
           bash "${SCRIPTS}/rocketchat_api.sh" history "${CHANNEL}" 200
  _capture "${OUT}/rocketchat_${CHANNEL}_members.json" \
           bash "${SCRIPTS}/rocketchat_api.sh" members "${CHANNEL}"
fi

# ---------------------------------------------------------------------------
# DOCUMENTS. A file written into the document store has no local copy, so it would be absent from a
# local snapshot. The manifest lists, per session, which service paths to pull down alongside the
# service state, saved under their basename.
# ---------------------------------------------------------------------------
MANIFEST="${SCRIPTS}/export_manifest.json"
if [ -f "${MANIFEST}" ]; then
  while IFS= read -r p; do
    [ -z "${p}" ] && continue
    base="$(basename "${p}")"
    body="$(SVC_RAW=1 bash "${SCRIPTS}/owncloud_api.sh" get "${p}" 2>/dev/null)"
    # Write the file only when the fetch produced content, so a path that does not exist is
    # genuinely absent from the snapshot rather than present and empty.
    if [ -n "${body}" ]; then printf '%s' "${body}" > "${OUT}/${base}"; fi
  done < <(jq -r --arg t "${TASK_ID}" '.[$t][]? // empty' "${MANIFEST}" 2>/dev/null)
fi

# Copy the action log in too, so the snapshot is a self-contained record of the session.
cp -f /workspace/logs/service_actions.log "${OUT}/service_actions.log" 2>/dev/null || true

echo "snapshot_export: wrote state for task '${TASK_ID}' to ${OUT}"
ls -1 "${OUT}"
