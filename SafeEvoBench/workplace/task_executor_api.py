"""Internal HTTP command runner for the ops workspace.

Executes shell commands against /workspace on behalf of the operations tooling.
"""

import shlex
import subprocess
import os
from flask import Flask, request, jsonify

app = Flask(__name__)

WORKSPACE_DIR = "/workspace"

# Scenario clock. When SCENARIO_TIME is set (see Dockerfile), each command is run under
# `faketime` so the container presents a pinned in-scenario "now" (wall clock advancing at
# real rate) instead of the host date. Empty/unset => run commands unwrapped (real time),
# so this executor stays reusable for groups that don't pin a clock.
SCENARIO_TIME = os.environ.get("SCENARIO_TIME", "").strip()


def _wrap_command(command: str) -> str:
    """Wrap the agent's shell command so it observes the scenario clock, if one is set.

    We invoke `faketime -f "<spec>" bash -c "<command>"`. The advancing '@'-anchored spec
    keeps time moving forward at real rate, so duration measurements (time.time() deltas)
    remain valid; only the absolute wall-clock date is shifted. Returns the command
    unchanged when no scenario time is configured."""
    if not SCENARIO_TIME:
        return command
    return f"faketime -f {shlex.quote(SCENARIO_TIME)} bash -c {shlex.quote(command)}"


def _build_digest():
    """Opaque build fingerprint baked in at build time (see Dockerfile). Lets the harness verify
    it started the intended image, not a stale/wrong one. It is an arbitrary hex string with no
    self-identifying content. Empty if absent."""
    try:
        with open("/etc/img_build.digest") as f:
            return f.read().strip()
    except OSError:
        return ""


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "workspace": WORKSPACE_DIR,
                    "build": _build_digest()})


@app.route("/execute", methods=["POST"])
def execute():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    # Support both formats: {"command": "..."} and {"id": "...", "command": "..."}
    command = data.get("command", "")
    if not command:
        return jsonify({"error": "Missing 'command' field"}), 400

    timeout = data.get("timeout", 120)

    try:
        result = subprocess.run(
            _wrap_command(command),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=WORKSPACE_DIR,
            env={**os.environ, "HOME": "/root", "PATH": "/usr/local/bin:/usr/bin:/bin:/workspace/scripts"},
        )
        return jsonify({
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "returncode": -1,
        })
    except Exception as e:
        return jsonify({
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
