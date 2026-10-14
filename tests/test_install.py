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

    def test_windows_command_uses_forward_slashes_and_quotes(self):
        cmd = install.command_for_hook(Path("D:\\TNE_NEW\\x y\\.venv\\Scripts\\python.exe"),
                                       Path("D:\\TNE_NEW\\x y\\hook.py"), windows=True)
        self.assertEqual(cmd, '"D:/TNE_NEW/x y/.venv/Scripts/python.exe" "D:/TNE_NEW/x y/hook.py"')

    def test_windows_command_rejects_unsafe_characters(self):
        for bad in ('D:/a"b/hook.py', "D:/a$b/hook.py", "D:/a`b/hook.py"):
            with self.subTest(bad=bad), self.assertRaises(install.InstallationError):
                install.command_for_hook(Path("D:/py.exe"), Path(bad), windows=True)

    def test_posix_command_unchanged(self):
        self.assertEqual(install.command_for_hook(Path("/a b/py"), Path("/c/hook.py"), windows=False),
                         "'/a b/py' /c/hook.py")

    def test_is_our_hook_recognises_old_backslash_and_new_form(self):
        script = Path("D:/TNE_NEW/claude-document-gate/hook.py")
        old = {"command": r"D:\TNE_NEW\claude-document-gate\.venv\Scripts\python.exe D:\TNE_NEW\claude-document-gate\hook.py"}
        new = {"command": '"D:/TNE_NEW/claude-document-gate/.venv/Scripts/python.exe" "D:/TNE_NEW/claude-document-gate/hook.py"'}
        self.assertTrue(install.is_our_hook(old, script))
        self.assertTrue(install.is_our_hook(new, script))
        self.assertFalse(install.is_our_hook({"command": "other-tool"}, script))

    def test_reinstall_replaces_old_backslash_entry(self):
        self.settings.parent.mkdir(parents=True)
        old = r"D:\x\claude-document-gate\.venv\Scripts\python.exe D:\x\claude-document-gate\hook.py"
        self.settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": old}]}]}}), encoding="utf-8")
        install.register_hook(self.python, settings=self.settings)
        entries = json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(entries), 1)
        self.assertNotEqual(entries[0]["hooks"][0]["command"], old)

    def _run(self, returncode=0, stdout="{}\n", stderr=""):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def test_self_check_success_and_stdin(self):
        with patch.object(install.subprocess, "run", return_value=self._run()) as run:
            self.assertEqual(install.self_check_hook("cmd", windows=False), (True, ""))
        self.assertEqual(run.call_args.args[0], ["/bin/sh", "-c", "cmd"])
        self.assertEqual(json.loads(run.call_args.kwargs["input"])["prompt"], "document gate self-check")

    def test_self_check_failures(self):
        for result in (self._run(127, "", "command not found"), self._run(0, "garbage"),
                       self._run(0, '{"decision": "block"}')):
            with self.subTest(result=result), patch.object(install.subprocess, "run", return_value=result):
                ok, detail = install.self_check_hook("cmd", windows=False)
                self.assertFalse(ok)
                self.assertTrue(detail)
        with patch.object(install.subprocess, "run", side_effect=OSError("nope")):
            self.assertFalse(install.self_check_hook("cmd", windows=False)[0])

    def test_self_check_windows_uses_git_bash_or_warns(self):
        with patch.object(install, "find_windows_bash", return_value="C:/Git/bin/bash.exe"), \
             patch.object(install.subprocess, "run", return_value=self._run()) as run:
            self.assertTrue(install.self_check_hook("cmd", windows=True)[0])
        self.assertEqual(run.call_args.args[0], ["C:/Git/bin/bash.exe", "-c", "cmd"])
        with patch.object(install, "find_windows_bash", return_value=None):
            self.assertIsNone(install.self_check_hook("cmd", windows=True)[0])

    def test_main_fails_with_warning_when_self_check_fails(self):
        with patch.object(install, "check_python_version"), \
             patch.object(install, "ensure_venv", return_value=self.python), \
             patch.object(install, "install_dependencies"), \
             patch.object(install, "ensure_user_config"), \
             patch.object(install, "register_hook"), \
             patch.object(install, "self_check_hook", return_value=(False, "exit code 127")):
            self.assertEqual(install.main(["--skip-tests"]), 1)

    def test_main_only_warns_when_shell_missing(self):
        with patch.object(install, "check_python_version"), \
             patch.object(install, "ensure_venv", return_value=self.python), \
             patch.object(install, "install_dependencies"), \
             patch.object(install, "ensure_user_config"), \
             patch.object(install, "register_hook"), \
             patch.object(install, "self_check_hook", return_value=(None, "no bash")):
            self.assertEqual(install.main(["--skip-tests"]), 0)

    def test_macos_proceeds_with_flag(self):
        with patch.object(install.sys, "platform", "darwin"), \
             patch.object(install, "check_python_version"), \
             patch.object(install, "ensure_venv", return_value=self.python), \
             patch.object(install, "install_dependencies"), \
             patch.object(install, "ensure_user_config"), \
             patch.object(install, "self_check_hook", return_value=(True, "")), \
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
