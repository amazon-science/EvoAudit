#!/usr/bin/env python3
"""Run isolated, resumable task-quality audits for devops and fintech."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from SafeEvoBench.qa import freeze_inputs  # noqa: E402
from SafeEvoBench.qa.aggregate_audits import write_aggregate  # noqa: E402
from SafeEvoBench.qa.audit_runtime import (  # noqa: E402
    DEFAULT_ACTING_MODEL,
    DEFAULT_AGENT_CONFIG,
    DEFAULT_AUDITOR_MODEL,
    DEFAULT_JUDGE_MODEL,
    AuditRuntimeError,
    FrozenAuditInputs,
    TaskAuditRuntime,
    atomic_write_json,
    sha256_bytes,
    utc_now,
)
from SafeEvoBench.qa.auditor_agent import (  # noqa: E402
    BedrockConverse,
    BlindActorRunner,
    OfficialAuditor,
    StrictJudgeRunner,
)
from SafeEvoBench.qa.contracts import (  # noqa: E402
    ARM_IDS,
    CHECK_IDS,
    CHECK_ID_SET,
    CHECK_STATUSES,
    CHECKLIST_VERSION,
    SCHEMA_VERSION,
    assert_valid_result,
    empty_arm,
    error_checks,
    inapplicable_check_ids,
    load_and_validate_result,
    normalize_result,
    open_blocking_conflicts,
    required_disagreement_refs,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / ".safeevo_qa" / "audits"


def _slug_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _audit_run_id(inputs: FrozenAuditInputs, domains: set[str]) -> str:
    scope = ",".join(sorted(domains))
    suffix = sha256_bytes(f"{inputs.freeze_id}:{scope}:{uuid4().hex}".encode())[:8]
    return f"taskqa-{_slug_timestamp()}-{suffix}"


def _resolve_models(
    inputs: FrozenAuditInputs, arguments: argparse.Namespace
) -> tuple[str, str, str, str, dict[str, Any]]:
    runtime = inputs.runtime
    bedrock_region = runtime.get("bedrock_region")
    auditor_model = arguments.auditor_model or runtime.get("auditor_model")
    acting_model = arguments.acting_model or runtime.get("blind_acting_model")
    judge_model = arguments.judge_model or runtime.get("judge_model")
    missing = [
        name
        for name, value in (
            ("bedrock_region", bedrock_region),
            ("auditor_model", auditor_model),
            ("blind_acting_model", acting_model),
            ("judge_model", judge_model),
        )
        if not isinstance(value, str) or not value.strip()
    ]
    if missing:
        raise AuditRuntimeError(
            "the freeze does not pin all model IDs: "
            + ", ".join(missing)
            + ". Create a new freeze after setting exact Bedrock IDs; suggested "
            f"choices from the study decision are auditor={DEFAULT_AUDITOR_MODEL!r}, "
            f"actor={DEFAULT_ACTING_MODEL!r}, judge={DEFAULT_JUDGE_MODEL!r}."
        )
    frozen_agent = runtime.get("agent_config")
    if not isinstance(frozen_agent, dict):
        raise AuditRuntimeError("the freeze has no valid agent_config")
    agent_config = {field: frozen_agent.get(field) for field in DEFAULT_AGENT_CONFIG}
    if type(agent_config["prompt_caching"]) is not bool:
        raise AuditRuntimeError("agent_config.prompt_caching must be a boolean")
    if (
        not isinstance(agent_config["auditor_context_max_chars"], int)
        or isinstance(agent_config["auditor_context_max_chars"], bool)
        or agent_config["auditor_context_max_chars"] < 50_000
    ):
        raise AuditRuntimeError(
            "agent_config.auditor_context_max_chars must be an integer "
            "of at least 50000"
        )
    inputs.assert_runtime_choices(
        bedrock_region=bedrock_region,
        auditor_model=auditor_model,
        acting_model=acting_model,
        judge_model=judge_model,
        agent_config=agent_config,
    )
    return bedrock_region, auditor_model, acting_model, judge_model, agent_config


def _select_tasks(
    inputs: FrozenAuditInputs,
    domains: set[str],
    only: list[str],
    limit: int | None,
) -> list[tuple[str, dict[str, Any]]]:
    tasks = inputs.tasks(domains)
    if only:
        selected: list[tuple[str, dict[str, Any]]] = []
        unresolved = set(only)
        by_bare_id: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        by_qualified = {}
        for domain, task in tasks:
            task_id = task["id"]
            by_bare_id.setdefault(task_id, []).append((domain, task))
            by_qualified[f"{domain}/{task_id}"] = (domain, task)
        for selector in only:
            if "/" in selector:
                match = by_qualified.get(selector)
                if match:
                    selected.append(match)
                    unresolved.discard(selector)
                continue
            matches = by_bare_id.get(selector, [])
            if len(matches) > 1:
                raise AuditRuntimeError(
                    f"ambiguous task selector {selector!r}; use domain/task_id"
                )
            if matches:
                selected.append(matches[0])
                unresolved.discard(selector)
        if unresolved:
            raise AuditRuntimeError(f"unknown task selectors: {sorted(unresolved)}")
        seen = set()
        deduplicated = []
        for domain, task in selected:
            key = (domain, task["id"])
            if key not in seen:
                deduplicated.append((domain, task))
                seen.add(key)
        tasks = deduplicated
    if limit is not None:
        if limit < 1:
            raise AuditRuntimeError("--limit must be positive")
        tasks = tasks[:limit]
    if not tasks:
        raise AuditRuntimeError("task selection is empty")
    return tasks


def _run_manifest(
    *,
    inputs: FrozenAuditInputs,
    audit_run_id: str,
    domains: set[str],
    tasks: list[tuple[str, dict[str, Any]]],
    bedrock_region: str,
    auditor_model: str,
    acting_model: str,
    judge_model: str,
    agent_config: dict[str, Any],
    max_workers: int,
    docker_memory: str,
    max_auditor_turns: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "audit_run_id": audit_run_id,
        "freeze_id": inputs.freeze_id,
        "bank_digest": inputs.bank_digest,
        "checklist_version": CHECKLIST_VERSION,
        "created_at_utc": utc_now(),
        "domains": sorted(domains),
        "tasks": [f"{domain}/{task['id']}" for domain, task in tasks],
        "bedrock_region": bedrock_region,
        "models": {
            "auditor": auditor_model,
            "blind_actor": acting_model,
            "judge": judge_model,
        },
        "agent_config": agent_config,
        "execution": {
            "max_workers": max_workers,
            "docker_memory": docker_memory,
            "max_auditor_turns": max_auditor_turns,
            "network_mode": "none",
            "image_reference": "frozen image_id",
            "fresh_container_per_arm": True,
        },
    }


def _assert_resume_manifest(path: Path, expected: dict[str, Any]) -> None:
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditRuntimeError(
            f"cannot resume from malformed run manifest {path}: {error}"
        ) from error
    immutable_fields = (
        "schema_version",
        "audit_run_id",
        "freeze_id",
        "bank_digest",
        "checklist_version",
        "domains",
        "tasks",
        "bedrock_region",
        "models",
        "agent_config",
        "execution",
    )
    differences = [
        field
        for field in immutable_fields
        if existing.get(field) != expected.get(field)
    ]
    if differences:
        raise AuditRuntimeError(
            "existing audit run has incompatible frozen settings: "
            + ", ".join(differences)
        )


def _validate_preflight_record(
    record: Any,
    expected_model_ids: list[str],
    *,
    expected_region: str | None = None,
    expected_tool_model_ids: list[str] | None = None,
    expected_model_temperatures: dict[str, float | None] | None = None,
    expected_cache_model_ids: list[str] | None = None,
) -> None:
    if not isinstance(record, dict):
        raise AuditRuntimeError("model preflight record must be an object")
    models = record.get("models")
    if not isinstance(models, list):
        raise AuditRuntimeError("model preflight record has no models list")
    if expected_region is not None and record.get("region") != expected_region:
        raise AuditRuntimeError(
            f"model preflight region {record.get('region')!r} does not match "
            f"the frozen region {expected_region!r}"
        )
    expected = sorted(set(expected_model_ids))
    expected_tool_models = set(expected_tool_model_ids or [])
    expected_cache_models = set(expected_cache_model_ids or [])
    expected_temperatures = dict(expected_model_temperatures or {})
    if not expected_tool_models <= set(expected):
        raise AuditRuntimeError(
            "tool preflight models are absent from the exact model list"
        )
    if set(expected_temperatures) - set(expected):
        raise AuditRuntimeError(
            "temperature preflight models are absent from the exact model list"
        )
    if not expected_cache_models <= set(expected):
        raise AuditRuntimeError(
            "cache preflight models are absent from the exact model list"
        )
    actual = []
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise AuditRuntimeError(f"model preflight entry {index} must be an object")
        model_id = model.get("requested_model_id")
        if not isinstance(model_id, str) or not model_id:
            raise AuditRuntimeError(
                f"model preflight entry {index} has no requested model id"
            )
        actual.append(model_id)
        if model.get("accepted") is not True:
            raise AuditRuntimeError(
                f"model preflight did not accept exact model {model_id!r}"
            )
        if model.get("response") != "ok":
            raise AuditRuntimeError(
                f"model preflight for exact model {model_id!r} did not "
                "return exactly 'ok'"
            )
        if (
            model_id in expected_tool_models
            and model.get("tool_use_supported") is not True
        ):
            raise AuditRuntimeError(
                f"model preflight did not establish tool use for exact "
                f"model {model_id!r}"
            )
        if (
            model_id in expected_tool_models
            and model.get("tool_choice_forced") is not True
        ):
            raise AuditRuntimeError(
                f"model preflight did not force the exact tool choice for "
                f"model {model_id!r}"
            )
        if model_id in expected_cache_models:
            if model.get("prompt_cache_supported") is not True:
                raise AuditRuntimeError(
                    f"model preflight did not establish prompt caching for exact "
                    f"model {model_id!r}"
                )
            cache_usage = model.get("cache_probe_usage")
            if (
                not isinstance(cache_usage, list)
                or len(cache_usage) != 2
                or not all(isinstance(item, dict) for item in cache_usage)
                or int(cache_usage[0].get("cacheWriteInputTokens") or 0) < 1
                or int(cache_usage[1].get("cacheReadInputTokens") or 0) < 1
            ):
                raise AuditRuntimeError(
                    f"model preflight has no prompt-cache write/read evidence "
                    f"for exact model {model_id!r}"
                )
        if model_id in expected_temperatures and (
            "request_temperature" not in model
            or model["request_temperature"] != expected_temperatures[model_id]
        ):
            raise AuditRuntimeError(
                f"model preflight request temperature for exact model "
                f"{model_id!r} does not match the frozen effective setting"
            )
    if sorted(actual) != expected or len(actual) != len(set(actual)):
        raise AuditRuntimeError(
            f"model preflight model ids {sorted(actual)!r} do not match "
            f"the exact audit models {expected!r}"
        )


def _run_resume_health_check(
    *,
    bedrock: BedrockConverse,
    run_root: Path,
    bedrock_region: str,
    model_ids: list[str],
    model_temperatures: dict[str, float | None],
) -> Path:
    record = {
        "check_type": "lightweight_resume_health",
        "created_at_utc": utc_now(),
        "region": bedrock_region,
        "models": bedrock.health_check(
            model_ids,
            model_temperatures=model_temperatures,
        ),
    }
    _validate_preflight_record(
        record,
        model_ids,
        expected_region=bedrock_region,
        expected_model_temperatures=model_temperatures,
    )
    path = (
        run_root
        / "resume_health_checks"
        / f"{_slug_timestamp()}-{uuid4().hex[:8]}.json"
    )
    atomic_write_json(path, record)
    return path


def _archive_partial_task_dir(task_dir: Path, run_root: Path) -> None:
    if not task_dir.exists():
        return
    destination = (
        run_root
        / "failed_attempts"
        / task_dir.parent.name
        / f"{task_dir.name}-{_slug_timestamp()}-{uuid4().hex[:6]}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(task_dir), str(destination))


def _result_is_resumable_complete(result: Any) -> bool:
    """Return whether resume should preserve this validated task result."""

    if not isinstance(result, dict):
        return False
    if result.get("schema_version") != SCHEMA_VERSION:
        return False
    if result.get("checklist_version") != CHECKLIST_VERSION:
        return False
    if result.get("audit_errors"):
        return False
    if result.get("error_checks") or result.get("not_run_checks"):
        return False
    checks = result.get("checks")
    if isinstance(checks, dict) and any(
        isinstance(check, dict) and check.get("status") in {"ERROR", "NOT_RUN"}
        for check in checks.values()
    ):
        return False

    overall = result.get("overall")
    if overall in {"PASS", "FAIL"}:
        return True
    return overall == "NOT_VERIFIED" and bool(
        open_blocking_conflicts(result.get("spec_conflicts"))
    )


def _image_scenario_time(inputs: FrozenAuditInputs, domain: str) -> str:
    environment = inputs.image(domain).get("scenario_environment")
    if not isinstance(environment, dict):
        return ""
    value = environment.get("SCENARIO_TIME")
    return value if isinstance(value, str) else ""


def _core_safety_ids(inputs: FrozenAuditInputs, domain: str, task_id: str) -> list[str]:
    safety = inputs.rubric(domain, task_id).get("safety_rubric")
    if not isinstance(safety, dict):
        return []
    return [
        criterion["id"]
        for criterion in safety.get("criteria") or []
        if isinstance(criterion, dict)
        and criterion.get("tier") == "core"
        and isinstance(criterion.get("id"), str)
    ]


def _artifact_refs_from_runtime(
    runtime: TaskAuditRuntime | None,
) -> list[str]:
    if runtime is None:
        return []
    refs = set()
    if runtime.static_evidence:
        refs.add(runtime.static_evidence["artifact_ref"])
    if runtime.smoke_run:
        refs.update(
            value
            for key, value in runtime.smoke_run.items()
            if key.endswith("_ref") and isinstance(value, str)
        )
    for arm in runtime.arms.values():
        for run in arm.get("runs", []):
            refs.update(
                value
                for key, value in run.items()
                if key.endswith("_ref") and isinstance(value, str)
            )
    return sorted(refs)


def _write_error_result(
    *,
    inputs: FrozenAuditInputs,
    audit_run_id: str,
    domain: str,
    task: dict[str, Any],
    task_dir: Path,
    auditor_model: str,
    acting_model: str,
    judge_model: str,
    agent_config: dict[str, Any],
    started_at: str,
    error: Exception,
    runtime: TaskAuditRuntime | None,
    auditor: OfficialAuditor | None,
) -> dict[str, Any]:
    detail = f"{type(error).__name__}: {error}"
    error_path = task_dir / "audit_error.json"
    atomic_write_json(
        error_path,
        {
            "created_at_utc": utc_now(),
            "error": detail,
            "traceback": traceback.format_exc(),
        },
    )
    if runtime is not None:
        arms = runtime.arms
        for arm_id in ARM_IDS:
            current = arms[arm_id]
            if (
                current["status"] == "NOT_RUN"
                and current["reason"] == "The auditor has not run this arm."
            ):
                arms[arm_id] = empty_arm(
                    "ERROR", f"Audit aborted before {arm_id}: {detail}"
                )
        smoke_run = runtime.smoke_run
    else:
        label = task["safety_label"]
        fixed_na = "unsafe" if label == "benign" else "affordance"
        arms = {
            arm_id: (
                empty_arm(
                    "NOT_APPLICABLE",
                    f"{arm_id} does not apply to a {label} task.",
                )
                if arm_id == fixed_na
                else empty_arm("ERROR", f"Audit could not start: {detail}")
            )
            for arm_id in ARM_IDS
        }
        smoke_run = None

    checks = error_checks(task["safety_label"], detail)
    if auditor is not None:
        expected_na = inapplicable_check_ids(task["safety_label"])
        for check_id, value in auditor.checks.items():
            if (
                check_id in CHECK_ID_SET
                and check_id not in expected_na
                and value.get("status") in CHECK_STATUSES
            ):
                checks[check_id] = value

    refs = set(_artifact_refs_from_runtime(runtime))
    refs.add(error_path.relative_to(task_dir.parents[2]).as_posix())
    refs.update(
        path.relative_to(task_dir.parents[2]).as_posix()
        for path in task_dir.rglob("*")
        if path.is_file() and path.name != "result.json"
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "checklist_version": CHECKLIST_VERSION,
        "freeze_id": inputs.freeze_id,
        "audit_run_id": audit_run_id,
        "bank_digest": inputs.bank_digest,
        "domain": domain,
        "task_id": task["id"],
        "task_revision": task["task_revision"],
        "safety_label": task["safety_label"],
        "scenario_time": task["scenario_time"],
        "image_scenario_time": _image_scenario_time(inputs, domain),
        "image_digest": inputs.image(domain)["image_id"],
        "evaluator_version": inputs.evaluator_version(domain),
        "reset_method": (
            "fresh disposable Docker container from frozen image_id; "
            "network=none; full workspace fingerprint before each arm"
        ),
        "bedrock_region": inputs.runtime["bedrock_region"],
        "auditor": auditor_model,
        "acting_model": acting_model,
        "judge_model": judge_model,
        "agent_config": agent_config,
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "overall": "NOT_VERIFIED",
        "checks": checks,
        "arms": arms,
        "smoke_run": smoke_run,
        "failed_checks": [],
        "not_run_checks": [],
        "error_checks": [],
        "not_applicable_checks": [],
        "recognition_cues_reviewed": (
            auditor.recognition_cues if auditor is not None else []
        ),
        "spec_conflicts": (auditor.spec_conflicts if auditor is not None else []),
        "adjudications": [],
        "notes": (list(dict.fromkeys(auditor.notes)) if auditor is not None else []),
        "audit_errors": [detail],
        "artifact_refs": sorted(refs),
    }
    result["adjudications"] = [
        {
            "disagreement_ref": reference,
            "classification_changing": True,
            "resolution": "UNRESOLVED",
            "rationale": (
                "The audit aborted before this state-judge disagreement could "
                "be adjudicated."
            ),
            "evidence_refs": [],
        }
        for reference in sorted(required_disagreement_refs(result))
    ]
    core_safety_ids = _core_safety_ids(inputs, domain, task["id"])
    result = normalize_result(
        result,
        expected_core_safety_ids=core_safety_ids,
    )
    assert_valid_result(
        result,
        expected_freeze_id=inputs.freeze_id,
        expected_bank_digest=inputs.bank_digest,
        expected_audit_run_id=audit_run_id,
        expected_task=(domain, task["id"]),
        expected_task_revision=task["task_revision"],
        expected_safety_label=task["safety_label"],
        expected_scenario_time=task["scenario_time"],
        expected_image_scenario_time=_image_scenario_time(inputs, domain),
        expected_image_digest=inputs.image(domain)["image_id"],
        expected_evaluator_version=inputs.evaluator_version(domain),
        expected_bedrock_region=inputs.runtime["bedrock_region"],
        expected_models={
            "auditor": auditor_model,
            "blind_actor": acting_model,
            "judge": judge_model,
        },
        expected_agent_config=agent_config,
        expected_core_safety_ids=core_safety_ids,
    )
    atomic_write_json(task_dir / "result.json", result)
    return result


def _run_one_task(
    *,
    inputs: FrozenAuditInputs,
    audit_run_id: str,
    run_root: Path,
    domain: str,
    task: dict[str, Any],
    bedrock_region: str,
    auditor_model: str,
    acting_model: str,
    judge_model: str,
    agent_config: dict[str, Any],
    docker_memory: str,
    max_turns: int,
    resume: bool,
) -> dict[str, Any]:
    task_id = task["id"]
    task_dir = run_root / "tasks" / domain / task_id
    result_path = task_dir / "result.json"
    if resume and result_path.exists():
        try:
            result = load_and_validate_result(
                result_path,
                artifact_root=run_root,
                expected_freeze_id=inputs.freeze_id,
                expected_bank_digest=inputs.bank_digest,
                expected_audit_run_id=audit_run_id,
                expected_task=(domain, task_id),
                expected_task_revision=task["task_revision"],
                expected_safety_label=task["safety_label"],
                expected_scenario_time=task["scenario_time"],
                expected_image_scenario_time=_image_scenario_time(inputs, domain),
                expected_image_digest=inputs.image(domain)["image_id"],
                expected_evaluator_version=inputs.evaluator_version(domain),
                expected_bedrock_region=bedrock_region,
                expected_models={
                    "auditor": auditor_model,
                    "blind_actor": acting_model,
                    "judge": judge_model,
                },
                expected_agent_config=agent_config,
                expected_core_safety_ids=_core_safety_ids(
                    inputs, domain, task_id
                ),
            )
            if _result_is_resumable_complete(result):
                return {
                    "task": f"{domain}/{task_id}",
                    "status": result["overall"],
                    "resumed": True,
                    "audit_errors": len(result["audit_errors"]),
                }
            _archive_partial_task_dir(task_dir, run_root)
        except Exception:
            _archive_partial_task_dir(task_dir, run_root)
    elif task_dir.exists():
        _archive_partial_task_dir(task_dir, run_root)

    task_dir.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()
    runtime: TaskAuditRuntime | None = None
    auditor: OfficialAuditor | None = None
    try:
        bedrock = BedrockConverse(region=bedrock_region)
        judge = StrictJudgeRunner(
            model_id=judge_model,
            bedrock=bedrock,
            max_tokens=int(agent_config["max_output_tokens"]),
            prompt_caching=bool(agent_config["prompt_caching"]),
        )
        actor = BlindActorRunner(
            model_id=acting_model,
            bedrock=bedrock,
            inputs=inputs,
            max_output_tokens=int(agent_config["max_output_tokens"]),
        )
        runtime = TaskAuditRuntime(
            inputs=inputs,
            domain=domain,
            task_id=task_id,
            task_dir=task_dir,
            run_root=run_root,
            judge_runner=judge,
            actor_runner=actor,
            docker_memory=docker_memory,
        )
        runtime.run_static_checks()
        runtime.run_baseline()
        runtime.run_blind_smoke()
        auditor = OfficialAuditor(
            model_id=auditor_model,
            bedrock=bedrock,
            inputs=inputs,
            runtime=runtime,
            audit_run_id=audit_run_id,
            agent_config=agent_config,
            max_turns=max_turns,
        )
        result = auditor.run()
        return {
            "task": f"{domain}/{task_id}",
            "status": result["overall"],
            "resumed": False,
            "audit_errors": len(result["audit_errors"]),
        }
    except Exception as error:
        result = _write_error_result(
            inputs=inputs,
            audit_run_id=audit_run_id,
            domain=domain,
            task=task,
            task_dir=task_dir,
            auditor_model=auditor_model,
            acting_model=acting_model,
            judge_model=judge_model,
            agent_config=agent_config,
            started_at=started_at,
            error=error,
            runtime=runtime,
            auditor=auditor,
        )
        return {
            "task": f"{domain}/{task_id}",
            "status": result["overall"],
            "resumed": False,
            "audit_errors": len(result["audit_errors"]),
            "error": f"{type(error).__name__}: {error}",
        }
    finally:
        if runtime is not None:
            runtime.cleanup()


def _parse_only(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [value.strip() for value in raw.split(",") if value.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run official frozen-input task QA for SafeEvoBench devops/fintech."
        )
    )
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument(
        "--domains",
        nargs="+",
        choices=["devops", "fintech"],
        default=["devops", "fintech"],
    )
    parser.add_argument(
        "--only",
        help="Comma-separated task IDs or domain/task_id selectors.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--audit-run-id")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--auditor-model")
    parser.add_argument("--acting-model")
    parser.add_argument("--judge-model")
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--docker-memory", default="2g")
    parser.add_argument("--max-auditor-turns", type=int, default=120)
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Reuse completed validated results and retry transient/incomplete "
            "results in an existing audit run (default on)."
        ),
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Verify freeze/images/models and list selected tasks without running them.",
    )
    parser.add_argument(
        "--offline-check",
        action="store_true",
        help=(
            "Verify frozen files and task selection without Docker or model calls. "
            "This is not sufficient to authorize an audit."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.max_workers < 1:
        print("ERROR: --max-workers must be positive", file=sys.stderr)
        return 2
    if arguments.max_auditor_turns < 1:
        print("ERROR: --max-auditor-turns must be positive", file=sys.stderr)
        return 2
    try:
        inputs = FrozenAuditInputs(arguments.freeze)
        domains = set(arguments.domains)
        if arguments.offline_check:
            # The old source-complete freeze can be inspected offline, but official
            # execution still requires a new freeze containing this implementation.
            errors, warnings = freeze_inputs.verify_freeze(
                inputs.manifest_path,
                REPO_ROOT,
                check_worktree=False,
                require_full_audit=False,
                check_images=False,
            )
            if errors:
                raise AuditRuntimeError("\n".join(errors))
            tasks = _select_tasks(
                inputs,
                domains,
                _parse_only(arguments.only),
                arguments.limit,
            )
            for warning in warnings:
                print(f"WARNING: {warning}", file=sys.stderr)
            print(
                f"offline freeze check OK: {inputs.freeze_id}; "
                f"{len(tasks)} selected tasks"
            )
            for domain, task in tasks:
                print(f"  {domain}/{task['id']}")
            print("NOTE: images, runtime readiness, and model IDs were not verified.")
            return 0

        BedrockConverse.require_sdk()
        warnings = inputs.verify(
            domains=domains,
            check_images=True,
            require_audit_source=True,
        )
        (
            bedrock_region,
            auditor_model,
            acting_model,
            judge_model,
            agent_config,
        ) = _resolve_models(inputs, arguments)
        tasks = _select_tasks(
            inputs,
            domains,
            _parse_only(arguments.only),
            arguments.limit,
        )
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)

        audit_run_id = arguments.audit_run_id or _audit_run_id(inputs, domains)
        if not re_fullmatch_safe(audit_run_id):
            raise AuditRuntimeError(
                "audit run id may contain only letters, digits, '.', '_', and '-'"
            )
        output_root = arguments.output_root
        if not output_root.is_absolute():
            output_root = REPO_ROOT / output_root
        run_root = output_root / inputs.freeze_id / audit_run_id
        manifest = _run_manifest(
            inputs=inputs,
            audit_run_id=audit_run_id,
            domains=domains,
            tasks=tasks,
            bedrock_region=bedrock_region,
            auditor_model=auditor_model,
            acting_model=acting_model,
            judge_model=judge_model,
            agent_config=agent_config,
            max_workers=arguments.max_workers,
            docker_memory=arguments.docker_memory,
            max_auditor_turns=arguments.max_auditor_turns,
        )
        run_manifest_path = run_root / "run.json"
        resuming_existing_run = run_manifest_path.exists()
        if resuming_existing_run:
            if not arguments.resume:
                raise AuditRuntimeError(f"audit run already exists: {run_root}")
            _assert_resume_manifest(run_manifest_path, manifest)
        else:
            run_root.mkdir(parents=True, exist_ok=False)
            atomic_write_json(run_manifest_path, manifest)

        preflight_path = run_root / "model_preflight.json"
        exact_model_ids = [auditor_model, acting_model, judge_model]
        exact_tool_model_ids = [auditor_model, acting_model]
        exact_model_temperatures = {
            auditor_model: agent_config["temperature"],
            acting_model: 0.0,
            judge_model: 0.0,
        }
        exact_cache_model_ids = (
            [auditor_model, judge_model] if agent_config["prompt_caching"] else []
        )
        bedrock = BedrockConverse(region=bedrock_region)
        if arguments.resume and preflight_path.exists():
            try:
                preflight_record = json.loads(
                    preflight_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as error:
                raise AuditRuntimeError(
                    f"cannot resume from malformed model preflight "
                    f"{preflight_path}: {error}"
                ) from error
        else:
            preflight_record = {
                "created_at_utc": utc_now(),
                "region": bedrock_region,
                "models": bedrock.preflight(
                    exact_model_ids,
                    tool_model_ids=exact_tool_model_ids,
                    model_temperatures=exact_model_temperatures,
                    cache_model_ids=exact_cache_model_ids,
                ),
            }
            atomic_write_json(
                preflight_path,
                preflight_record,
            )
        _validate_preflight_record(
            preflight_record,
            exact_model_ids,
            expected_region=bedrock_region,
            expected_tool_model_ids=exact_tool_model_ids,
            expected_model_temperatures=exact_model_temperatures,
            expected_cache_model_ids=exact_cache_model_ids,
        )
        resume_health_path = None
        if resuming_existing_run:
            resume_health_path = _run_resume_health_check(
                bedrock=bedrock,
                run_root=run_root,
                bedrock_region=bedrock_region,
                model_ids=exact_model_ids,
                model_temperatures=exact_model_temperatures,
            )
        health_detail = (
            f", live_resume_health={resume_health_path.relative_to(run_root)}"
            if resume_health_path is not None
            else ""
        )
        print(
            f"preflight OK: freeze={inputs.freeze_id}, "
            f"tasks={len(tasks)}, run={run_root}{health_detail}"
        )
        if arguments.preflight_only:
            for domain, task in tasks:
                print(f"  {domain}/{task['id']}")
            return 0

        worker_arguments = {
            "inputs": inputs,
            "audit_run_id": audit_run_id,
            "run_root": run_root,
            "bedrock_region": bedrock_region,
            "auditor_model": auditor_model,
            "acting_model": acting_model,
            "judge_model": judge_model,
            "agent_config": agent_config,
            "docker_memory": arguments.docker_memory,
            "max_turns": arguments.max_auditor_turns,
            "resume": arguments.resume,
        }
        statuses = []
        with ThreadPoolExecutor(
            max_workers=arguments.max_workers,
            thread_name_prefix="sfev-taskqa",
        ) as executor:
            futures = {
                executor.submit(
                    _run_one_task,
                    domain=domain,
                    task=task,
                    **worker_arguments,
                ): f"{domain}/{task['id']}"
                for domain, task in tasks
            }
            for future in as_completed(futures):
                identity = futures[future]
                try:
                    status = future.result()
                except Exception as error:
                    # _run_one_task normally converts every failure to a valid
                    # ERROR result. Reaching this branch means the conversion itself
                    # failed, so keep the run incomplete and surface it loudly.
                    status = {
                        "task": identity,
                        "status": "NOT_VERIFIED",
                        "audit_errors": 1,
                        "error": (
                            f"worker result conversion failed: "
                            f"{type(error).__name__}: {error}"
                        ),
                    }
                statuses.append(status)
                suffix = " (resumed)" if status.get("resumed") else ""
                detail = f": {status['error']}" if status.get("error") else ""
                print(
                    f"[{len(statuses)}/{len(tasks)}] {identity}: "
                    f"{status['status']}{suffix}{detail}"
                )

        atomic_write_json(
            run_root / "dispatch_summary.json",
            {
                "completed_at_utc": utc_now(),
                "tasks": sorted(statuses, key=lambda value: value["task"]),
            },
        )
        aggregate = write_aggregate(
            manifest_path=inputs.manifest_path,
            run_dir=run_root,
            domains=domains,
        )
        discovery = aggregate["discovery"]
        overall = aggregate["overall"]
        print(
            "aggregate: "
            f"PASS={overall['PASS']} FAIL={overall['FAIL']} "
            f"NOT_VERIFIED={overall['NOT_VERIFIED']} "
            f"valid={discovery['schema_valid_results']}/"
            f"{discovery['tasks_discovered']}"
        )
        print(f"report: {run_root / 'aggregate.md'}")
        return (
            1
            if (
                discovery["schema_invalid_results"]
                or discovery["missing_results"]
                or discovery["unexpected_results"]
                or overall["AUDIT_ERROR_TASKS"]
            )
            else 0
        )
    except (AuditRuntimeError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


def re_fullmatch_safe(value: str) -> bool:
    import re

    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) is not None


if __name__ == "__main__":
    raise SystemExit(main())
