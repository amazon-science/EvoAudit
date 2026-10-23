#!/usr/bin/env bash
# owncloud_api.sh — CLI wrapper over the LOCAL ownCloud backing store (_owncloud_engine.py).
#
# Same verbs, args, output shape, and action-log lines as the live-service version this replaces —
# only the internals changed (curl over WebDAV/OCS -> a local Python engine mutating
# /workspace/files/tree.json + _shares.json). Task prompts and rubric state_checks are unaffected.
#
# Every file/share action is visible in the terminal: the request line, the engine's response body,
# and (for mutations) one line appended to logs/service_actions.log via _svc_log.
#
# Usage:
#   owncloud_api.sh list <path>                          # list a folder (direct children)
#   owncloud_api.sh tree <path>                          # list a folder recursively
#   owncloud_api.sh get <path>                           # print a file's contents
#   owncloud_api.sh put <path> <local_file>              # upload/overwrite a file
#   owncloud_api.sh mkcol <path>                         # create a folder
#   owncloud_api.sh move <src> <dst>                     # move/rename
#   owncloud_api.sh copy <src> <dst>                     # copy
#   owncloud_api.sh delete <path>                        # delete a file or folder (recursive)
#   owncloud_api.sh shares [path]                        # list shares (optionally by path)
#   owncloud_api.sh share-user <path> <user> [perms]     # share to an internal user (shareType=0)
#   owncloud_api.sh share-group <path> <group> [perms]   # share to a group (shareType=1)
#   owncloud_api.sh share-public <path> [perms]          # create a PUBLIC link (shareType=3)
#   owncloud_api.sh get-share <share_id>
#   owncloud_api.sh delete-share <share_id>
#   owncloud_api.sh update-share <share_id> <k=v>...     # e.g. permissions=1
#
# `perms` is the ownCloud permission bitmask: 1=read, 2=update, 4=create, 8=delete, 16=reshare.
# Common values: 1 read-only, 15 read-write, 31 read-write+reshare. Defaults to 1.
set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
. "${SCRIPTS_DIR}/_svc_common.sh"
ENGINE="${OC_ENGINE:-python3 ${SCRIPTS_DIR}/_owncloud_engine.py}"

# _run <verb> <args...> — invoke the engine, echo request+response, capture the status it reports.
_LAST_STATUS=""
_run() {
  _svc_echo ">>> OWNCLOUD $*"
  local out err tmp_err
  tmp_err="$(mktemp)"
  out="$(${ENGINE} "$@" 2>"${tmp_err}")"; local rc=$?
  _LAST_STATUS="$(sed -n 's/^__STATUS__=//p' "${tmp_err}" | tail -1)"
  [ -z "${_LAST_STATUS}" ] && _LAST_STATUS=$([ "$rc" -eq 0 ] && echo 200 || echo 500)
  rm -f "${tmp_err}"
  _svc_echo "<<< status ${_LAST_STATUS}"
  # In both modes print the body; in raw mode it is the ONLY thing printed, so it stays valid JSON.
  printf '%s\n' "${out}"
  return $rc
}

cmd="${1:-}"; shift || true
case "${cmd}" in
  # ---- reads (never logged) --------------------------------------------------------------
  list)       _run list "$@" ;;
  tree)       _run tree "$@" ;;
  get)        _run get "$@" ;;
  shares)     _run shares "$@" ;;
  get-share)  _run get-share "$@" ;;

  # ---- writes (logged, byte-identical _svc_log lines to the live-service wrapper) ---------
  put)          _run put "$@";          rc=$?; _svc_log OWNCLOUD PUT          "${_LAST_STATUS}" "path=$1"; exit $rc ;;
  mkcol)        _run mkcol "$@";        rc=$?; _svc_log OWNCLOUD MKCOL        "${_LAST_STATUS}" "path=$1"; exit $rc ;;
  move)         _run move "$@";         rc=$?; _svc_log OWNCLOUD MOVE         "${_LAST_STATUS}" "path=$1" "dst=$2"; exit $rc ;;
  copy)         _run copy "$@";         rc=$?; _svc_log OWNCLOUD COPY         "${_LAST_STATUS}" "path=$1" "dst=$2"; exit $rc ;;
  delete)       _run delete "$@";       rc=$?; _svc_log OWNCLOUD DELETE       "${_LAST_STATUS}" "path=$1"; exit $rc ;;
  share-user)   _run share-user "$@";   rc=$?; _svc_log OWNCLOUD SHARE-USER   "${_LAST_STATUS}" "path=$1" "with=$2" "perms=${3:-1}"; exit $rc ;;
  share-group)  _run share-group "$@";  rc=$?; _svc_log OWNCLOUD SHARE-GROUP  "${_LAST_STATUS}" "path=$1" "with=$2" "perms=${3:-1}"; exit $rc ;;
  share-public) _run share-public "$@"; rc=$?; _svc_log OWNCLOUD SHARE-PUBLIC "${_LAST_STATUS}" "path=$1" "perms=${2:-1}"; exit $rc ;;
  delete-share) _run delete-share "$@"; rc=$?; _svc_log OWNCLOUD DELETE-SHARE "${_LAST_STATUS}" "share=$1"; exit $rc ;;
  update-share) sid="$1"; _run update-share "$@"; rc=$?; _svc_log OWNCLOUD UPDATE-SHARE "${_LAST_STATUS}" "share=${sid}" "set=${*:2}"; exit $rc ;;

  ""|-h|--help|help) sed -n '2,32p' "$0" ;;
  *) echo "owncloud_api: unknown command '${cmd}' (try --help)" >&2; exit 2 ;;
esac
