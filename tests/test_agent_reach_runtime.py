from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_reach_runtime as runtime


class AgentReachRuntimeTest(unittest.TestCase):
    def test_manifest_pins_official_commit(self) -> None:
        manifest = runtime.load_manifest()
        self.assertRegex(
            manifest["source"],
            r"^git\+https://github\.com/Panniantong/Agent-Reach\.git@[0-9a-f]{40}$",
        )
        self.assertRegex(
            manifest["archive_source"],
            r"^https://github\.com/Panniantong/Agent-Reach/archive/[0-9a-f]{40}\.zip$",
        )
        self.assertEqual(manifest["package"], "agent-reach")
        self.assertIn("xiaohongshu", manifest["required_discovery_channels"])
        wheel = ROOT / manifest["bundled_wheel"]
        self.assertTrue(wheel.is_file())
        self.assertEqual(
            hashlib.sha256(wheel.read_bytes()).hexdigest(),
            manifest["bundled_wheel_sha256"],
        )

    def test_runtime_path_stays_under_agent_reach_home(self) -> None:
        manifest = runtime.load_manifest()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"HOME": directory}
        ):
            target = runtime.runtime_dir(manifest)
            self.assertEqual(
                target,
                Path(directory) / ".agent-reach" / "stephen-hot-content-runtime",
            )

    def test_status_reports_install_action_when_runtime_is_missing(self) -> None:
        manifest = runtime.load_manifest()
        with patch.object(runtime, "find_agent_reach", return_value=None):
            payload = runtime.status_payload(manifest)
        self.assertFalse(payload["installed"])
        self.assertEqual(payload["next_action"], "install")

    def test_bundled_wheel_is_verified_before_install(self) -> None:
        manifest = runtime.load_manifest()
        self.assertEqual(
            runtime.bundled_wheel(manifest),
            ROOT / manifest["bundled_wheel"],
        )

    def test_status_separates_ok_and_unverified_channels(self) -> None:
        manifest = {
            **runtime.load_manifest(),
            "required_discovery_channels": ["exa_search", "xiaohongshu"],
        }
        channel_status = {
            "exa_search": {"status": "ok"},
            "xiaohongshu": {"status": "warn"},
        }
        with patch.object(runtime, "find_agent_reach", return_value="/bin/agent-reach"), patch.object(
            runtime, "doctor", return_value=channel_status
        ):
            payload = runtime.status_payload(manifest)
        self.assertEqual(payload["doctor_ok_channels"], ["exa_search"])
        self.assertEqual(payload["missing_or_unverified_channels"], ["xiaohongshu"])

    def test_install_requires_explicit_system_flag_for_global_setup(self) -> None:
        manifest = runtime.load_manifest()
        with patch.object(runtime, "find_agent_reach", return_value="/bin/agent-reach"), patch.object(
            runtime, "run_checked"
        ) as run, patch.object(runtime, "status_payload", return_value={"installed": True}):
            runtime.install(manifest, system=False, channels="all")
            run.assert_called_once_with(["/bin/agent-reach", "install", "--env=auto"])

        with patch.object(runtime, "find_agent_reach", return_value="/bin/agent-reach"), patch.object(
            runtime, "run_checked"
        ) as run, patch.object(runtime, "status_payload", return_value={"installed": True}):
            runtime.install(manifest, system=True, channels="all")
            run.assert_called_once_with(
                [
                    "/bin/agent-reach",
                    "install",
                    "--env=auto",
                    "--system",
                    "--channels=all",
                ]
            )


if __name__ == "__main__":
    unittest.main()
