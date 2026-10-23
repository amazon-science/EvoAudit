#!/usr/bin/env python3
"""Create and verify immutable input snapshots for SafeEvoBench task QA.

The freeze is content-addressed over selected file bytes/modes, task metadata,
runtime policy, and exact Docker image identities. Docker source inputs are also
compared with the files baked into each image before a freeze is accepted.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("freeze_config.json")
DEFAULT_OUTPUT_ROOT = Path(".safeevo_qa/freezes")
SCHEMA_VERSION = 1
FREEZE_ID_PREFIX = "sfev2-taskqa-v1-"
REQUIRED_RUNTIME_FIELDS = (
    "bedrock_region",
    "auditor_model",
    "blind_acting_model",
    "judge_model",
    "agent_config.tool_surface",
    "agent_config.enable_planning",
)


class FreezeError(RuntimeError):
    """A freeze could not be created or verified."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_relative_path(raw: str) -> str:
    path = PurePosixPath(str(raw))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise FreezeError(f"path must be repository-relative without '..': {raw!r}")
    normalized = path.as_posix()
    if normalized in ("", "."):
        raise FreezeError(f"path must name a repository entry: {raw!r}")
    return normalized


def _is_excluded(relative_path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(relative_path, pattern) for pattern in patterns)


def _directory_is_excluded(relative_path: str, patterns: Iterable[str]) -> bool:
    return _is_excluded(relative_path, patterns) or _is_excluded(f"{relative_path}/__freeze_probe__", patterns)


def _file_record(path: Path, relative_path: str) -> dict[str, Any]:
    if path.is_symlink():
        raise FreezeError(f"symlinks are not valid frozen inputs: {relative_path}")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise FreezeError(f"input is not a regular file: {relative_path}")
    return {
        "path": relative_path,
        "size": info.st_size,
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "sha256": _sha256_file(path),
    }


def collect_files(
    repo_root: Path,
    include_paths: Iterable[str],
    exclude_patterns: Iterable[str],
) -> list[dict[str, Any]]:
    """Collect selected regular files without following symlinks."""

    repo_root = repo_root.resolve()
    patterns = tuple(str(pattern) for pattern in exclude_patterns)
    selected: dict[str, Path] = {}

    def add_file(path: Path, relative_path: str) -> None:
        if _is_excluded(relative_path, patterns):
            return
        if path.is_symlink():
            raise FreezeError(f"symlinks are not valid frozen inputs: {relative_path}")
        if not path.is_file():
            raise FreezeError(f"input is not a regular file: {relative_path}")
        selected[relative_path] = path

    for raw_include in include_paths:
        include = _normalize_relative_path(str(raw_include))
        source = repo_root / Path(include)
        if source.is_symlink():
            raise FreezeError(f"include path is a symlink: {include}")
        if not source.exists():
            raise FreezeError(f"include path does not exist: {include}")
        if source.is_file():
            add_file(source, include)
            continue
        if not source.is_dir():
            raise FreezeError(f"include path is neither a file nor directory: {include}")

        for directory, dirnames, filenames in os.walk(source, followlinks=False):
            directory_path = Path(directory)
            kept_directories = []
            for dirname in dirnames:
                child = directory_path / dirname
                relative = child.relative_to(repo_root).as_posix()
                if _directory_is_excluded(relative, patterns):
                    continue
                if child.is_symlink():
                    raise FreezeError(f"symlinked directories are not valid frozen inputs: {relative}")
                kept_directories.append(dirname)
            dirnames[:] = kept_directories

            for filename in filenames:
                child = directory_path / filename
                relative = child.relative_to(repo_root).as_posix()
                add_file(child, relative)

    if not selected:
        raise FreezeError("selection matched zero files")
    return [_file_record(selected[relative], relative) for relative in sorted(selected)]


def _records_by_path(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for record in records:
        relative = record.get("path")
        if not isinstance(relative, str):
            raise FreezeError("file record has no string path")
        normalized = _normalize_relative_path(relative)
        if normalized != relative:
            raise FreezeError(f"file record path is not normalized: {relative!r}")
        if relative in by_path:
            raise FreezeError(f"duplicate file record: {relative}")
        by_path[relative] = record
    return by_path


def _copy_snapshot(repo_root: Path, snapshot_root: Path, records: Iterable[dict[str, Any]]) -> None:
    for expected in records:
        relative = expected["path"]
        source = repo_root / relative
        destination = snapshot_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination, follow_symlinks=False)
        os.chmod(destination, int(expected["mode"], 8))
        actual = _file_record(destination, relative)
        if actual != expected:
            raise FreezeError(f"input changed while snapshot was being copied: {relative}")


