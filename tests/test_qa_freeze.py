import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "SafeEvoBench" / "qa" / "freeze_inputs.py"
SPEC = importlib.util.spec_from_file_location("safeevo_freeze_inputs", MODULE_PATH)
freeze = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(freeze)


class FreezeInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, relative, content, mode=0o644):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.chmod(path, mode)
        return path

    def test_collect_files_excludes_generated_inputs_and_records_mode(self):
        self.write("bank/tasks.json", b"{}\n")
        self.write("bank/workspace/run.sh", b"#!/bin/sh\n", 0o755)
        self.write("bank/pairs.json", b"{}\n")
        self.write("bank/__pycache__/x.pyc", b"cache")

        records = freeze.collect_files(
            self.root,
            ["bank"],
            ["bank/pairs.json", "**/__pycache__/**", "**/*.py[co]"],
        )

        by_path = {record["path"]: record for record in records}
        self.assertEqual(set(by_path), {"bank/tasks.json", "bank/workspace/run.sh"})
        self.assertEqual(by_path["bank/workspace/run.sh"]["mode"], "0755")
        self.assertEqual(
            by_path["bank/tasks.json"]["sha256"],
            freeze._sha256_bytes(b"{}\n"),
        )

    def test_collect_files_rejects_symlinks(self):
        target = self.write("target.txt", b"value")
        link = self.root / "bank" / "link.txt"
        link.parent.mkdir()
        try:
            link.symlink_to(target)
        except (NotImplementedError, OSError):
            self.skipTest("symlinks are unavailable")

        with self.assertRaises(freeze.FreezeError):
            freeze.collect_files(self.root, ["bank"], [])

    def test_snapshot_verification_detects_bytes_mode_and_extra_entries(self):
        source = self.write("input.txt", b"original", 0o640)
        record = freeze._file_record(source, "input.txt")
        freeze_id = "test-freeze"
        freeze_dir = self.root / freeze_id
        snapshot = freeze_dir / "snapshot"
        snapshot.mkdir(parents=True)
        copied = snapshot / "input.txt"
        copied.write_bytes(b"original")
        os.chmod(copied, 0o640)
        manifest = {
            "snapshot_dir": "snapshot",
            "frozen": {"files": [record]},
        }
        self.assertEqual(freeze._verify_snapshot(manifest, freeze_dir), [])

        copied.write_bytes(b"changed")
        (snapshot / "extra.txt").write_text("extra", encoding="utf-8")
        errors = freeze._verify_snapshot(manifest, freeze_dir)
        self.assertTrue(any("input.txt" in error for error in errors))
        self.assertTrue(any("extra.txt" in error for error in errors))

    def test_content_identity_is_independent_of_dictionary_key_order(self):
        first = {"scope": {"domains": ["devops"]}, "files": [{"path": "x"}]}
        second = {"files": [{"path": "x"}], "scope": {"domains": ["devops"]}}
        self.assertEqual(
            freeze._content_identity(first), freeze._content_identity(second)
        )

    def test_runtime_readiness_distinguishes_false_from_unset(self):
        runtime = {
            "bedrock_region": "us-east-1",
            "auditor_model": "auditor-v1",
            "blind_acting_model": "actor-v1",
            "judge_model": "judge-v1",
            "agent_config": {
                "tool_surface": "base",
                "enable_planning": False,
            },
        }
        self.assertEqual(freeze.unresolved_runtime_fields(runtime), [])
        runtime["judge_model"] = None
        self.assertEqual(freeze.unresolved_runtime_fields(runtime), ["judge_model"])

    def test_checked_in_config_selects_three_self_contained_domains(self):
        config = freeze._load_config(
            REPO_ROOT / "SafeEvoBench" / "qa" / "freeze_config.json"
        )
        self.assertEqual(
            set(config["scope"]["domains"]), {"devops", "fintech", "workplace"}
        )
        # All three domains ship self-contained (baked workspaces, local engines,
        # no live services), so the freeze declares no external services.
        self.assertEqual(config["external_services"], {})

    def test_validate_selected_scope_rejects_entered_secret_values(self):
        secret_path = "SafeEvoBench/qa/.example_creds"
        config = {
            "external_services": {
                "example": {"credential_policy": {"excluded_paths": [secret_path]}}
            }
        }
        with self.assertRaisesRegex(freeze.FreezeError, "secret value entered"):
            freeze._validate_selected_scope([{"path": secret_path}], config)

    def test_container_topology_omits_secret_values_and_host_bind_sources(self):
        secret = "do-not-freeze-this-value"
        inspect_payload = [
            {
                "Image": "sha256:" + "1" * 64,
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
                "Config": {
                    "Env": [f"PASSWORD={secret}", "PUBLIC_SETTING=enabled"],
                    "Labels": {
                        "com.docker.compose.project": "workplace",
                        "private-token": secret,
                    },
                },
                "HostConfig": {
                    "PortBindings": {
                        "3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3000"}]
                    },
                    "NetworkMode": "workplace_default",
                    "Privileged": False,
                    "ReadonlyRootfs": True,
                },
                "NetworkSettings": {"Networks": {"workplace_default": {}}},
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": f"/host/{secret}",
                        "Destination": "/seed",
                        "RW": False,
                    },
                    {
                        "Type": "volume",
                        "Name": "workplace-data",
                        "Destination": "/data",
                        "RW": True,
                    },
                ],
            }
        ]
        result = SimpleNamespace(stdout=json.dumps(inspect_payload))
        with mock.patch.object(freeze, "_run_checked", return_value=result):
            inspected = freeze._inspect_container("workplace-service")

        serialized = json.dumps(inspected, sort_keys=True)
        self.assertNotIn(secret, serialized)
        self.assertEqual(
            inspected["topology"]["environment_names"],
            ["PASSWORD", "PUBLIC_SETTING"],
        )
        self.assertNotIn("source", serialized.lower())

    def test_external_service_blockers_are_readiness_items(self):
        services = {
            "workplace": {
                "readiness_blockers": [
                    {
                        "id": "reset-gap",
                        "resolved": False,
                        "reason": "Reset is incomplete.",
                    },
                    {
                        "id": "fixed-gap",
                        "resolved": True,
                        "reason": "Reset is complete.",
                    },
                ]
            }
        }
        self.assertEqual(
            freeze.unresolved_external_service_items(services),
            ["workplace.reset-gap"],
        )

    def test_external_service_verification_rechecks_pins_and_topology(self):
        image_id = "sha256:" + "2" * 64
        topology = {
            "image_id": image_id,
            "compose": {},
            "environment_names": ["PASSWORD"],
            "network_mode": "workplace_default",
            "networks": ["workplace_default"],
            "ports": {},
            "mounts": [],
            "privileged": False,
            "read_only_rootfs": False,
        }
        container = {
            "image_id": image_id,
            "status": "running",
            "health": "healthy",
            "topology": topology,
            "topology_sha256": freeze._sha256_bytes(freeze._canonical_bytes(topology)),
        }
        image = {
            "image_id": image_id,
            "platform": {"os": "linux", "architecture": "amd64", "variant": None},
            "scenario_environment": {},
        }
        services = {
            "workplace": {
                "service_images": [
                    {
                        "name": "chat",
                        "image_ref": "chat:1",
                        "container_name": "chat",
                        **image,
                        "container": container,
                    }
                ]
            }
        }
        with (
            mock.patch.object(freeze, "_inspect_image", return_value=image),
            mock.patch.object(freeze, "_inspect_container", return_value=container),
        ):
            errors, warnings = freeze._verify_external_services(services)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_legacy_manifest_without_external_services_remains_valid(self):
        runtime = {
            "bedrock_region": "us-east-1",
            "auditor_model": "auditor-v1",
            "blind_acting_model": "actor-v1",
            "judge_model": "judge-v1",
            "agent_config": {
                "tool_surface": "base",
                "enable_planning": False,
            },
        }
        frozen = {
            "schema_version": freeze.SCHEMA_VERSION,
            "scope": {"domains": []},
            "selection": {"include_paths": [], "exclude_patterns": []},
            "runtime": runtime,
            "tasks": {},
            "images": [],
            "files": [],
        }
        content_sha256, freeze_id = freeze._content_identity(frozen)
        freeze_directory = self.root / freeze_id
        (freeze_directory / "snapshot").mkdir(parents=True)
        manifest_path = freeze_directory / "freeze.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": freeze.SCHEMA_VERSION,
                    "freeze_id": freeze_id,
                    "content_sha256": content_sha256,
                    "snapshot_dir": "snapshot",
                    "full_audit_ready": True,
                    "unresolved_runtime_fields": [],
                    "frozen": frozen,
                }
            ),
            encoding="utf-8",
        )

        with mock.patch.object(freeze, "_validate_selected_scope", return_value=None):
            errors, warnings = freeze.verify_freeze(
                manifest_path,
                self.root,
                check_worktree=False,
                require_full_audit=True,
                check_images=False,
            )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_image_source_verification_rejects_stale_workspace(self):
        domain_root = "SafeEvoBench/devops"
        records = []
        for relative, content, mode in (
            (f"{domain_root}/workspace/data.txt", b"current", 0o644),
            (f"{domain_root}/requirements.txt", b"flask\n", 0o644),
            (f"{domain_root}/task_executor_api.py", b"print('ok')\n", 0o644),
        ):
            path = self.write(relative, content, mode)
            records.append(freeze._file_record(path, relative))
        workspace, app = freeze._container_source_records(records, domain_root)
        inventory = {
            "workspace": json.loads(json.dumps(workspace)),
            "app_inputs": app,
            "build_digest": "expected",
        }
        result = freeze._verify_image_source(
            "devops", domain_root, "expected", records, inventory
        )
        self.assertEqual(result["workspace_file_count"], 1)

        inventory["workspace"]["data.txt"]["sha256"] = "0" * 64
        with self.assertRaises(freeze.FreezeError):
            freeze._verify_image_source(
                "devops", domain_root, "expected", records, inventory
            )


if __name__ == "__main__":
    unittest.main()
