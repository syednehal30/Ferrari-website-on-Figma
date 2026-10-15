"""Verify the ordinary launcher cannot silently select fictional demo data."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_launcher", ROOT / "scripts/local_demo.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LauncherTest(unittest.TestCase):
    def launch_command(self, arguments):
        with patch.object(sys, "argv", ["local_demo.py", *arguments]), patch.object(launcher, "install", return_value=(Path(sys.executable), None)), patch.object(launcher, "run") as run:
            launcher.main()
            return run.call_args.args[0], run.call_args.kwargs["env"]

    def test_normal_launch_is_real_paused_and_uses_separate_data(self):
        command, environment = self.launch_command([])
        _, demo = self.launch_command(["--demo"])
        self.assertIn("--workspace", command)
        self.assertEqual(environment["ZANDOP_LOCAL_WORKSPACE"], "true")
        self.assertEqual(environment["ZANDOP_SEED_DEMO"], "false")
        self.assertEqual(environment["ZANDOP_LIVE_MODE"], "false")
        self.assertGreaterEqual(len(environment["ZANDOP_OPERATOR_TOKEN"]), 32)
        self.assertNotEqual(environment["ZANDOP_DATA_DIR"], demo["ZANDOP_DATA_DIR"])

    def test_demo_requires_explicit_choice_and_cannot_inherit_live_credentials(self):
        with patch.dict(os.environ, {"ZANDOP_LOCAL_WORKSPACE": "true", "GMAIL_ADDRESS": "owner@example.com", "GMAIL_APP_PASSWORD": "test-only", "ZANDOP_LIVE_MODE": "true"}):
            command, environment = self.launch_command(["--demo", "--no-browser"])
        self.assertIn("--demo", command)
        self.assertIn("--no-browser", command)
        self.assertNotIn("ZANDOP_LOCAL_WORKSPACE", environment)
        self.assertNotIn("GMAIL_APP_PASSWORD", environment)
        self.assertEqual(environment["ZANDOP_SEED_DEMO"], "true")
        self.assertEqual(environment["ZANDOP_LIVE_MODE"], "false")

    def test_explicit_workspace_with_custom_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            command, environment = self.launch_command(["--workspace", "--data-dir", directory])
        self.assertIn("--workspace", command)
        self.assertEqual(environment["ZANDOP_DATA_DIR"], str(Path(directory).resolve()))

    def test_internal_server_rejects_demo_environment_when_real_mode_selected(self):
        with patch.dict(os.environ, {"ZANDOP_LOCAL_WORKSPACE": "", "ZANDOP_OPERATOR_TOKEN": ""}), self.assertRaisesRegex(RuntimeError, "internal option"):
            launcher.serve(open_browser=False)


if __name__ == "__main__":
    unittest.main()
