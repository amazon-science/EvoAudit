"""Post-hoc run-health classification.

Detects *degenerate* task runs — ones that got stuck in a non-productive loop
(repeating an empty or an identical command) and never completed the task.
Such runs produce **artifactual** scores: a run that emits ``bash("")`` five
times and never writes its deliverable scores like an empty submission, not
like a considered decision. In a paired A/B design a consistently-degenerate
baseline can therefore fake a delta *even at low variance* — which is exactly
the failure the 5-seed / 2*SE validity gate cannot catch on its own.

The live agent (``continual_harness.agent``) already breaks out of these loops
via its malformed-streak backstop, but it does not record that it did; this
module makes the outcome observable (``result["degenerate"]``) and lets us
reclassify the thousands of already-recorded trajectories offline. Both callers
share ONE predicate so the live flag and the offline audit never disagree.

The predicate, validated against the devops_v2 factorial corpus (12,864
trajectories): a run is degenerate iff it **did not complete** AND its bash
history ends in / is dominated by a non-advancing loop — either the trailing
commands are mostly empty (the empty-command loop), or the same exact command
was issued many times consecutively (the repeated-command loop). On that
corpus this flags 133 runs and — the key safety property — flags **zero**
runs that completed, while sparing 137 completed runs that merely had a few
scattered empty commands mid-run before recovering.
"""

from typing import Any, Dict, List, Optional

# Default thresholds (validated on the devops_v2 corpus: 0 completed-run
# false positives at these values). Exposed as params for other domains.
_TAIL_N = 5            # window of trailing bash commands to inspect
_TAIL_EMPTY_MIN = 3    # >= this many empties in the tail => empty-command loop
_DUP_MIN = 5           # >= this many identical consecutive commands => repeated loop


def _bash_commands(trajectory: Optional[List[dict]]) -> List[str]:
    """The ordered list of bash command strings issued across the trajectory.
    An empty/unparseable bash call contributes an empty string (its signature)."""
    cmds: List[str] = []
    for step in trajectory or []:
        for tc in step.get("tool_calls", []) or []:
            if tc.get("tool") == "bash":
                cmds.append((tc.get("args") or {}).get("command") or "")
    return cmds


def _longest_identical_run(cmds: List[str]) -> tuple:
    """(length, command) of the longest run of identical *consecutive* commands.
    Empty strings are excluded here — those are the empty-command loop's job, so
    the repeated-command signal only fires on a real, non-advancing command."""
    longest = 0
    best = ""
    cur = 0
    prev = object()
    for x in cmds:
        if x == prev:
            cur += 1
        else:
            cur = 1
            prev = x
        if x.strip() and cur > longest:
            longest = cur
            best = x
    return longest, best


def classify_run_health(
    trajectory: Optional[List[dict]],
    completed: bool,
    *,
    tail_n: int = _TAIL_N,
    tail_empty_min: int = _TAIL_EMPTY_MIN,
    dup_min: int = _DUP_MIN,
) -> Dict[str, Any]:
    """Classify one task run.

    Returns ``{"degenerate": bool, "signal": str|None, "reason": str}`` where
    ``signal`` is one of ``"empty_command_loop"`` / ``"repeated_command_loop"``
    / ``None``. A completed run is never degenerate: reaching ``task_complete``
    means the agent left the loop under its own power and (for scored tasks)
    typically produced a deliverable, so its score is a real behavioral signal.
    """
    if completed:
        return {"degenerate": False, "signal": None, "reason": ""}

    cmds = _bash_commands(trajectory)
    if not cmds:
        # No bash at all + not completed is a different failure mode (never
        # engaged); not a *loop*, so out of scope for this classifier.
        return {"degenerate": False, "signal": None, "reason": ""}

    tail = cmds[-tail_n:]
    tail_empty = sum(1 for x in tail if not x.strip())
    if tail_empty >= tail_empty_min:
        return {
            "degenerate": True,
            "signal": "empty_command_loop",
            "reason": (
                f"empty-command loop: {tail_empty}/{len(tail)} trailing bash calls "
                f"had no command and the task never completed"
            ),
        }

    dup_len, dup_cmd = _longest_identical_run(cmds)
    if dup_len >= dup_min:
        preview = (dup_cmd.strip().splitlines()[0] if dup_cmd.strip() else "")[:60]
        return {
            "degenerate": True,
            "signal": "repeated_command_loop",
            "reason": (
                f"repeated-command loop: the same command ran {dup_len}x consecutively "
                f"and the task never completed (command: {preview!r})"
            ),
        }

    return {"degenerate": False, "signal": None, "reason": ""}


def classify_result(result: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """Convenience wrapper for a run-result dict (has ``trajectory`` +
    ``completed``), e.g. a loaded ``trajectory_*.json``."""
    return classify_run_health(
        result.get("trajectory"), bool(result.get("completed")), **kwargs
    )
