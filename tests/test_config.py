"""Configuration layering and its effect on the gate (no real config, settings or network)."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg
import document_gate as gate
import hook


class LoadConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, data):
        (self.dir / name).write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

    def load(self, env=None):
        return cfg.load_config(env=env or {}, project_dir=self.dir)

    def test_code_defaults_without_files(self):
        c = self.load()
        self.assertEqual(c.convert, frozenset(cfg.DEFAULT_CONVERT))
        self.assertEqual(c.block, frozenset(cfg.DEFAULT_BLOCK))
        self.assertTrue(c.sanitize)
        self.assertNotIn(".md", c.convert)

    def test_shipped_default_file_matches_code_defaults(self):
        c = cfg.load_config(env={}, project_dir=Path(cfg.__file__).parent / "does-not-matter")
        shipped = json.loads((Path(cfg.__file__).parent / "config.default.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(shipped["convert_extensions"]), sorted(c.convert))
        self.assertEqual(sorted(shipped["block_extensions"]), sorted(c.block))
        self.assertIs(shipped["sanitize"], True)

    def test_priority_defaults_file_user_file_env(self):
        self.write("config.default.json", {"convert_extensions": [".pdf"], "sanitize": True})
        self.assertEqual(self.load().convert, frozenset({".pdf"}))
        self.write("config.json", {"convert_extensions": [".docx"], "sanitize": False})
        c = self.load()
        self.assertEqual(c.convert, frozenset({".docx"}))
        self.assertFalse(c.sanitize)
        c = self.load({"DOCUMENT_GATE_EXTENSIONS": "MD, .Txt", "DOCUMENT_GATE_SANITIZE": "yes"})
        self.assertEqual(c.convert, frozenset({".md", ".txt"}))
        self.assertTrue(c.sanitize)

    def test_env_block_extensions(self):
        self.assertEqual(self.load({"DOCUMENT_GATE_BLOCK_EXTENSIONS": "zip,.PNG"}).block,
                         frozenset({".zip", ".png"}))
        self.assertEqual(self.load({"DOCUMENT_GATE_BLOCK_EXTENSIONS": ""}).block, frozenset())

    def test_env_sanitize_values(self):
        for value, expected in (("1", True), ("0", False), ("true", True), ("FALSE", False),
                                ("on", True), ("off", False), ("yes", True), ("no", False)):
            with self.subTest(value=value):
                self.assertIs(self.load({"DOCUMENT_GATE_SANITIZE": value}).sanitize, expected)

    def test_invalid_env_values(self):
        for env in ({"DOCUMENT_GATE_SANITIZE": "maybe"},
                    {"DOCUMENT_GATE_EXTENSIONS": "pdf,exe"},
                    {"DOCUMENT_GATE_EXTENSIONS": "p d f"},
                    {"DOCUMENT_GATE_BLOCK_EXTENSIONS": "zi/p"}):
            with self.subTest(env=env), self.assertRaises(cfg.ConfigError):
                self.load(env)

    def test_invalid_files(self):
        for data in ("{not json", "[]", {"bogus": 1}, {"convert_extensions": "pdf"},
                     {"convert_extensions": [".exe"]}, {"convert_extensions": [1]},
                     {"block_extensions": ["a b"]}, {"sanitize": "yes"}):
            with self.subTest(data=data):
                self.write("config.json", data)
                with self.assertRaises(cfg.ConfigError) as ctx:
                    self.load()
                self.assertIn("config.json", str(ctx.exception))

    def test_extension_in_both_lists_is_blocked(self):
        c = self.load({"DOCUMENT_GATE_EXTENSIONS": "pdf,md", "DOCUMENT_GATE_BLOCK_EXTENSIONS": "md"})
        self.assertEqual(c.convert, frozenset({".pdf"}))
        self.assertIn(".md", c.block)


class FakeMarkItDownMixin:
    def fake_markitdown(self, text="Kontakt: jane@example.com"):
        module = types.ModuleType("markitdown")

        class MarkItDown:
            def __init__(self, **kwargs):
                pass

            def convert_local(self, path):
                return types.SimpleNamespace(text_content=text)
        module.MarkItDown = MarkItDown
        return patch.dict(sys.modules, {"markitdown": module})


class GateConfigTests(FakeMarkItDownMixin, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.cwd = base / "work"
        self.cwd.mkdir()
        for name, value in (("ROOT", base / "app"), ("SANITIZED", base / "app" / "sanitized")):
            p = patch.object(gate, name, value); p.start(); self.addCleanup(p.stop)
        env = {k: v for k, v in os.environ.items() if not k.startswith("DOCUMENT_GATE_")}
        p = patch.dict(os.environ, env, clear=True); p.start(); self.addCleanup(p.stop)
        self.proj = base / "proj"
        self.proj.mkdir()
        p = patch.object(cfg, "PROJECT_DIR", self.proj); p.start(); self.addCleanup(p.stop)
        gate.prepare_dirs()

    def run_hook(self, prompt):
        return hook.handle({"prompt": prompt, "cwd": str(self.cwd)}, notify_session=False)

    def test_default_state_text_files_pass_pdf_converts(self):
        (self.cwd / "README.md").write_text("hello", encoding="utf-8")
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        self.assertEqual(self.run_hook("uprav README.md"), {})
        with self.fake_markitdown():
            result = self.run_hook("shrn a.pdf")
        self.assertEqual(result["decision"], "block")
        self.assertIn("Sanitized file(s):", result["reason"])
        self.assertIn("sanitized_a_", result["reason"])

    def test_existing_zip_still_blocked_by_default(self):
        (self.cwd / "x.zip").write_bytes(b"PK")
        self.assertIn("Unsupported", self.run_hook("rozbal x.zip")["reason"])

    def test_extensions_env_enables_md(self):
        (self.cwd / "README.md").write_text("mail jane@example.com", encoding="utf-8")
        with patch.dict(os.environ, {"DOCUMENT_GATE_EXTENSIONS": "md"}):
            result = self.run_hook("uprav README.md")
        self.assertEqual(result["decision"], "block")
        self.assertIn("sanitized_README_", result["reason"])

    def test_sanitize_off_gives_converted_file_and_raw_prompt(self):
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        env = {"DOCUMENT_GATE_SANITIZE": "off"}
        with patch.dict(os.environ, env), self.fake_markitdown():
            found, rewritten, files, error = gate.process_prompt(
                "pis jane@example.com a.pdf", self.cwd)
        self.assertTrue(found); self.assertIsNone(error)
        name = Path(files[0]).name
        self.assertTrue(name.startswith("converted_a_"))
        self.assertIn("jane@example.com", Path(files[0]).read_text(encoding="utf-8"))
        self.assertNotIn("[REDACTED_", Path(files[0]).read_text(encoding="utf-8"))
        self.assertIn("jane@example.com", rewritten)
        self.assertNotIn("[REDACTED_", rewritten)
        meta = json.loads(Path(files[0]).with_suffix(".meta.json").read_text(encoding="utf-8"))
        self.assertIs(meta["sanitized"], False)

    def test_sanitize_off_hook_message_and_reason(self):
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        sent = []
        env = {"DOCUMENT_GATE_SANITIZE": "0", "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/x.sock",
               "CLAUDE_CODE_MESSAGING_TOKEN": "t"}
        with patch.dict(os.environ, env), self.fake_markitdown(), \
             patch.object(hook, "send_frames", side_effect=lambda a, p: sent.append(p)):
            result = hook.handle({"prompt": "shrn a.pdf", "cwd": str(self.cwd), "session_id": "s"})
        self.assertIn("Converted file(s) (sanitization OFF):", result["reason"])
        frames = [json.loads(x) for x in sent[0].splitlines()]
        self.assertTrue(frames[1]["message"]["content"].startswith("[DOCUMENT_GATE: CONVERTED]"))

    def test_sanitize_on_message_header(self):
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        sent = []
        env = {"CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/x.sock", "CLAUDE_CODE_MESSAGING_TOKEN": "t"}
        with patch.dict(os.environ, env), self.fake_markitdown(), \
             patch.object(hook, "send_frames", side_effect=lambda a, p: sent.append(p)):
            hook.handle({"prompt": "shrn a.pdf", "cwd": str(self.cwd), "session_id": "s"})
        frames = [json.loads(x) for x in sent[0].splitlines()]
        self.assertTrue(frames[1]["message"]["content"].startswith("[DOCUMENT_GATE: SANITIZED]"))

    def test_converted_copy_not_verified_when_sanitize_on(self):
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        with patch.dict(os.environ, {"DOCUMENT_GATE_SANITIZE": "off"}), self.fake_markitdown():
            converted = Path(gate.process_prompt("a.pdf", self.cwd)[2][0])
        self.assertTrue(gate.is_verified_sanitized(converted, sanitize_mode=False))
        self.assertFalse(gate.is_verified_sanitized(converted, sanitize_mode=True))
        # Back to sanitize=on: the original is converted again into a sanitized_ copy.
        with self.fake_markitdown():
            found, _, files, _ = gate.process_prompt("a.pdf", self.cwd)
        self.assertTrue(found)
        self.assertTrue(Path(files[0]).name.startswith("sanitized_a_"))
        self.assertNotIn("jane@example.com", Path(files[0]).read_text(encoding="utf-8"))

    def test_direct_reference_to_converted_copy_with_sanitize_on_is_blocked(self):
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        with patch.dict(os.environ, {"DOCUMENT_GATE_SANITIZE": "off"}), self.fake_markitdown():
            converted = gate.process_prompt("a.pdf", self.cwd)[2][0]
        prompt = f'cti "{converted}"'
        for ext_env in (None, "md", "pdf"):
            with self.subTest(ext_env=ext_env):
                env = {} if ext_env is None else {"DOCUMENT_GATE_EXTENSIONS": ext_env}
                with patch.dict(os.environ, env):
                    found, _, files, error = gate.process_prompt(prompt, self.cwd)
                self.assertTrue(found); self.assertEqual(files, [])
                self.assertIn("UNSANITIZED", error)
                self.assertIn("original document", error)
        # sanitize off: the verified converted_ copy is acceptable (when .md is configured).
        with patch.dict(os.environ, {"DOCUMENT_GATE_SANITIZE": "off", "DOCUMENT_GATE_EXTENSIONS": "md"}):
            self.assertEqual(gate.process_prompt(prompt, self.cwd), (False, prompt, [], None))

    def test_ordinary_md_outside_data_dir_still_ignored_by_default(self):
        (self.cwd / "notes.md").write_text("x", encoding="utf-8")
        self.assertEqual(gate.process_prompt("cti notes.md", self.cwd), (False, "cti notes.md", [], None))
        (self.cwd / "converted_x.md").write_text("x", encoding="utf-8")
        self.assertEqual(gate.process_prompt("cti converted_x.md", self.cwd),
                         (False, "cti converted_x.md", [], None))

    def test_converted_message_never_says_sanitized_outside_filenames(self):
        from message_format import build_frames
        frames = build_frames(token="t", session_id="s", prompt='viz "/d/converted_a_1.md"',
                              files=["/d/converted_a_1.md"], sanitized=False)
        body = frames[1]["message"]["content"]
        self.assertTrue(body.startswith("[DOCUMENT_GATE: CONVERTED]"))
        stripped = body.replace("/d/converted_a_1.md", "")
        self.assertNotIn("sanitized", stripped.lower().replace("sanitization off", ""))
        sanitized_body = build_frames(token="t", session_id="s", prompt="p", files=["/d/x"])[1]["message"]["content"]
        self.assertIn("sanitized files", sanitized_body)

    def test_sanitized_copy_accepted_when_sanitize_off(self):
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        with self.fake_markitdown():
            sanitized = Path(gate.process_prompt("a.pdf", self.cwd)[2][0])
        self.assertTrue(gate.is_verified_sanitized(sanitized, sanitize_mode=False))
        self.assertTrue(gate.is_verified_sanitized(sanitized, sanitize_mode=True))

    def test_signature_covers_sanitized_flag(self):
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        with patch.dict(os.environ, {"DOCUMENT_GATE_SANITIZE": "off"}), self.fake_markitdown():
            converted = Path(gate.process_prompt("a.pdf", self.cwd)[2][0])
        meta_path = converted.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["sanitized"] = True
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self.assertFalse(gate.is_verified_sanitized(converted, sanitize_mode=False))

    def test_old_cache_without_flag_not_verified(self):
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        with self.fake_markitdown():
            copy = Path(gate.process_prompt("a.pdf", self.cwd)[2][0])
        meta_path = copy.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        del meta["sanitized"]
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self.assertFalse(gate.is_verified_sanitized(copy))

    def test_invalid_config_blocks_only_existing_default_file(self):
        (self.proj / "config.json").write_text("{broken", encoding="utf-8")
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        (self.cwd / "README.md").write_text("x", encoding="utf-8")
        ok = self.run_hook("uprav README.md a vytvor missing.pdf")
        self.assertEqual(ok, {})
        self.assertEqual(self.run_hook("Ahoj"), {})
        bad = self.run_hook("shrn a.pdf")
        self.assertEqual(bad["decision"], "block")
        self.assertIn("Document gate config error: config.json", bad["reason"])
        self.assertNotIn("Traceback", bad["reason"])

    def test_invalid_env_is_config_error(self):
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        with patch.dict(os.environ, {"DOCUMENT_GATE_SANITIZE": "maybe"}):
            result = self.run_hook("shrn a.pdf")
        self.assertIn("Document gate config error: DOCUMENT_GATE_SANITIZE", result["reason"])

    def test_harness_prefix_covers_both_modes(self):
        (self.cwd / "a.pdf").write_bytes(b"%PDF-1.4")
        for mode in ("SANITIZED", "CONVERTED"):
            self.assertEqual(self.run_hook(f"[DOCUMENT_GATE: {mode}]\nviz a.pdf"), {})


if __name__ == "__main__":
    unittest.main()