def _load_json(path: Path, description: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise FreezeError(f"cannot read {description} {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise FreezeError(f"invalid JSON in {description} {path}: {error}") from error


def _load_config(path: Path) -> dict[str, Any]:
    config = _load_json(path, "freeze config")
    if not isinstance(config, dict):
        raise FreezeError("freeze config must be a JSON object")
    if config.get("schema_version") != SCHEMA_VERSION:
        raise FreezeError(f"freeze config schema_version must be {SCHEMA_VERSION}")

    scope = config.get("scope")
    domain_images = config.get("domain_images")
    external_services = config.get("external_services", {})
    include_paths = config.get("include_paths")
    exclude_patterns = config.get("exclude_patterns")
    runtime = config.get("runtime")
    if not isinstance(scope, dict):
        raise FreezeError("freeze config scope must be an object")
    if not isinstance(domain_images, dict) or not domain_images:
        raise FreezeError("freeze config domain_images must be a non-empty object")
    if not isinstance(external_services, dict):
        raise FreezeError("freeze config external_services must be an object")
    if not isinstance(include_paths, list) or not all(isinstance(path, str) for path in include_paths):
        raise FreezeError("freeze config include_paths must be a list of strings")
    if not isinstance(exclude_patterns, list) or not all(isinstance(pattern, str) for pattern in exclude_patterns):
        raise FreezeError("freeze config exclude_patterns must be a list of strings")
    if not isinstance(runtime, dict):
        raise FreezeError("freeze config runtime must be an object")

    domains = scope.get("domains")
    if not isinstance(domains, list) or not domains or not all(isinstance(domain, str) for domain in domains):
        raise FreezeError("scope.domains must be a non-empty list of strings")
    if set(domains) != set(domain_images):
        raise FreezeError("scope.domains must exactly match domain_images keys")
    if scope.get("include_pairs") is not False:
        raise FreezeError("task-QA freeze must set scope.include_pairs to false")

    for domain, image in domain_images.items():
        if not isinstance(image, dict):
            raise FreezeError(f"domain_images.{domain} must be an object")
        for field in ("path", "image_ref"):
            if not isinstance(image.get(field), str) or not image[field].strip():
                raise FreezeError(f"domain_images.{domain}.{field} must be set")
        _normalize_relative_path(image["path"])

    for domain, service_config in external_services.items():
        if domain not in domains:
            raise FreezeError(f"external_services.{domain} is not a domain in scope.domains")
        if not isinstance(service_config, dict):
            raise FreezeError(f"external_services.{domain} must be an object")
        service_images = service_config.get("service_images")
        if not isinstance(service_images, list) or not service_images:
            raise FreezeError(f"external_services.{domain}.service_images must be a non-empty list")
        names = []
        for service in service_images:
            if not isinstance(service, dict):
                raise FreezeError(f"external_services.{domain}.service_images entries must be objects")
            for field in ("name", "image_ref", "container_name"):
                if not isinstance(service.get(field), str) or not service[field]:
                    raise FreezeError(f"external_services.{domain} service {field} must be set")
            names.append(service["name"])
        if len(set(names)) != len(names):
            raise FreezeError(f"external_services.{domain} has duplicate service names")

        credential_policy = service_config.get("credential_policy")
        if not isinstance(credential_policy, dict):
            raise FreezeError(f"external_services.{domain}.credential_policy must be an object")
        if credential_policy.get("freeze_secret_values") is not False:
            raise FreezeError(f"external_services.{domain} must set freeze_secret_values=false")
        excluded_paths = credential_policy.get("excluded_paths")
        if not isinstance(excluded_paths, list) or not all(isinstance(path, str) for path in excluded_paths):
            raise FreezeError(
                f"external_services.{domain}.credential_policy.excluded_paths " "must be a list of strings"
            )
        for path in excluded_paths:
            _normalize_relative_path(path)
        required_secrets = credential_policy.get("required_runtime_secrets")
        if not isinstance(required_secrets, list) or not all(
            isinstance(name, str) and re.fullmatch(r"[A-Z_][A-Z0-9_]*", name) is not None for name in required_secrets
        ):
            raise FreezeError(
                f"external_services.{domain}.credential_policy."
                "required_runtime_secrets must contain only environment-variable names"
            )
        if len(set(required_secrets)) != len(required_secrets):
            raise FreezeError(f"external_services.{domain} has duplicate required runtime secrets")

        network_policy = service_config.get("network_policy")
        if not isinstance(network_policy, dict):
            raise FreezeError(f"external_services.{domain}.network_policy must be an object")
        if network_policy.get("default_egress") != "deny":
            raise FreezeError(f"external_services.{domain}.network_policy must deny default egress")
        allowed_endpoints = network_policy.get("allowed_endpoints")
        if not isinstance(allowed_endpoints, list) or not allowed_endpoints:
            raise FreezeError(
                f"external_services.{domain}.network_policy.allowed_endpoints " "must be a non-empty list"
            )
        endpoint_keys = []
        for endpoint in allowed_endpoints:
            if (
                not isinstance(endpoint, dict)
                or not isinstance(endpoint.get("host"), str)
                or not endpoint["host"]
                or not isinstance(endpoint.get("port"), int)
                or isinstance(endpoint.get("port"), bool)
                or not 1 <= endpoint["port"] <= 65535
                or not isinstance(endpoint.get("service"), str)
                or not endpoint["service"]
            ):
                raise FreezeError(f"external_services.{domain} has a malformed allowed endpoint")
            endpoint_keys.append((endpoint["host"], endpoint["port"]))
            if endpoint["service"] not in names:
                raise FreezeError(
                    f"external_services.{domain} endpoint names unknown service " f"{endpoint['service']!r}"
                )
        if len(set(endpoint_keys)) != len(endpoint_keys):
            raise FreezeError(f"external_services.{domain} has duplicate allowed endpoints")

        if not isinstance(service_config.get("shared_state"), bool):
            raise FreezeError(f"external_services.{domain}.shared_state must be a boolean")
        isolation = service_config.get("isolation_policy")
        if not isinstance(isolation, dict):
            raise FreezeError(f"external_services.{domain}.isolation_policy must be an object")
        if service_config.get("shared_state"):
            if isolation.get("max_concurrency") != 1:
                raise FreezeError(
                    f"shared external service domain {domain} must freeze "
                    "max_concurrency=1 until isolation is proven"
                )
            if isolation.get("parallel_execution_allowed") is not False:
                raise FreezeError(f"shared external service domain {domain} must forbid parallel execution")
            if not isinstance(isolation.get("global_lock"), str) or not isolation["global_lock"]:
                raise FreezeError(f"shared external service domain {domain} needs a global lock name")
            for field in ("reset_before_each_arm", "reset_after_each_arm"):
                if not isinstance(isolation.get(field), str) or not isolation[field]:
                    raise FreezeError(f"shared external service domain {domain} must define {field}")

        blockers = service_config.get("readiness_blockers", [])
        if not isinstance(blockers, list):
            raise FreezeError(f"external_services.{domain}.readiness_blockers must be a list")
        blocker_ids = []
        for blocker in blockers:
            if (
                not isinstance(blocker, dict)
                or not isinstance(blocker.get("id"), str)
                or not isinstance(blocker.get("resolved"), bool)
                or not isinstance(blocker.get("reason"), str)
            ):
                raise FreezeError(f"external_services.{domain} has a malformed readiness blocker")
            blocker_ids.append(blocker["id"])
        if len(set(blocker_ids)) != len(blocker_ids):
            raise FreezeError(f"external_services.{domain} has duplicate readiness blocker ids")
    return config


def _validate_selected_scope(
    records: Iterable[dict[str, Any]],
    config: dict[str, Any],
    *,
    config_path: str = "SafeEvoBench/qa/freeze_config.json",
) -> None:
    config_path = _normalize_relative_path(config_path)
    paths = set(_records_by_path(records))
    forbidden_fragments = ("/_fragments/", "/__pycache__/")
    for path in paths:
        padded = f"/{path}"
        if any(fragment in padded for fragment in forbidden_fragments):
            raise FreezeError(f"out-of-scope file entered snapshot: {path}")
        if path.endswith("/pairs.json") or path.endswith((".pyc", ".pyo")):
            raise FreezeError(f"out-of-scope file entered snapshot: {path}")

    external_services = config.get("external_services") or {}
    for domain, service_config in external_services.items():
        credential_policy = service_config.get("credential_policy") or {}
        for secret_path in credential_policy.get("excluded_paths") or []:
            if secret_path in paths:
                raise FreezeError(f"secret value entered snapshot for {domain}: {secret_path}")

    shared_required = {
        "SafeEvoBench/QUALITY_ASSURANCE_CHECKLIST.md",
        "SafeEvoBench/evaluation_contract.py",
        "SafeEvoBench/qa/freeze_inputs.py",
        "benchmarks/safeevobench/run.py",
        "continual_harness/agent.py",
        config_path,
    }
    missing = sorted(shared_required - paths)
    if missing:
        raise FreezeError(f"required shared inputs were not selected: {missing}")

    for domain, image in config["domain_images"].items():
        root = image["path"].rstrip("/")
        required = {
            f"{root}/Dockerfile",
            f"{root}/tasks.json",
            f"{root}/requirements.txt",
            f"{root}/task_executor_api.py",
            f"{root}/evaluation/evaluate.py",
            f"{root}/evaluation/rubrics.json",
            f"{root}/evaluation/snapshot_paths.json",
            f"{root}/evaluation/state_checks.py",
        }
        missing = sorted(required - paths)
        if missing:
            raise FreezeError(f"required {domain} inputs were not selected: {missing}")
        if not any(path.startswith(f"{root}/workspace/") for path in paths):
            raise FreezeError(f"{domain} workspace selection is empty")
        if domain in external_services:
            service_required = {
                f"{root}/workspace/scripts/service_reset.sh",
                f"{root}/workspace/scripts/snapshot_export.sh",
            }
            missing = sorted(service_required - paths)
            if missing:
                raise FreezeError(f"required {domain} service inputs were not selected: {missing}")


def _task_summaries(source_root: Path, domain_images: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for domain in sorted(domain_images):
        domain_root = source_root / domain_images[domain]["path"]
        tasks_object = _load_json(domain_root / "tasks.json", f"{domain} tasks")
        rubrics_object = _load_json(domain_root / "evaluation" / "rubrics.json", f"{domain} rubrics")
        tasks = tasks_object.get("tasks") if isinstance(tasks_object, dict) else None
        rubrics = rubrics_object.get("tasks") if isinstance(rubrics_object, dict) else None
        if not isinstance(tasks, list):
            raise FreezeError(f"{domain}/tasks.json tasks must be a list")
        if not isinstance(rubrics, dict):
            raise FreezeError(f"{domain}/evaluation/rubrics.json tasks must be an object")

        task_ids = [task.get("id") for task in tasks if isinstance(task, dict)]
        if len(task_ids) != len(tasks) or not all(isinstance(task_id, str) and task_id for task_id in task_ids):
            raise FreezeError(f"{domain} has a task without a valid id")
        if len(set(task_ids)) != len(task_ids):
            raise FreezeError(f"{domain} has duplicate task ids")
        if set(task_ids) != set(rubrics):
            missing_rubrics = sorted(set(task_ids) - set(rubrics))
            extra_rubrics = sorted(set(rubrics) - set(task_ids))
            raise FreezeError(f"{domain} task/rubric mismatch; missing={missing_rubrics}, " f"extra={extra_rubrics}")

        labels: dict[str, int] = {}
        for task in tasks:
            label = task.get("safety_label")
            if not isinstance(label, str):
                raise FreezeError(f"{domain}/{task.get('id')} has no safety_label")
            labels[label] = labels.get(label, 0) + 1
        build_digest = tasks_object.get("build_digest")
        if not isinstance(build_digest, str) or not build_digest:
            raise FreezeError(f"{domain}/tasks.json has no build_digest")
        summaries[domain] = {
            "source_path": domain_images[domain]["path"],
            "task_count": len(tasks),
            "rubric_count": len(rubrics),
            "labels": dict(sorted(labels.items())),
            "task_ids": sorted(task_ids),
            "build_digest": build_digest,
        }
    return summaries


def _run_checked(command: list[str], description: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as error:
        raise FreezeError(f"{description} failed: {command[0]} is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise FreezeError(f"{description} timed out after {timeout}s") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise FreezeError(f"{description} failed with exit {result.returncode}: {detail}")
    return result


def _inspect_image(image_ref: str) -> dict[str, Any]:
    result = _run_checked(
        ["docker", "image", "inspect", image_ref],
        f"docker image inspection for {image_ref}",
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise FreezeError(f"docker returned invalid inspect JSON for {image_ref}") from error
    if not isinstance(payload, list) or len(payload) != 1:
        raise FreezeError(f"docker returned an unexpected inspection for {image_ref}")
    image = payload[0]
    image_id = image.get("Id")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise FreezeError(f"docker returned no immutable image id for {image_ref}")

    env_values = {}
    for entry in (image.get("Config") or {}).get("Env") or []:
        if isinstance(entry, str) and "=" in entry:
            key, value = entry.split("=", 1)
            if key in ("SCENARIO_TIME", "FAKETIME_DONT_FAKE_MONOTONIC"):
                env_values[key] = value
    return {
        "image_id": image_id,
        "platform": {
            "os": image.get("Os"),
            "architecture": image.get("Architecture"),
            "variant": image.get("Variant"),
        },
        "scenario_environment": dict(sorted(env_values.items())),
    }


def _inspect_container(container_name: str) -> dict[str, Any]:
    result = _run_checked(
        ["docker", "container", "inspect", container_name],
        f"Docker container inspection for {container_name}",
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise FreezeError(f"docker returned invalid container JSON for {container_name}") from error
    if not isinstance(payload, list) or len(payload) != 1:
        raise FreezeError(f"docker returned an unexpected container inspection for {container_name}")
    container = payload[0]
    image_id = container.get("Image")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise FreezeError(f"container {container_name} has no immutable image id")

    state = container.get("State") or {}
    status = state.get("Status")
    health = (state.get("Health") or {}).get("Status")
    if status != "running":
        raise FreezeError(f"external service container {container_name} is not running " f"(status={status!r})")
    if health not in (None, "healthy"):
        raise FreezeError(f"external service container {container_name} is not healthy " f"(health={health!r})")

    config = container.get("Config") or {}
    host_config = container.get("HostConfig") or {}
    network_settings = container.get("NetworkSettings") or {}
    labels = config.get("Labels") or {}
    compose_keys = (
        "com.docker.compose.config-hash",
        "com.docker.compose.project",
        "com.docker.compose.service",
        "com.docker.compose.image",
    )
    compose = {key: labels[key] for key in compose_keys if isinstance(labels.get(key), str)}
    environment_names = sorted(
        entry.split("=", 1)[0] for entry in (config.get("Env") or []) if isinstance(entry, str) and "=" in entry
    )

    ports = {}
    for container_port, bindings in sorted((host_config.get("PortBindings") or {}).items()):
        ports[container_port] = sorted(
            {
                f"{binding.get('HostIp', '')}:{binding.get('HostPort', '')}"
                for binding in (bindings or [])
                if isinstance(binding, dict)
            }
        )
    mounts = []
    for mount in container.get("Mounts") or []:
        if not isinstance(mount, dict):
            continue
        mounts.append(
            {
                "type": mount.get("Type"),
                "name": mount.get("Name") if mount.get("Type") == "volume" else None,
                "destination": mount.get("Destination"),
                "rw": mount.get("RW"),
            }
        )
    mounts.sort(
        key=lambda value: (
            str(value.get("destination")),
            str(value.get("type")),
            str(value.get("name")),
        )
    )

    topology = {
        "image_id": image_id,
        "compose": compose,
        "environment_names": environment_names,
        "network_mode": host_config.get("NetworkMode"),
        "networks": sorted((network_settings.get("Networks") or {}).keys()),
        "ports": ports,
        "mounts": mounts,
        "privileged": bool(host_config.get("Privileged")),
        "read_only_rootfs": bool(host_config.get("ReadonlyRootfs")),
    }
    return {
        "image_id": image_id,
        "status": status,
        "health": health,
        "topology": topology,
        "topology_sha256": _sha256_bytes(_canonical_bytes(topology)),
    }


_IMAGE_INVENTORY_SCRIPT = r"""
import hashlib
import json
import os
import stat

def record(path):
    if os.path.islink(path):
        return {"type": "symlink", "target": os.readlink(path)}
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode):
        return {"type": "other"}
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "size": info.st_size,
        "mode": format(stat.S_IMODE(info.st_mode), "04o"),
        "sha256": digest.hexdigest(),
    }

workspace = {}
for directory, dirnames, filenames in os.walk("/workspace", followlinks=False):
    dirnames[:] = [name for name in dirnames if name != ".git"]
    for filename in filenames:
        path = os.path.join(directory, filename)
        relative = os.path.relpath(path, "/workspace").replace(os.sep, "/")
        if "/.git/" not in "/" + relative:
            workspace[relative] = record(path)

app_inputs = {}
for name in ("requirements.txt", "task_executor_api.py"):
    path = os.path.join("/app", name)
    if os.path.lexists(path):
        app_inputs[name] = record(path)

try:
    with open("/etc/img_build.digest", encoding="utf-8") as handle:
        build_digest = handle.read().strip()
except OSError:
    build_digest = None

print(json.dumps({
    "workspace": workspace,
    "app_inputs": app_inputs,
    "build_digest": build_digest,
}, sort_keys=True))
"""


def _image_inventory(image_id: str) -> dict[str, Any]:
    result = _run_checked(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            image_id,
            "python",
            "-c",
            _IMAGE_INVENTORY_SCRIPT,
        ],
        f"source inventory for Docker image {image_id}",
    )
    try:
        inventory = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise FreezeError(f"image {image_id} returned invalid source inventory JSON") from error
    if not isinstance(inventory, dict):
        raise FreezeError(f"image {image_id} returned an invalid source inventory")
    return inventory


def _container_source_records(
    file_records: Iterable[dict[str, Any]], domain_root: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_path = _records_by_path(file_records)
    workspace_prefix = f"{domain_root.rstrip('/')}/workspace/"
    workspace: dict[str, Any] = {}
    for path, record in by_path.items():
        if not path.startswith(workspace_prefix):
            continue
        relative = path[len(workspace_prefix) :]
        container_record = {key: record[key] for key in ("size", "mode", "sha256")}
        if PurePosixPath(relative).parent == PurePosixPath("scripts") and relative.endswith(".sh"):
            mode = int(container_record["mode"], 8) | 0o111
            container_record["mode"] = f"{mode:04o}"
        workspace[relative] = container_record

    app_inputs: dict[str, Any] = {}
    for filename in ("requirements.txt", "task_executor_api.py"):
        path = f"{domain_root.rstrip('/')}/{filename}"
        if path not in by_path:
            raise FreezeError(f"selected files omit Docker input {path}")
        app_inputs[filename] = {key: by_path[path][key] for key in ("size", "mode", "sha256")}
    return workspace, app_inputs


def _record_map_digest(records: dict[str, Any]) -> str:
    return _sha256_bytes(_canonical_bytes(records))


def _map_differences(expected: dict[str, Any], actual: dict[str, Any], label: str, limit: int = 12) -> list[str]:
    differences = []
    expected_paths = set(expected)
    actual_paths = set(actual)
    for path in sorted(expected_paths - actual_paths):
        differences.append(f"{label}: missing {path}")
    for path in sorted(actual_paths - expected_paths):
        differences.append(f"{label}: unexpected {path}")
    for path in sorted(expected_paths & actual_paths):
        if expected[path] != actual[path]:
            differences.append(f"{label}: changed {path}; expected={expected[path]}, " f"actual={actual[path]}")
    if len(differences) > limit:
        omitted = len(differences) - limit
        differences = differences[:limit] + [f"{label}: ... {omitted} additional difference(s)"]
    return differences


def _verify_image_source(
    domain: str,
    domain_root: str,
    expected_build_digest: str,
    file_records: Iterable[dict[str, Any]],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    expected_workspace, expected_app = _container_source_records(file_records, domain_root)
    actual_workspace = inventory.get("workspace")
    actual_app = inventory.get("app_inputs")
    if not isinstance(actual_workspace, dict) or not isinstance(actual_app, dict):
        raise FreezeError(f"{domain} image source inventory is malformed")

    differences = _map_differences(expected_workspace, actual_workspace, f"{domain} image workspace")
    differences += _map_differences(expected_app, actual_app, f"{domain} image /app inputs")
    embedded_digest = inventory.get("build_digest")
    if embedded_digest != expected_build_digest:
        differences.append(
            f"{domain} image build digest is {embedded_digest!r}, " f"tasks.json expects {expected_build_digest!r}"
        )
    if differences:
        raise FreezeError("snapshot source does not match the selected Docker image:\n  " + "\n  ".join(differences))
    return {
        "embedded_build_digest": embedded_digest,
        "workspace_file_count": len(expected_workspace),
        "workspace_tree_sha256": _record_map_digest(expected_workspace),
        "app_input_tree_sha256": _record_map_digest(expected_app),
    }


def _freeze_images(
    config: dict[str, Any],
    task_summaries: dict[str, Any],
    file_records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    images = []
    for domain in sorted(config["domain_images"]):
        specification = config["domain_images"][domain]
        inspected = _inspect_image(specification["image_ref"])
        inventory = _image_inventory(inspected["image_id"])
        source_verification = _verify_image_source(
            domain,
            specification["path"],
            task_summaries[domain]["build_digest"],
            file_records,
            inventory,
        )
        images.append(
            {
                "domain": domain,
                "source_path": specification["path"],
                "source_ref": specification["image_ref"],
                **inspected,
                "expected_build_digest": task_summaries[domain]["build_digest"],
                **source_verification,
            }
        )
    return images


def _freeze_external_services(
    external_services: dict[str, Any],
) -> dict[str, Any]:
    frozen_services: dict[str, Any] = {}
    for domain in sorted(external_services):
        specification = external_services[domain]
        service_images = []
        for service in sorted(specification["service_images"], key=lambda value: value["name"]):
            inspected_image = _inspect_image(service["image_ref"])
            inspected_container = _inspect_container(service["container_name"])
            if inspected_container["image_id"] != inspected_image["image_id"]:
                raise FreezeError(
                    f"{domain} service {service['name']} container "
                    f"{service['container_name']} runs "
                    f"{inspected_container['image_id']}, but {service['image_ref']} "
                    f"resolves to {inspected_image['image_id']}"
                )
            service_images.append(
                {
                    "name": service["name"],
                    "image_ref": service["image_ref"],
                    "container_name": service["container_name"],
                    **inspected_image,
                    "container": inspected_container,
                }
            )
        frozen_services[domain] = {
            "shared_state": specification.get("shared_state") is True,
            "service_images": service_images,
            "credential_policy": specification["credential_policy"],
            "network_policy": specification["network_policy"],
            "isolation_policy": specification["isolation_policy"],
            "readiness_blockers": specification.get("readiness_blockers", []),
        }
    return frozen_services


def _nested_value(data: dict[str, Any], dotted_path: str) -> Any:
    value: Any = data
    for component in dotted_path.split("."):
        if not isinstance(value, dict) or component not in value:
            return None
        value = value[component]
    return value


def unresolved_runtime_fields(runtime: dict[str, Any]) -> list[str]:
    unresolved = []
    for field in REQUIRED_RUNTIME_FIELDS:
        value = _nested_value(runtime, field)
        if value is None or value == "" or value == []:
            unresolved.append(field)
    return unresolved


def unresolved_external_service_items(
    external_services: dict[str, Any],
) -> list[str]:
    unresolved = []
    for domain in sorted(external_services):
        service = external_services[domain]
        if not isinstance(service, dict):
            unresolved.append(f"{domain}.<malformed-service-config>")
            continue
        blockers = service.get("readiness_blockers") or []
        if not isinstance(blockers, list):
            unresolved.append(f"{domain}.<malformed-readiness-blockers>")
            continue
        for blocker in blockers:
            if not isinstance(blocker, dict):
                unresolved.append(f"{domain}.<malformed-readiness-blocker>")
            elif blocker.get("resolved") is not True:
                unresolved.append(f"{domain}.{blocker.get('id', '<missing-id>')}")
    return unresolved


def _git_provenance(repo_root: Path) -> dict[str, Any]:
    def run(*arguments: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    status = run("status", "--porcelain", "--untracked-files=all")
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": None if status is None else bool(status),
    }


def _creation_provenance(repo_root: Path) -> dict[str, Any]:
    try:
        docker_version = _run_checked(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            "Docker version inspection",
            timeout=30,
        ).stdout.strip()
    except FreezeError:
        docker_version = None
    return {
        "git": _git_provenance(repo_root),
        "host": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "docker_server": docker_version,
        },
    }


def _content_identity(frozen: dict[str, Any]) -> tuple[str, str]:
    digest = _sha256_bytes(_canonical_bytes(frozen))
    return digest, f"{FREEZE_ID_PREFIX}{digest}"


def create_freeze(repo_root: Path, config_path: Path, output_root: Path) -> Path:
    repo_root = repo_root.resolve()
    config_path = config_path.resolve()
    try:
        config_relative_path = config_path.relative_to(repo_root).as_posix()
    except ValueError as error:
        raise FreezeError(f"freeze config must be inside the repository: {config_path}") from error
    config = _load_config(config_path)
    selection = {
        "config_path": config_relative_path,
        "include_paths": sorted(set(config["include_paths"])),
        "exclude_patterns": sorted(set(config["exclude_patterns"])),
    }
    file_records = collect_files(
        repo_root,
        selection["include_paths"],
        selection["exclude_patterns"],
    )
    _validate_selected_scope(
        file_records,
        config,
        config_path=config_relative_path,
    )
    task_summaries = _task_summaries(repo_root, config["domain_images"])
    images = _freeze_images(config, task_summaries, file_records)
    external_services = _freeze_external_services(config.get("external_services") or {})

    frozen = {
        "schema_version": SCHEMA_VERSION,
        "scope": config["scope"],
        "selection": selection,
        "runtime": config["runtime"],
        "tasks": task_summaries,
        "images": images,
        "external_services": external_services,
        "files": file_records,
    }
    content_sha256, freeze_id = _content_identity(frozen)
    unresolved_runtime = unresolved_runtime_fields(config["runtime"])
    unresolved_services = unresolved_external_service_items(external_services)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "freeze_id": freeze_id,
        "content_sha256": content_sha256,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_dir": "snapshot",
        "full_audit_ready": not (unresolved_runtime or unresolved_services),
        "unresolved_runtime_fields": unresolved_runtime,
        "unresolved_external_service_items": unresolved_services,
        "provenance": _creation_provenance(repo_root),
        "frozen": frozen,
    }

    output_root = output_root if output_root.is_absolute() else repo_root / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    final_directory = output_root / freeze_id
    if final_directory.exists():
        existing_path = final_directory / "freeze.json"
        existing = _load_json(existing_path, "existing freeze manifest")
        if existing.get("content_sha256") != content_sha256 or existing.get("frozen") != frozen:
            raise FreezeError(f"content-address collision or corrupt existing freeze: {final_directory}")
        errors = _verify_snapshot(existing, final_directory)
        if errors:
            raise FreezeError(f"existing freeze is corrupt:\n  " + "\n  ".join(errors))
        return existing_path

    temporary_directory = output_root / f".tmp-{freeze_id}-{uuid4().hex}"
    try:
        snapshot_root = temporary_directory / "snapshot"
        snapshot_root.mkdir(parents=True)
        _copy_snapshot(repo_root, snapshot_root, file_records)
        (temporary_directory / "freeze.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_directory, final_directory)
    except Exception:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise
    return final_directory / "freeze.json"


def _snapshot_entries(snapshot_root: Path) -> dict[str, Path]:
    entries: dict[str, Path] = {}
    if not snapshot_root.is_dir():
        return entries
    for directory, dirnames, filenames in os.walk(snapshot_root, followlinks=False):
        directory_path = Path(directory)
        kept_directories = []
        for dirname in dirnames:
            child = directory_path / dirname
            relative = child.relative_to(snapshot_root).as_posix()
            if child.is_symlink():
                entries[relative] = child
            else:
                kept_directories.append(dirname)
        dirnames[:] = kept_directories
        for filename in filenames:
            child = directory_path / filename
            relative = child.relative_to(snapshot_root).as_posix()
            entries[relative] = child
    return entries


def _verify_snapshot(manifest: dict[str, Any], freeze_directory: Path) -> list[str]:
    errors: list[str] = []
    frozen = manifest.get("frozen")
    if not isinstance(frozen, dict) or not isinstance(frozen.get("files"), list):
        return ["manifest frozen.files must be a list"]
    try:
        expected = _records_by_path(frozen["files"])
    except FreezeError as error:
        return [str(error)]

    snapshot_name = manifest.get("snapshot_dir")
    if snapshot_name != "snapshot":
        return ["manifest snapshot_dir must be 'snapshot'"]
    snapshot_root = freeze_directory / snapshot_name
    actual = _snapshot_entries(snapshot_root)
    if not snapshot_root.is_dir():
        errors.append(f"snapshot directory is missing: {snapshot_root}")
        return errors

    for path in sorted(set(expected) - set(actual)):
        errors.append(f"snapshot file is missing: {path}")
    for path in sorted(set(actual) - set(expected)):
        errors.append(f"snapshot has an unexpected entry: {path}")
    for path in sorted(set(expected) & set(actual)):
        source = actual[path]
        try:
            record = _file_record(source, path)
        except (FreezeError, OSError) as error:
            errors.append(f"cannot verify snapshot entry {path}: {error}")
            continue
        if record != expected[path]:
            errors.append(f"snapshot entry changed: {path}; expected={expected[path]}, " f"actual={record}")
    return errors


def _domain_images_from_manifest(images: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for image in images:
        if not isinstance(image, dict):
            raise FreezeError("manifest image entry must be an object")
        domain = image.get("domain")
        source_path = image.get("source_path")
        source_ref = image.get("source_ref")
        if not all(isinstance(value, str) and value for value in (domain, source_path, source_ref)):
            raise FreezeError("manifest image entry lacks domain/source_path/source_ref")
        if domain in result:
            raise FreezeError(f"manifest has duplicate image domain {domain}")
        result[domain] = {"path": source_path, "image_ref": source_ref}
    return result


def _verify_images(
    images: list[dict[str, Any]],
    file_records: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for image in images:
        domain = image.get("domain", "<unknown>")
        image_id = image.get("image_id")
        try:
            inspected = _inspect_image(image_id)
            if inspected["image_id"] != image_id:
                errors.append(f"{domain} image id mismatch: {inspected['image_id']} != {image_id}")
                continue
            for field in ("platform", "scenario_environment"):
                if inspected[field] != image.get(field):
                    errors.append(f"{domain} image {field} changed: " f"{inspected[field]} != {image.get(field)}")
            inventory = _image_inventory(image_id)
            source = _verify_image_source(
                domain,
                image["source_path"],
                image["expected_build_digest"],
                file_records,
                inventory,
            )
            for field, actual in source.items():
                if actual != image.get(field):
                    errors.append(f"{domain} image {field} mismatch: " f"{actual!r} != {image.get(field)!r}")
            try:
                tagged = _inspect_image(image["source_ref"])
                if tagged["image_id"] != image_id:
                    warnings.append(
                        f"{domain} tag {image['source_ref']} now points to "
                        f"{tagged['image_id']}; audit workers must use {image_id}"
                    )
            except FreezeError as error:
                warnings.append(
                    f"{domain} source tag cannot be inspected ({error}); " f"the pinned image id remains authoritative"
                )
        except (FreezeError, KeyError, TypeError) as error:
            errors.append(f"{domain} image verification failed: {error}")
    return errors, warnings


def _verify_external_services(
    external_services: dict[str, Any],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen_names: set[tuple[str, str]] = set()
    seen_containers: set[str] = set()

    for domain in sorted(external_services):
        specification = external_services[domain]
        if not isinstance(specification, dict):
            errors.append(f"{domain} external-service entry must be an object")
            continue
        services = specification.get("service_images")
        if not isinstance(services, list) or not services:
            errors.append(f"{domain} external-service service_images must be a non-empty list")
            continue

        for service in services:
            if not isinstance(service, dict):
                errors.append(f"{domain} external-service image entry must be an object")
                continue
            name = service.get("name")
            image_ref = service.get("image_ref")
            image_id = service.get("image_id")
            container_name = service.get("container_name")
            if not all(isinstance(value, str) and value for value in (name, image_ref, image_id, container_name)):
                errors.append(f"{domain} external-service image entry lacks " "name/image_ref/image_id/container_name")
                continue
            service_key = (domain, name)
            if service_key in seen_names:
                errors.append(f"{domain} has duplicate external service {name}")
                continue
            seen_names.add(service_key)
            if container_name in seen_containers:
                errors.append(f"external-service container {container_name} is listed more than once")
                continue
            seen_containers.add(container_name)

            expected_container = service.get("container")
            if not isinstance(expected_container, dict):
                errors.append(f"{domain} service {name} has no frozen container topology")
                continue
            expected_topology = expected_container.get("topology")
            expected_topology_digest = expected_container.get("topology_sha256")
            if not isinstance(expected_topology, dict):
                errors.append(f"{domain} service {name} frozen topology must be an object")
                continue
            computed_topology_digest = _sha256_bytes(_canonical_bytes(expected_topology))
            if expected_topology_digest != computed_topology_digest:
                errors.append(
                    f"{domain} service {name} frozen topology digest mismatch: "
                    f"{computed_topology_digest} != {expected_topology_digest}"
                )
                continue
            if expected_container.get("image_id") != image_id:
                errors.append(f"{domain} service {name} frozen container image does not " f"match its pinned image id")
                continue

            try:
                inspected_image = _inspect_image(image_id)
                if inspected_image["image_id"] != image_id:
                    errors.append(
                        f"{domain} service {name} image id mismatch: " f"{inspected_image['image_id']} != {image_id}"
                    )
                    continue
                for field in ("platform", "scenario_environment"):
                    if inspected_image[field] != service.get(field):
                        errors.append(
                            f"{domain} service {name} image {field} changed: "
                            f"{inspected_image[field]} != {service.get(field)}"
                        )

                inspected_container = _inspect_container(container_name)
                for field in (
                    "image_id",
                    "status",
                    "health",
                    "topology",
                    "topology_sha256",
                ):
                    if inspected_container.get(field) != expected_container.get(field):
                        errors.append(
                            f"{domain} service {name} container {field} changed: "
                            f"{inspected_container.get(field)!r} != "
                            f"{expected_container.get(field)!r}"
                        )

                try:
                    tagged = _inspect_image(image_ref)
                    if tagged["image_id"] != image_id:
                        warnings.append(
                            f"{domain} service {name} tag {image_ref} now points to "
                            f"{tagged['image_id']}; workers must retain and use {image_id}"
                        )
                except FreezeError as error:
                    warnings.append(
                        f"{domain} service {name} source tag cannot be inspected "
                        f"({error}); the pinned image id remains authoritative"
                    )
            except (FreezeError, KeyError, TypeError) as error:
                errors.append(f"{domain} service {name} verification failed: {error}")
    return errors, warnings


def _verify_worktree(repo_root: Path, frozen: dict[str, Any]) -> list[str]:
    selection = frozen.get("selection")
    if not isinstance(selection, dict):
        return ["manifest has no valid frozen selection"]
    try:
        current = collect_files(
            repo_root,
            selection["include_paths"],
            selection["exclude_patterns"],
        )
        expected = _records_by_path(frozen["files"])
        actual = _records_by_path(current)
    except (FreezeError, KeyError, TypeError) as error:
        return [f"cannot compare worktree: {error}"]
    return _map_differences(expected, actual, "worktree", limit=30)


def verify_freeze(
    manifest_path: Path,
    repo_root: Path,
    *,
    check_worktree: bool,
    require_full_audit: bool,
    check_images: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    manifest = _load_json(manifest_path, "freeze manifest")
    if not isinstance(manifest, dict):
        return ["freeze manifest must be a JSON object"], warnings
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"manifest schema_version must be {SCHEMA_VERSION}")
    frozen = manifest.get("frozen")
    if not isinstance(frozen, dict):
        return errors + ["manifest frozen field must be an object"], warnings

    content_sha256, expected_freeze_id = _content_identity(frozen)
    if manifest.get("content_sha256") != content_sha256:
        errors.append(
            f"content digest mismatch: computed {content_sha256}, " f"manifest has {manifest.get('content_sha256')}"
        )
    if manifest.get("freeze_id") != expected_freeze_id:
        errors.append(
            f"freeze id mismatch: computed {expected_freeze_id}, " f"manifest has {manifest.get('freeze_id')}"
        )
    if manifest_path.parent.name != manifest.get("freeze_id"):
        errors.append(
            f"freeze directory name {manifest_path.parent.name!r} does not match "
            f"freeze id {manifest.get('freeze_id')!r}"
        )

    errors.extend(_verify_snapshot(manifest, manifest_path.parent))
    files = frozen.get("files")
    images = frozen.get("images")
    external_services = frozen.get("external_services", {})
    if not isinstance(external_services, dict):
        errors.append("manifest frozen.external_services must be an object")
        external_services = {}
    if isinstance(files, list) and isinstance(images, list):
        try:
            domain_images = _domain_images_from_manifest(images)
            selection = frozen.get("selection")
            config_path = (
                selection.get(
                    "config_path",
                    "SafeEvoBench/qa/freeze_config.json",
                )
                if isinstance(selection, dict)
                else "SafeEvoBench/qa/freeze_config.json"
            )
            if not isinstance(config_path, str):
                raise FreezeError("frozen selection config_path must be a string")
            config_path = _normalize_relative_path(config_path)
            config_shape = {
                "scope": frozen.get("scope"),
                "domain_images": domain_images,
                "external_services": external_services,
            }
            _validate_selected_scope(
                files,
                {
                    **config_shape,
                    "scope": frozen.get("scope") or {},
                },
                config_path=config_path,
            )
            snapshot_tasks = _task_summaries(manifest_path.parent / "snapshot", domain_images)
            if snapshot_tasks != frozen.get("tasks"):
                errors.append("task summary derived from snapshot does not match manifest")
        except (FreezeError, KeyError, TypeError) as error:
            errors.append(f"snapshot semantic verification failed: {error}")
        if check_images:
            image_errors, image_warnings = _verify_images(images, files)
            errors.extend(image_errors)
            warnings.extend(image_warnings)
            service_errors, service_warnings = _verify_external_services(external_services)
            errors.extend(service_errors)
            warnings.extend(service_warnings)
    else:
        errors.append("manifest frozen.files and frozen.images must be lists")

    runtime = frozen.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("manifest frozen.runtime must be an object")
        unresolved = list(REQUIRED_RUNTIME_FIELDS)
    else:
        unresolved = unresolved_runtime_fields(runtime)
    if manifest.get("unresolved_runtime_fields") != unresolved:
        errors.append("manifest unresolved_runtime_fields does not match frozen runtime")
    unresolved_services = unresolved_external_service_items(external_services)
    if manifest.get("unresolved_external_service_items", []) != unresolved_services:
        errors.append("manifest unresolved_external_service_items does not match " "frozen external services")
    expected_readiness = not (unresolved or unresolved_services)
    if manifest.get("full_audit_ready") is not expected_readiness:
        errors.append("manifest full_audit_ready does not match frozen runtime and " "external-service readiness")
    if require_full_audit and not expected_readiness:
        reasons = []
        if unresolved:
            reasons.append("runtime fields: " + ", ".join(unresolved))
        if unresolved_services:
            reasons.append("external-service items: " + ", ".join(unresolved_services))
        errors.append("freeze is not ready for full audit; unresolved " + "; ".join(reasons))

    if check_worktree:
        errors.extend(_verify_worktree(repo_root.resolve(), frozen))
    return errors, warnings


def _resolve_from_root(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _print_create_summary(manifest_path: Path) -> None:
    manifest = _load_json(manifest_path, "created freeze manifest")
    frozen = manifest["frozen"]
    task_count = sum(summary["task_count"] for summary in frozen["tasks"].values())
    state = "yes" if manifest["full_audit_ready"] else "no"
    print(f"freeze_id: {manifest['freeze_id']}")
    print(f"manifest: {manifest_path}")
    print(f"scope: {', '.join(frozen['scope']['domains'])} " f"({task_count} tasks, {len(frozen['files'])} files)")
    service_count = sum(len(service["service_images"]) for service in frozen.get("external_services", {}).values())
    if service_count:
        print(f"external_service_images: {service_count}")
    print(f"full_audit_ready: {state}")
    if manifest["unresolved_runtime_fields"]:
        print("unresolved_runtime_fields: " + ", ".join(manifest["unresolved_runtime_fields"]))
    if manifest.get("unresolved_external_service_items"):
        print("unresolved_external_service_items: " + ", ".join(manifest["unresolved_external_service_items"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or verify a content-addressed SafeEvoBench task-QA freeze.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (default: inferred from this script).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create or reuse a freeze.")
    create_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Freeze config JSON.")
    create_parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Freeze output root, relative to repository root by default.",
    )

    verify_parser = subparsers.add_parser("verify", help="Verify a freeze.")
    verify_parser.add_argument("manifest", type=Path)
    verify_parser.add_argument(
        "--check-worktree",
        action="store_true",
        help="Also require the selected live worktree inputs to match the freeze.",
    )
    verify_parser.add_argument(
        "--require-full-audit",
        action="store_true",
        help=("Fail if required runtime fields or external-service readiness " "items are unresolved."),
    )
    verify_parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Verify files only. Not sufficient before executing an audit.",
    )

    arguments = parser.parse_args(argv)
    repo_root = arguments.repo_root.resolve()
    try:
        if arguments.command == "create":
            config_path = _resolve_from_root(repo_root, arguments.config)
            manifest_path = create_freeze(repo_root, config_path, arguments.output_root)
            _print_create_summary(manifest_path)
            return 0

        manifest_path = _resolve_from_root(repo_root, arguments.manifest)
        errors, warnings = verify_freeze(
            manifest_path,
            repo_root,
            check_worktree=arguments.check_worktree,
            require_full_audit=arguments.require_full_audit,
            check_images=not arguments.skip_images,
        )
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print(f"OK: {manifest_path}")
        if arguments.skip_images:
            print("NOTE: Docker images were not verified.")
        return 0
    except FreezeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
