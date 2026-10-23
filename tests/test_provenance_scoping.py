"""Regression tests for the Q1/Q2 provenance scoping bug (found in the 2026-07-31 re-audit).

`source_evolution` (Q1 — did the model evolve in the SOURCE?) was being read off the
fan-out (TARGET) run dir. In the factorial layout source and target are separate units, so
the target dir's prompt_rewrites.jsonl only ever holds the target's own task_id and the
source intersection was always empty: `source_evolution.prompt == 0` in all 11,445 records
of `.safeevo_cache_v2_sweep`, including the evolve family that demonstrably rewrote it.
The fan-out store is also a re-written copy of the seed, so it loses source entries.

These tests pin the invariant: **Q1 comes from the unit where the SOURCE ran** (base unit
for a single source, prefix unit for a sequence), while **Q2 stays on the target arm**.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "benchmarks" / "safeevobench"))

from run_factorial import _ckpt_hash, _join_and_write  # noqa: E402
from run_pairs import source_evolution, target_reuse  # noqa: E402

MODEL, CONFIG = "test-model", "evolve"


def _unit(root, name, tasks, *, rewrites=(), mem=(), seed=None):
    """Write a minimal run-dir: scores + whichever provenance artifacts are asked for."""
    d = root / "units" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "evaluation.json").write_text(json.dumps({"tasks": {
        t: {"utility": {"score": 0.5}, "harm": {"score": 0.25}} for t in tasks}}))
    if rewrites:
        (d / "prompt_rewrites.jsonl").write_text(
            "".join(json.dumps({"task_id": t}) + "\n" for t in rewrites))
    if mem:
        (d / "memory.json").write_text(json.dumps({"entries": {
            f"m{i}": {"created_in_task": t} for i, t in enumerate(mem)}}))
    if seed is not None:
        (d / "config.json").write_text(json.dumps({"seed_store": str(seed)}))
        (d / "seed_evolved_prompt.txt").write_text("evolved")
    return d


class _Args:
    replicates, group, model, config, arms = 1, "g", MODEL, CONFIG, "workspace-reset"


@pytest.fixture
def factorial_batch(tmp_path):
    """A 2-pair factorial batch: one single-source pair, one multi-source pair."""
    batch = tmp_path / "seb_test"
    (batch / "units").mkdir(parents=True)
    stash = batch / "checkpoints" / "ckpt_x" / "store"
    stash.mkdir(parents=True)
    (stash / "evolved_prompt.txt").write_text("evolved")

    src = _unit(batch, "base_srcA__r0", ["srcA"], rewrites=["srcA"], mem=["srcA", "srcA"])
    tgt1 = _unit(batch, "base_tgt1__r0", ["tgt1"])
    # the TARGET arm re-evolves and logs its OWN rewrite — this must not be counted as Q1
    fo1 = _unit(batch, "fanout_P1_store_only__r0", ["tgt1"], rewrites=["tgt1"], seed=stash)

    srcs2 = ["srcB", "srcC"]
    ch = _ckpt_hash(MODEL, CONFIG, srcs2, 0)
    pre = _unit(batch, f"prefix_{ch}__r0", srcs2, rewrites=["srcB", "srcC"], mem=["srcB"])
    tgt2 = _unit(batch, "base_tgt2__r0", ["tgt2"])
    fo2 = _unit(batch, "fanout_P2_store_only__r0", ["tgt2"], seed=stash)

    pairs = [
        {"id": "P1", "source": "srcA", "target": "tgt1", "quadrant": "B->D",
         "model_key": MODEL, "config_key": CONFIG},
        {"id": "P2", "source": srcs2, "target": "tgt2", "quadrant": "D->D",
         "model_key": MODEL, "config_key": CONFIG},
    ]
    _join_and_write(
        _Args, batch, pairs,
        {("srcA", 0): src, ("tgt1", 0): tgt1, ("tgt2", 0): tgt2},
        {("tgt1", 0): (0.5, 0.25), ("tgt2", 0): (0.5, 0.25), ("srcA", 0): (0.5, 0.25)},
        {ch: pre},
        [{"pair_id": "P1", "arm": "store_only", "target": "tgt1", "rep": 0,
          "dir": fo1, "scores": (0.6, 0.1)},
         {"pair_id": "P2", "arm": "store_only", "target": "tgt2", "rep": 0,
          "dir": fo2, "scores": (0.6, 0.1)}],
        "ts", "m")
    out = json.loads((batch / "pairs.json").read_text())
    return {p["pair_id"]: p for p in out["pairs"]}, ch


def test_single_source_q1_from_base_unit(factorial_batch):
    """Q1 counts the SOURCE base unit's artifacts — the regression that read 0 for `prompt`."""
    p = factorial_batch[0]["P1"]
    assert p["source_evolution"] == {
        "memory": 2, "skills": 0, "subagents": 0, "prompt": 1, "total": 3}
    assert Path(p["units"]["source"]).name == "base_srcA__r0"


def test_target_own_rewrite_is_not_source_evolution(factorial_batch):
    """The target arm's own prompt rewrite (task_id=tgt1) must not inflate Q1."""
    assert factorial_batch[0]["P1"]["source_evolution"]["prompt"] == 1


def test_multi_source_q1_from_prefix_unit(factorial_batch):
    """A source SEQUENCE runs as a prefix unit; Q1 must resolve there, not to a base unit."""
    pairs, ch = factorial_batch
    p = pairs["P2"]
    assert p["source_evolution"]["prompt"] == 2      # both source-task rewrites
    assert p["source_evolution"]["memory"] == 1
    assert Path(p["units"]["source"]).name == f"prefix_{ch}__r0"


def test_seeded_evolved_prompt_counts_as_target_reuse(factorial_batch):
    """Q2: the factorial target starts on the source's evolved prompt. The rewrite is logged
    in another unit, so the seeded prompt (marker / seed_store) is what makes it observable."""
    for pid in ("P1", "P2"):
        tr = factorial_batch[0][pid]["target_reuse"]
        assert tr["prompt_pull"] == 1
        assert tr["content_pull"] == 1               # prompt_pull folds into real reuse


def test_sequential_layout_unchanged(tmp_path):
    """run_pairs' natural arm runs source+target in ONE dir; both Q1 and Q2 read it."""
    d = tmp_path / "nat_P1__tgt"
    d.mkdir()
    (d / "prompt_rewrites.jsonl").write_text(
        json.dumps({"task_id": "srcA"}) + "\n" + json.dumps({"task_id": "tgt"}) + "\n")
    (d / "memory.json").write_text(json.dumps({"entries": {
        "a": {"created_in_task": "srcA"},
        "b": {"created_in_task": "tgt"},
        "builtin": {"created_in_task": ""},          # built-ins excluded
    }}))
    assert source_evolution(d, ["srcA"]) == {
        "memory": 1, "skills": 0, "subagents": 0, "prompt": 1, "total": 2}
    assert target_reuse(d, ["srcA"], "tgt")["prompt_pull"] == 1


def test_no_false_positive_reuse_on_bare_dir(tmp_path):
    """No seed and no rewrites => nothing credited. Guards _carried_evolved_prompt."""
    assert target_reuse(tmp_path, ["srcA"], "tgt") == {
        "content_pull": 0, "content_push": 0, "discovery": 0, "prompt_pull": 0}
    assert source_evolution(None, ["srcA"])["total"] == 0
    assert target_reuse(None, ["srcA"], "tgt")["prompt_pull"] == 0
