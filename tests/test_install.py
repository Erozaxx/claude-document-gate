"""Installer tests: no external downloads and no changes to actual Claude settings."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.settings = self.directory / ".claude" / "settings.json"
        self.python = self.directory / ".venv" / "bin" / "python"

    def test_register_new_preserves_existing_hooks(self):
        self.settings.parent.mkdir(parents=True)
        previous = {"model": "opus", "hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "other-tool --check"}]}
        ]}}
        self.settings.write_text(json.dumps(previous), encoding="utf-8")
        install.register_hook(self.python, settings=self.settings)
        actual = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(actual["model"], "opus")
        entries = actual["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["hooks"][0]["command"], "other-tool --check")
        ours = entries[1]["hooks"][0]
        self.assertIn(str(self.python), ours["command"])
        self.assertIn("hook.py", ours["command"])
        self.assertEqual(ours["timeout"], 180)
        self.assertEqual(json.loads(self.settings.with_name("settings.json.document-gate.bak")
                                    .read_text(encoding="utf-8")), previous)

    def test_rerunning_does_not_duplicate_hook(self):
        install.register_hook(self.python, settings=self.settings)
        install.register_hook(self.python, settings=self.settings)
        entries = json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(entries), 1)

    def test_existing_install_switches_to_virtual_environment(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": "python /old/claude-document-gate/hook.py"}
        ]}]}}), encoding="utf-8")
        install.register_hook(self.python, settings=self.settings)
        entries = json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(entries), 1)
        self.assertIn(str(self.python), entries[0]["hooks"][0]["command"])

    def test_bad_json_never_overwritten(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text("NOT JSON", encoding="utf-8")
        with self.assertRaises(install.InstallationError):
            install.register_hook(self.python, settings=self.settings)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "NOT JSON")

    def test_uninstall_removes_only_our_hook(self):
        self.settings.parent.mkdir(parents=True)
        other = {"type": "command", "command": "other-tool --check"}
        self.settings.write_text(json.dumps({"model": "opus", "hooks": {
            "UserPromptSubmit": [{"hooks": [other]}],
            "Stop": [{"hooks": [other]}]}}), encoding="utf-8")
        install.register_hook(self.python, settings=self.settings)
        install.unregister_hook(settings=self.settings)
        actual = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(actual["model"], "opus")
        self.assertEqual(actual["hooks"]["UserPromptSubmit"], [{"hooks": [other]}])
        self.assertEqual(actual["hooks"]["Stop"], [{"hooks": [other]}])
        self.assertTrue(self.settings.with_name("settings.json.document-gate.bak").exists())

    def test_uninstall_cleans_empty_containers(self):
        install.register_hook(self.python, settings=self.settings)
        install.unregister_hook(settings=self.settings)
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), {})

    def test_uninstall_mixed_group_keeps_other_hook(self):
        self.settings.parent.mkdir(parents=True)
        other = {"type": "command", "command": "other-tool"}
        ours = {"type": "command", "command": "python /x/claude-document-gate/hook.py"}
        self.settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": [
            {"hooks": [ours, other]}]}}), encoding="utf-8")
        install.unregister_hook(settings=self.settings)
        actual = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(actual["hooks"]["UserPromptSubmit"], [{"hooks": [other]}])

    def test_uninstall_when_not_registered_leaves_file_untouched(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text('{"model": "opus"}', encoding="utf-8")
        install.unregister_hook(settings=self.settings)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), '{"model": "opus"}')
        install.unregister_hook(settings=self.directory / "missing.json")

    def test_uninstall_bad_json_never_overwritten(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text("NOT JSON", encoding="utf-8")
        with self.assertRaises(install.InstallationError):
            install.unregister_hook(settings=self.settings)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "NOT JSON")

    def test_uninstall_cli_uses_config_dir_and_keeps_data(self):
        config_dir = self.directory / "cfg"
        data = self.directory / "data"
        data.mkdir()
        install.register_hook(self.python, settings=config_dir / "settings.json")
        with patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(config_dir),
                                       "DOCUMENT_GATE_HOME": str(data)}):
            self.assertEqual(install.main(["--uninstall"]), 0)
        self.assertEqual(json.loads((config_dir / "settings.json").read_text(encoding="utf-8")), {})
        self.assertTrue(data.exists())

    def test_macos_requires_flag(self):
        with patch.object(install.sys, "platform", "darwin"), \
             patch.object(install, "check_python_version", side_effect=AssertionError("must not run")):
            self.assertEqual(install.main([]), 2)

    def test_uninstall_works_on_macos_without_flag(self):
        install.register_hook(self.python, settings=self.settings)
        with patch.object(install.sys, "platform", "darwin"), \
             patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(self.settings.parent)}):
            self.assertEqual(install.main(["--uninstall"]), 0)
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), {})

    def test_ensure_user_config_creates_only_when_missing(self):
        (self.directory / "config.default.json").write_text('{"sanitize": true}', encoding="utf-8")
        with patch.object(install, "PROJECT_DIR", self.directory):
            install.ensure_user_config()
            target = self.directory / "config.json"
            self.assertEqual(target.read_text(encoding="utf-8"), '{"sanitize": true}')
            target.write_text('{"sanitize": false}', encoding="utf-8")
            install.ensure_user_config()
            self.assertEqual(target.read_text(encoding="utf-8"), '{"sanitize": false}')

    def test_macos_proceeds_with_flag(self):
        with patch.object(install.sys, "platform", "darwin"), \
             patch.object(install, "check_python_version"), \
             patch.object(install, "ensure_venv", return_value=self.python), \
             patch.object(install, "install_dependencies"), \
             patch.object(install, "ensure_user_config"), \
             patch.object(install, "register_hook") as register:
            self.assertEqual(install.main(["--allow-macos", "--skip-tests"]), 0)
            register.assert_called_once()

    def test_install_dependencies_uses_all_extras(self):
        with patch.object(install, "run_checked") as runner, patch.object(install, "verify_markitdown") as verifier:
            install.install_dependencies(self.python, upgrade=False)
            self.assertEqual(runner.call_args.args[0][-1], "markitdown[all]")
            self.assertEqual(runner.call_args.args[0][:4],
                             [str(self.python), "-m", "pip", "--disable-pip-version-check"])
            verifier.assert_called_once_with(self.python)

    def test_created_venv_interpreter_is_really_isolated(self):
        # Regression test: .resolve() follows the POSIX python symlink back
        # to the system interpreter, silently bypassing installed dependencies.
        target = self.directory / "clean-venv"
        python = install.ensure_venv(target=target)
        self.assertEqual(python, install.venv_python(target).absolute())
        result = subprocess.run(
            [str(python), "-c", "import sys; print(sys.prefix != sys.base_prefix)"],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), "True")

    def test_incomplete_venv_aborts_without_overwrite(self):
        existing = self.directory / ".venv"
        existing.mkdir()
        (existing / "some-file").write_text("old", encoding="utf-8")
        with self.assertRaises(install.InstallationError):
            install.ensure_venv(target=existing)
        self.assertTrue((existing / "some-file").exists())

    def test_dependency_error_prevents_hook_registration(self):
        with patch.object(install, "check_python_version"), \
             patch.object(install, "ensure_venv", return_value=self.python), \
             patch.object(install, "install_dependencies", side_effect=install.InstallationError("pip failed")), \
             patch.object(install, "register_hook") as register:
            self.assertEqual(install.main(["--skip-tests"]), 1)
            register.assert_not_called()


if __name__ == "__main__":
    unittest.main()
