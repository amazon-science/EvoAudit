#!/usr/bin/env python3
"""Validate and deterministically aggregate SafeEvoBench task-audit results."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from SafeEvoBench.qa.contracts import (  # noqa: E402
    ARM_IDS,
    CHECK_IDS,
    CHECKLIST_VERSION,
    CHECK_STATUSES,
    OVERALL_STATUSES,
    SCHEMA_VERSION,
    ResultContractError,
    load_and_validate_result,
    open_blocking_conflicts,
    required_behavior_arm,
    unresolved_adjudications,
)


def _load_json(path: Path, description: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ResultContractError(f"cannot read {description} {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ResultContractError(f"invalid JSON in {description} {path}: {error}") from error


def expected_tasks_from_manifest(
    manifest_path: Path, domains: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    manifest = _load_json(manifest_path, "freeze manifest")
    frozen = manifest.get("frozen")
    if not isinstance(frozen, dict):
        raise ResultContractError("freeze manifest has no frozen object")
    task_summaries = frozen.get("tasks")
    if not isinstance(task_summaries, dict):
        raise ResultContractError("freeze manifest has no task summaries")
    snapshot = manifest_path.parent / manifest.get("snapshot_dir", "snapshot")

    images = frozen.get("images")
    files = frozen.get("files")
    if not isinstance(images, list) or not isinstance(files, list):
        raise ResultContractError("freeze manifest has no image or file inventory")
    image_by_domain = {
        image.get("domain"): image
        for image in images
        if isinstance(image, dict) and isinstance(image.get("domain"), str)
    }
    file_by_path = {
        record.get("path"): record
        for record in files
        if isinstance(record, dict) and isinstance(record.get("path"), str)
    }

    expected: dict[str, dict[str, Any]] = {}
    for domain in sorted(domains):
        summary = task_summaries.get(domain)
        if not isinstance(summary, dict):
            raise ResultContractError(f"domain {domain!r} is not in the freeze")
        source_path = summary.get("source_path")
        if not isinstance(source_path, str):
            raise ResultContractError(f"domain {domain!r} has no source_path")
        image = image_by_domain.get(domain)
        if not isinstance(image, dict) or not isinstance(image.get("image_id"), str):
            raise ResultContractError(f"domain {domain!r} has no frozen image id")
        evaluator_path = f"{source_path}/evaluation/evaluate.py"
        evaluator = file_by_path.get(evaluator_path)
        if not isinstance(evaluator, dict) or not isinstance(evaluator.get("sha256"), str):
            raise ResultContractError(f"domain {domain!r} has no frozen evaluator digest")
        tasks_path = snapshot / source_path / "tasks.json"
        tasks_document = _load_json(tasks_path, f"{domain} tasks")
        rubrics_path = snapshot / source_path / "evaluation" / "rubrics.json"
        rubrics_document = _load_json(rubrics_path, f"{domain} rubrics")
        rubrics = (
            rubrics_document.get("tasks")
            if isinstance(rubrics_document, dict)
            else None
        )
        if not isinstance(rubrics, dict):
            raise ResultContractError(f"{domain} rubrics has no tasks object")
        environment = image.get("scenario_environment")
        image_scenario_time = (
            environment.get("SCENARIO_TIME")
            if isinstance(environment, dict)
            and isinstance(environment.get("SCENARIO_TIME"), str)
            else ""
        )
        for task in tasks_document.get("tasks", []):
            if not isinstance(task, dict):
                continue
            task_id = task.get("id")
            safety_label = task.get("safety_label")
            task_revision = task.get("task_revision")
            scenario_time = task.get("scenario_time")
            if (
                not isinstance(task_id, str)
                or not isinstance(safety_label, str)
                or not isinstance(task_revision, int)
                or isinstance(task_revision, bool)
                or task_revision < 1
                or not isinstance(scenario_time, str)
            ):
                raise ResultContractError(f"{domain} contains a malformed task record")
            rubric = rubrics.get(task_id)
            if not isinstance(rubric, dict):
                raise ResultContractError(f"{domain}/{task_id} has no frozen rubric")
            safety_rubric = rubric.get("safety_rubric")
            core_safety_ids = [
                criterion["id"]
                for criterion in (
                    safety_rubric.get("criteria")
                    if isinstance(safety_rubric, dict)
                    else []
                )
                if isinstance(criterion, dict)
                and criterion.get("tier") == "core"
                and isinstance(criterion.get("id"), str)
            ]
            key = f"{domain}/{task_id}"
            if key in expected:
                raise ResultContractError(f"duplicate frozen task {key}")
            expected[key] = {
                "safety_label": safety_label,
                "task_revision": task_revision,
                "scenario_time": scenario_time,
                "image_scenario_time": image_scenario_time,
                "core_safety_ids": core_safety_ids,
                "image_digest": image["image_id"],
                "evaluator_version": f"sha256:{evaluator['sha256']}",
            }
    return expected, manifest


def _validate_run_manifest(
    run_manifest: Any,
    *,
    run_dir: Path,
    freeze_id: str,
    bank_digest: str,
    domains: set[str],
    frozen_tasks: dict[str, dict[str, Any]],
    frozen_bedrock_region: str,
) -> tuple[list[str], str, dict[str, str], dict[str, Any]]:
    if not isinstance(run_manifest, dict):
        raise ResultContractError("audit run manifest must be an object")
    expected_fields = {
        "schema_version": SCHEMA_VERSION,
        "audit_run_id": run_dir.name,
        "freeze_id": freeze_id,
        "bank_digest": bank_digest,
        "checklist_version": CHECKLIST_VERSION,
        "domains": sorted(domains),
    }
    differences = [field for field, expected in expected_fields.items() if run_manifest.get(field) != expected]
    if differences:
        raise ResultContractError("audit run manifest does not match aggregation scope: " + ", ".join(differences))

    selected = run_manifest.get("tasks")
    if not isinstance(selected, list) or not all(isinstance(value, str) for value in selected):
        raise ResultContractError("audit run manifest tasks must be a list of strings")
    if len(selected) != len(set(selected)):
        raise ResultContractError("audit run manifest has duplicate task ids")
    if not selected:
        raise ResultContractError("audit run manifest task selection is empty")
    unknown = sorted(set(selected) - set(frozen_tasks))
    if unknown:
        raise ResultContractError(f"audit run selects tasks absent from the freeze/domain scope: {unknown}")
    if any(task.split("/", 1)[0] not in domains for task in selected):
        raise ResultContractError("audit run selects a task outside its declared domains")

    models = run_manifest.get("models")
    if (
        not isinstance(models, dict)
        or set(models) != {"auditor", "blind_actor", "judge"}
        or not all(isinstance(value, str) and value for value in models.values())
    ):
        raise ResultContractError("audit run manifest models must pin auditor/blind_actor/judge")
    bedrock_region = run_manifest.get("bedrock_region")
    if bedrock_region != frozen_bedrock_region:
        raise ResultContractError("audit run manifest bedrock_region does not match the freeze")
    agent_config = run_manifest.get("agent_config")
    if not isinstance(agent_config, dict):
        raise ResultContractError("audit run manifest agent_config must be an object")
    execution = run_manifest.get("execution")
    if not isinstance(execution, dict):
        raise ResultContractError("audit run manifest execution must be an object")
    required_execution = {
        "network_mode": "none",
        "image_reference": "frozen image_id",
        "fresh_container_per_arm": True,
    }
    for field, value in required_execution.items():
        if execution.get(field) != value:
            raise ResultContractError(f"audit run manifest execution.{field} must be {value!r}")
    for field in ("max_workers", "max_auditor_turns"):
        value = execution.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ResultContractError(f"audit run manifest execution.{field} must be positive")
    if not isinstance(execution.get("docker_memory"), str) or not execution["docker_memory"]:
        raise ResultContractError("audit run manifest execution.docker_memory must be non-empty")
    return selected, bedrock_region, models, agent_config


def _empty_check_counter() -> dict[str, int]:
    return {
        "applicable": 0,
        "pass": 0,
        "fail": 0,
        "not_run": 0,
        "error": 0,
        "not_applicable": 0,
    }


def _summary_counter() -> dict[str, int]:
    return {status: 0 for status in sorted(OVERALL_STATUSES)}


def aggregate_results(
    *,
    manifest_path: Path,
    run_dir: Path,
    domains: set[str],
) -> dict[str, Any]:
    expected, manifest = expected_tasks_from_manifest(manifest_path, domains)
    freeze_id = manifest.get("freeze_id")
    bank_digest = manifest.get("content_sha256")
    frozen_bedrock_region = ((manifest.get("frozen") or {}).get("runtime") or {}).get("bedrock_region")
    if not isinstance(frozen_bedrock_region, str) or not frozen_bedrock_region:
        raise ResultContractError("freeze has no valid bedrock_region")
    run_manifest_path = run_dir / "run.json"
    run_models: dict[str, str] | None = None
    run_agent_config: dict[str, Any] | None = None
    expected_audit_run_id = run_dir.name
    if not run_manifest_path.exists():
        raise ResultContractError(f"audit run manifest is missing: {run_manifest_path}")
    run_manifest = _load_json(run_manifest_path, "audit run manifest")
    selected, run_bedrock_region, run_models, run_agent_config = _validate_run_manifest(
        run_manifest,
        run_dir=run_dir,
        freeze_id=freeze_id,
        bank_digest=bank_digest,
        domains=domains,
        frozen_tasks=expected,
        frozen_bedrock_region=frozen_bedrock_region,
    )
    expected_audit_run_id = run_manifest["audit_run_id"]
    expected = {key: expected[key] for key in selected}

    result_root = run_dir / "tasks"
    candidates = sorted(result_root.glob("*/*/result.json")) if result_root.exists() else []
    valid: dict[str, dict[str, Any]] = {}
    invalid_results: list[dict[str, Any]] = []
    unexpected_results: list[str] = []

    for path in candidates:
        relative = path.relative_to(result_root)
        if len(relative.parts) != 3:
            invalid_results.append({"path": str(path), "errors": ["unexpected result path layout"]})
            continue
        domain, task_id, _ = relative.parts
        key = f"{domain}/{task_id}"
        if key not in expected:
            unexpected_results.append(key)
            continue
        if key in valid:
            invalid_results.append({"path": str(path), "errors": [f"duplicate result for {key}"]})
            continue
        try:
            frozen_task = expected[key]
            valid[key] = load_and_validate_result(
                path,
                artifact_root=run_dir,
                expected_freeze_id=freeze_id,
                expected_bank_digest=bank_digest,
                expected_audit_run_id=expected_audit_run_id,
                expected_task=(domain, task_id),
                expected_task_revision=frozen_task["task_revision"],
                expected_safety_label=frozen_task["safety_label"],
                expected_scenario_time=frozen_task["scenario_time"],
                expected_image_scenario_time=frozen_task[
                    "image_scenario_time"
                ],
                expected_image_digest=frozen_task["image_digest"],
                expected_evaluator_version=frozen_task["evaluator_version"],
                expected_bedrock_region=run_bedrock_region,
                expected_models=run_models,
                expected_agent_config=run_agent_config,
                expected_core_safety_ids=frozen_task["core_safety_ids"],
            )
        except ResultContractError as error:
            invalid_results.append({"path": str(path), "errors": str(error).splitlines()})

    overall = _summary_counter()
    by_domain: dict[str, Counter[str]] = defaultdict(Counter)
    by_label: dict[str, Counter[str]] = defaultdict(Counter)
    by_domain_label: dict[str, Counter[str]] = defaultdict(Counter)
    check_counts = {check_id: _empty_check_counter() for check_id in CHECK_IDS}
    failed_tasks: list[dict[str, Any]] = []
    not_verified_tasks: list[dict[str, Any]] = []
    audit_error_tasks: list[dict[str, Any]] = []
    nonqualifying_tasks: list[dict[str, Any]] = []
    conflict_tasks: list[dict[str, Any]] = []
    adjudication_tasks: list[dict[str, Any]] = []
    qualification_counts = {
        arm_id: Counter() for arm_id in ARM_IDS
    }
    conflict_counts: Counter[str] = Counter()
    adjudication_counts: Counter[str] = Counter()

    for key in sorted(valid):
        result = valid[key]
        status = result["overall"]
        domain = result["domain"]
        label = result["safety_label"]
        overall[status] += 1
        by_domain[domain][status] += 1
        by_label[label][status] += 1
        by_domain_label[f"{domain}/{label}"][status] += 1

        required_arms = {
            "baseline",
            "refusal",
            "safe",
            required_behavior_arm(label),
        }
        task_nonqualifying = []
        for arm_id in ARM_IDS:
            qualification = result["arms"][arm_id]["qualification"]
            qualification_counts[arm_id][qualification["status"]] += 1
            if (
                arm_id in required_arms
                and qualification["status"] != "QUALIFIED"
            ):
                task_nonqualifying.append(
                    {
                        "arm": arm_id,
                        "status": qualification["status"],
                        "reasons": qualification["reasons"],
                    }
                )
        if task_nonqualifying:
            nonqualifying_tasks.append(
                {"task": key, "arms": task_nonqualifying}
            )

        for conflict in result["spec_conflicts"]:
            conflict_counts[
                f"{conflict['severity']}/{conflict['status']}"
            ] += 1
        if result["spec_conflicts"]:
            conflict_tasks.append(
                {
                    "task": key,
                    "conflicts": result["spec_conflicts"],
                    "open_blocking_ids": [
                        conflict["id"]
                        for conflict in open_blocking_conflicts(
                            result["spec_conflicts"]
                        )
                    ],
                }
            )

        for adjudication in result["adjudications"]:
            adjudication_counts[adjudication["resolution"]] += 1
        if result["adjudications"]:
            adjudication_tasks.append(
                {
                    "task": key,
                    "adjudications": result["adjudications"],
                }
            )

        for check_id in CHECK_IDS:
            value = result["checks"][check_id]
            check_status = value["status"]
            counter = check_counts[check_id]
            if check_status == "NOT_APPLICABLE":
                counter["not_applicable"] += 1
            else:
                counter["applicable"] += 1
                counter[check_status.lower()] += 1

        if status == "FAIL":
            failed = []
            for check_id in result["failed_checks"]:
                value = result["checks"][check_id]
                failed.append(
                    {
                        "check_id": check_id,
                        "evidence_refs": [evidence["ref"] for evidence in value["evidence"]],
                        "finding": value["finding"],
                        "remediation": value["remediation"],
                    }
                )
            failed_tasks.append({"task": key, "failed_checks": failed})
        elif status == "NOT_VERIFIED":
            not_verified_tasks.append(
                {
                    "task": key,
                    "not_run_checks": result["not_run_checks"],
                    "error_checks": result["error_checks"],
                    "audit_errors": result["audit_errors"],
                    "open_blocking_conflicts": [
                        conflict["id"]
                        for conflict in open_blocking_conflicts(
                            result["spec_conflicts"]
                        )
                    ],
                    "unresolved_adjudications": [
                        value["disagreement_ref"]
                        for value in unresolved_adjudications(
                            result["adjudications"]
                        )
                    ],
                    "nonqualifying_arms": task_nonqualifying,
                }
            )
        if result["audit_errors"] or result["error_checks"]:
            audit_error_tasks.append(
                {
                    "task": key,
                    "error_checks": result["error_checks"],
                    "audit_errors": result["audit_errors"],
                }
            )

    missing_results = sorted(set(expected) - set(valid))
    return {
        "schema_version": SCHEMA_VERSION,
        "checklist_version": CHECKLIST_VERSION,
        "freeze_id": freeze_id,
        "bank_digest": bank_digest,
        "audit_run_id": run_dir.name,
        "domains": sorted(domains),
        "discovery": {
            "tasks_discovered": len(expected),
            "result_files_found": len(candidates),
            "schema_valid_results": len(valid),
            "schema_invalid_results": len(invalid_results),
            "missing_results": len(missing_results),
            "unexpected_results": len(unexpected_results),
        },
        "overall": {
            **dict(overall),
            "AUDIT_ERROR_TASKS": len(audit_error_tasks),
        },
        "by_domain": {
            key: {status: counter.get(status, 0) for status in sorted(OVERALL_STATUSES)}
            for key, counter in sorted(by_domain.items())
        },
        "by_safety_label": {
            key: {status: counter.get(status, 0) for status in sorted(OVERALL_STATUSES)}
            for key, counter in sorted(by_label.items())
        },
        "by_domain_and_safety_label": {
            key: {status: counter.get(status, 0) for status in sorted(OVERALL_STATUSES)}
            for key, counter in sorted(by_domain_label.items())
        },
        "checks": check_counts,
        "failed_tasks": failed_tasks,
        "not_fully_verified_tasks": not_verified_tasks,
        "audit_error_tasks": audit_error_tasks,
        "arm_qualifications": {
            arm_id: dict(sorted(counter.items()))
            for arm_id, counter in qualification_counts.items()
        },
        "nonqualifying_tasks": nonqualifying_tasks,
        "conflicts": {
            "counts": dict(sorted(conflict_counts.items())),
            "tasks": conflict_tasks,
        },
        "adjudications": {
            "counts": dict(sorted(adjudication_counts.items())),
            "tasks": adjudication_tasks,
        },
        "missing_tasks": missing_results,
        "invalid_results": invalid_results,
        "unexpected_results": sorted(unexpected_results),
        "calibration": {
            "status": "NOT_EVALUATED",
            "note": (
                "Model-relative calibration is separate from intrinsic task QA "
                "and is not inferred from these audit arms."
            ),
        },
    }


def render_markdown(aggregate: dict[str, Any]) -> str:
    discovery = aggregate["discovery"]
    overall = aggregate["overall"]
    lines = [
        "# SafeEvoBench Task QA Aggregate",
        "",
        f"- Freeze: `{aggregate['freeze_id']}`",
        f"- Audit run: `{aggregate['audit_run_id']}`",
        f"- Domains: {', '.join(aggregate['domains'])}",
        f"- Tasks discovered: {discovery['tasks_discovered']}",
        f"- Valid results: {discovery['schema_valid_results']}",
        f"- Missing results: {discovery['missing_results']}",
        f"- Invalid results: {discovery['schema_invalid_results']}",
        "",
        "## Outcomes",
        "",
        "| Outcome | Tasks |",
        "|---|---:|",
        f"| PASS | {overall.get('PASS', 0)} |",
        f"| FAIL | {overall.get('FAIL', 0)} |",
        f"| NOT_VERIFIED | {overall.get('NOT_VERIFIED', 0)} |",
        f"| Audit errors | {overall.get('AUDIT_ERROR_TASKS', 0)} |",
        "",
        "## Checklist",
        "",
        "| Check | Applicable | Pass | Fail | Not run | Error | N/A |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for check_id in CHECK_IDS:
        counts = aggregate["checks"][check_id]
        lines.append(
            f"| {check_id} | {counts['applicable']} | {counts['pass']} | "
            f"{counts['fail']} | {counts['not_run']} | {counts['error']} | "
            f"{counts['not_applicable']} |"
        )

    lines.extend(["", "## Failed Tasks", ""])
    if not aggregate["failed_tasks"]:
        lines.append("None.")
    for task in aggregate["failed_tasks"]:
        ids = ", ".join(item["check_id"] for item in task["failed_checks"])
        lines.append(f"- `{task['task']}`: {ids}")

    lines.extend(["", "## Not Fully Verified", ""])
    if not aggregate["not_fully_verified_tasks"]:
        lines.append("None.")
    for task in aggregate["not_fully_verified_tasks"]:
        ids = task["not_run_checks"] + task["error_checks"]
        lines.append(f"- `{task['task']}`: {', '.join(ids) or 'audit error'}")

    if aggregate["missing_tasks"]:
        lines.extend(["", "## Missing Results", ""])
        lines.extend(f"- `{task}`" for task in aggregate["missing_tasks"])
    if aggregate["invalid_results"]:
        lines.extend(["", "## Invalid Results", ""])
        for item in aggregate["invalid_results"]:
            lines.append(f"- `{item['path']}`: {'; '.join(item['errors'])}")

    lines.extend(
        [
            "",
            "## Calibration",
            "",
            "Not evaluated. Model-relative calibration remains a separate pilot step.",
            "",
        ]
    )
    return "\n".join(lines)


def write_aggregate(*, manifest_path: Path, run_dir: Path, domains: set[str]) -> dict[str, Any]:
    aggregate = aggregate_results(
        manifest_path=manifest_path,
        run_dir=run_dir,
        domains=domains,
    )
    (run_dir / "aggregate.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "aggregate.md").write_text(
        render_markdown(aggregate),
        encoding="utf-8",
    )
    return aggregate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and aggregate SafeEvoBench task-QA results.")
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--domains",
        nargs="+",
        default=["devops", "fintech"],
        choices=["devops", "fintech"],
    )
    arguments = parser.parse_args(argv)
    try:
        aggregate = write_aggregate(
            manifest_path=arguments.freeze.resolve(),
            run_dir=arguments.run_dir.resolve(),
            domains=set(arguments.domains),
        )
    except ResultContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    discovery = aggregate["discovery"]
    print(f"validated {discovery['schema_valid_results']}/" f"{discovery['tasks_discovered']} expected task results")
    return (
        1
        if (discovery["schema_invalid_results"] or discovery["missing_results"] or discovery["unexpected_results"])
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
