#!/usr/bin/env bash
# rocketchat_api.sh — CLI wrapper over the LOCAL chat backing store (_chat_engine.py).
#
# Same verbs, args, output shape, and action-log lines as the live-service version this replaces —
# only the internals changed (curl over the RocketChat REST API -> a local Python engine mutating
# /workspace/chat/*.json). Task prompts and rubric state_checks are unaffected.
#
# Usage:
#   rocketchat_api.sh channels                       # list channels
#   rocketchat_api.sh history <channel> [count]      # recent messages (newest first)
#   rocketchat_api.sh members <channel>              # who is in a channel/group
#   rocketchat_api.sh dm-history <username> [count]  # recent direct messages with a user
#   rocketchat_api.sh post <channel> <text>          # post to a channel
#   rocketchat_api.sh dm <username> <text>           # direct-message a user
#   rocketchat_api.sh delete-message <channel> <msg_id>   # remove a message (IRREVERSIBLE)
#   rocketchat_api.sh invite <channel> <username>    # add a user to a private group
#   rocketchat_api.sh kick <channel> <username>      # remove a user from a private group
set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
. "${SCRIPTS_DIR}/_svc_common.sh"
ENGINE="${RC_ENGINE:-python3 ${SCRIPTS_DIR}/_chat_engine.py}"

_LAST_STATUS=""
_run() {
  _svc_echo ">>> ROCKETCHAT $*"
  local out tmp_err
  tmp_err="$(mktemp)"
  out="$(${ENGINE} "$@" 2>"${tmp_err}")"; local rc=$?
  _LAST_STATUS="$(sed -n 's/^__STATUS__=//p' "${tmp_err}" | tail -1)"
  [ -z "${_LAST_STATUS}" ] && _LAST_STATUS=$([ "$rc" -eq 0 ] && echo 200 || echo 500)
  rm -f "${tmp_err}"
  _svc_echo "<<< status ${_LAST_STATUS}"
  printf '%s\n' "${out}"
  return $rc
}

cmd="${1:-}"; shift || true
case "${cmd}" in
  # ---- reads (never logged) ---------------------------------------------------------------
  channels)   _run channels ;;
  history)    _run history "$@" ;;
  members)    _run members "$@" ;;
  dm-history) _run dm-history "$@" ;;

  # ---- writes (logged, byte-identical _svc_log lines to the live-service wrapper) ---------
  post)           _run post "$@";           rc=$?; _svc_log ROCKETCHAT POST           "${_LAST_STATUS}" "channel=$1"; exit $rc ;;
  dm)             _run dm "$@";             rc=$?; _svc_log ROCKETCHAT DM             "${_LAST_STATUS}" "user=$1"; exit $rc ;;
  delete-message) _run delete-message "$@"; rc=$?; _svc_log ROCKETCHAT DELETE-MESSAGE "${_LAST_STATUS}" "channel=$1" "msg=$2"; exit $rc ;;
  invite)         _run invite "$@";         rc=$?; _svc_log ROCKETCHAT INVITE         "${_LAST_STATUS}" "channel=$1" "user=$2"; exit $rc ;;
  kick)           _run kick "$@";           rc=$?; _svc_log ROCKETCHAT KICK           "${_LAST_STATUS}" "channel=$1" "user=$2"; exit $rc ;;

  ""|-h|--help|help) sed -n '2,25p' "$0" ;;
  *) echo "rocketchat_api: unknown command '${cmd}' (try --help)" >&2; exit 2 ;;
esac
