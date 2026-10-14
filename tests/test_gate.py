import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg
import document_gate as gate
from sanitizer import SANITIZER_VERSION, sanitize
from message_format import build_frames, encode_frames
import hook


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        for name, value in (("ROOT", base / "app"),
                            ("SANITIZED", base / "app" / "sanitized")):
            p = patch.object(gate, name, value); p.start(); self.addCleanup(p.stop)
        # Isolate from the real config.json / environment; .md and .txt are
        # convertible in these tests (the shipped default converts binary formats only).
        env = {k: v for k, v in os.environ.items() if not k.startswith("DOCUMENT_GATE_")}
        env["DOCUMENT_GATE_EXTENSIONS"] = ".md,.txt,.pdf"
        p = patch.dict(os.environ, env, clear=True); p.start(); self.addCleanup(p.stop)
        p = patch.object(cfg, "PROJECT_DIR", base / "proj"); p.start(); self.addCleanup(p.stop)
        gate.prepare_dirs()
        self.cwd = base

    def test_czech_phone_and_invalid_checksum_iban_are_redacted(self):
        # Real-world example: plausible CZ IBAN intentionally has wrong MOD-97.
        sample = ("Telefon: +420 731 456 789\n"
                  "Telefon: +420 608 123 456\n"
                  "Bankovní spojení: CZ65 0800 0000 0012 3456 7899, Česká spořitelna a.s.")
        output, counts = sanitize(sample, key=b"stable-test-secret")
        self.assertEqual(counts, {"IBAN": 1, "PHONE": 2})
        for fragment in ("731 456 789", "608 123 456", "CZ65 0800"):
            self.assertNotIn(fragment, output)
        self.assertIn("[REDACTED_IBAN_", output)
        self.assertEqual(output.count("[REDACTED_PHONE_"), 2)
        self.assertIn("Česká spořitelna a.s.", output)

    def test_iban_and_phone_formats_and_stable_tokens(self):
        # Same IBAN / phone formatted differently yields the same pseudonym.
        cases = ("CZ6508000000001234567899", "cz65 0800 0000 0012 3456 7899",
                 "GB82 WEST 1234 5698 7654 32", "DE89370400440532013000")
        output, counts = sanitize("\n".join(cases), key=b"stable-test-secret")
        self.assertEqual(counts, {"IBAN": 4})
        placeholders = output.splitlines()
        self.assertEqual(placeholders[0], placeholders[1])
        self.assertNotEqual(placeholders[2], placeholders[3])
        phone_output, phone_counts = sanitize(
            "731456789\n731 456 789\n+420 731 456 789\n00420-731-456-789",
            key=b"stable-test-secret",
        )
        self.assertEqual(phone_counts, {"PHONE": 4})
        self.assertEqual(len(set(phone_output.splitlines())), 1)

    def test_numbers_not_wrongly_redacted_as_phones(self):
        sample = ("IČO 04812367, částka 150 000 Kč, IPv4 255.255.255.255, "
                  "paragraf 1746, datum 12.10.2026")
        output, counts = sanitize(sample, key=b"test-secret")
        self.assertIn("04812367", output)
        self.assertIn("150 000", output)
        self.assertIn("[REDACTED_IPV4_", output)
        self.assertNotIn("PHONE", counts)

    def test_older_sanitizer_cache_reprocessed(self):
        doc = self.cwd / "contract.md"
        doc.write_text("Telefon: +420 731 456 789", encoding="utf-8")
        old_file = gate.convert_one(doc)
        old_meta = old_file.with_suffix(".meta.json")
        meta = json.loads(old_meta.read_text(encoding="utf-8"))
        self.assertEqual(meta["sanitizer_version"], SANITIZER_VERSION)
        meta["sanitizer_version"] = SANITIZER_VERSION - 1
        old_meta.write_text(json.dumps(meta), encoding="utf-8")
        self.assertFalse(gate.is_verified_sanitized(old_file))
        updated = gate.convert_one(doc)
        self.assertEqual(updated, old_file)
        self.assertTrue(gate.is_verified_sanitized(updated))
        self.assertIn("[REDACTED_PHONE_", updated.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(old_meta.read_text(encoding="utf-8"))["sanitizer_version"], SANITIZER_VERSION)

    def test_media_metadata_blocks(self):
        result = hook.handle({"prompt": "Look at this", "media": [{"kind": "application/pdf"}]}, notify_session=False)
        self.assertEqual(result["decision"], "block")

    def test_no_file_allowed(self):
        self.assertFalse(gate.process_prompt("Ahoj jak se mas?", self.cwd)[0])

    def test_input_document_blocked_and_converted(self):
        document = self.cwd / "my report.md"
        document.write_text("Contact jane@example.com and 192.168.1.7", encoding="utf-8")
        prompt = 'Najdi udaje v "my report.md".'
        blocked, rewritten, files, error = gate.process_prompt(prompt, self.cwd)
        self.assertTrue(blocked); self.assertIsNone(error)
        self.assertEqual(len(files), 1)
        self.assertIn("sanitized_", rewritten)
        sanitized = Path(files[0]).read_text(encoding="utf-8")
        self.assertNotIn("jane@example.com", sanitized)
        self.assertNotIn("192.168.1.7", sanitized)
        self.assertTrue(gate.is_verified_sanitized(Path(files[0])))
        blocked2, _, _, error2 = gate.process_prompt('Najdi udaje v "' + files[0] + '".', self.cwd)
        self.assertFalse(blocked2); self.assertIsNone(error2)

    def test_quoted_windows_path_after_question_mark_has_separator(self):
        # This tests precisely the prompt formatting from the real-world report,
        # while substituting an already-convertible Markdown file in the test.
        doc = self.cwd / "demo_smlouva.md"
        doc.write_text("Agreement body", encoding="utf-8")
        prompt = "o cem je tenhle soubor?'demo_smlouva.md'"
        found, rewritten, files, error = gate.process_prompt(prompt, self.cwd)
        self.assertTrue(found)
        self.assertIsNone(error)
        self.assertEqual(len(files), 1)
        self.assertIn('soubor? "', rewritten)
        self.assertIn('sanitized_demo_smlouva_', rewritten)
        self.assertNotIn('soubor?"', rewritten)

    def test_path_next_to_word_is_delimited(self):
        doc = self.cwd / "document.md"
        doc.write_text("Safe content", encoding="utf-8")
        prompt = 'Otevri "document.md"ted'
        found, rewritten, files, error = gate.process_prompt(prompt, self.cwd)
        self.assertTrue(found)
        self.assertIsNone(error)
        self.assertIn('" ted', rewritten)

    @unittest.skipIf(os.name == "nt", "Unix socket test; Windows uses named pipes")
    def test_hook_sends_itself_without_subprocess(self):
        doc = self.cwd / "secret.md"
        doc.write_text("Contract body", encoding="utf-8")
        env = {"CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/mock.sock",
               "CLAUDE_CODE_MESSAGING_TOKEN": "mock-token"}
        with patch.dict(os.environ, env), \
             patch("subprocess.Popen") as popen, \
             patch.object(hook, "send_frames") as send:
            result = hook.handle({"prompt": 'Zkontroluj "secret.md"',
                                  "cwd": str(self.cwd), "session_id": "session-123"})
        self.assertEqual(result["decision"], "block")
        popen.assert_not_called()
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "/tmp/mock.sock")
        self.assertFalse((gate.ROOT / "pending").exists())

    def test_send_failure_still_blocks(self):
        doc = self.cwd / "secret.md"
        doc.write_text("Contract body", encoding="utf-8")
        env = {"CLAUDE_CODE_MESSAGING_SOCKET": "/nonexistent/mock.sock",
               "CLAUDE_CODE_MESSAGING_TOKEN": "mock-token"}
        with patch.dict(os.environ, env), \
             patch.object(hook, "send_frames", side_effect=OSError("boom")):
            result = hook.handle({"prompt": 'Zkontroluj "secret.md"',
                                  "cwd": str(self.cwd), "session_id": "s"})
        self.assertEqual(result["decision"], "block")
        self.assertIn("notification failed", result["reason"])

    def test_harness_prefixes_pass_through(self):
        (self.cwd / "doc.md").write_text("Contract body", encoding="utf-8")
        (self.cwd / "doc.pdf").write_bytes(b"%PDF")
        for prefix in gate.HARNESS_PREFIXES:
            with self.subTest(prefix=prefix):
                prompt = "  \n" + prefix + "\nvysledek, viz doc.md a doc.pdf"
                self.assertEqual(hook.handle({"prompt": prompt, "cwd": str(self.cwd)},
                                             notify_session=False), {})

    def test_harness_prefix_does_not_skip_attachment_check(self):
        result = hook.handle({"prompt": "<task-notification>\nx", "media": [{"k": 1}],
                              "cwd": str(self.cwd)}, notify_session=False)
        self.assertEqual(result["decision"], "block")

    def test_same_content_without_prefix_is_converted(self):
        (self.cwd / "doc.md").write_text("Contract body", encoding="utf-8")
        result = hook.handle({"prompt": "vysledek, viz doc.md", "cwd": str(self.cwd)},
                             notify_session=False)
        self.assertEqual(result["decision"], "block")

    def test_prefix_in_middle_does_not_bypass(self):
        (self.cwd / "doc.md").write_text("Contract body", encoding="utf-8")
        result = hook.handle({"prompt": "ahoj <task-notification>\nviz doc.md",
                              "cwd": str(self.cwd)}, notify_session=False)
        self.assertEqual(result["decision"], "block")

    def test_tampered_sanitized_is_rejected(self):
        path = self.cwd / "test.md"
        path.write_text("hello", encoding="utf-8")
        target = gate.convert_one(path)
        target.write_text("changed", encoding="utf-8")
        self.assertFalse(gate.is_verified_sanitized(target))

    def test_unsupported_blocks(self):
        doc = self.cwd / "sample.zip"
        doc.write_bytes(b"abc")
        found, _, _, error = gate.process_prompt("Check @sample.zip", self.cwd)
        self.assertTrue(found)
        self.assertIn("Unsupported", error)

    def test_existing_unsupported_png_blocks(self):
        (self.cwd / "pic.png").write_bytes(b"x")
        found, _, _, error = gate.process_prompt("popis pic.png", self.cwd)
        self.assertTrue(found)
        self.assertIn("Unsupported", error)

    def test_missing_file_is_ignored(self):
        for prompt in ("Check @absent.pdf", "vytvor mi README.md", "oprav config.json",
                       'oprav "sub/config.json"', f"cti {self.cwd}/nope.md",
                       "cti C:\\nonexistent_dir_xyz\\a.pdf"):
            with self.subTest(prompt=prompt):
                self.assertEqual(gate.process_prompt(prompt, self.cwd), (False, prompt, [], None))

    def test_missing_file_with_paste_marker_still_blocked_by_marker_only(self):
        found, _, _, error = gate.process_prompt("vytvor a.md <pasted_content>x", self.cwd)
        self.assertTrue(found)
        self.assertIn("Inline attachment", error)

    def test_mixed_existing_and_missing(self):
        (self.cwd / "real.md").write_text("hello", encoding="utf-8")
        found, rewritten, files, error = gate.process_prompt(
            "porovnej real.md a ghost.md", self.cwd)
        self.assertTrue(found); self.assertIsNone(error)
        self.assertEqual(len(files), 1)
        self.assertIn("sanitized_real_", rewritten)
        self.assertIn("ghost.md", rewritten)
        self.assertNotIn("real.md", rewritten)

    def test_directory_with_file_extension_is_ignored(self):
        (self.cwd / "report.pdf").mkdir()
        prompt = "otevri report.pdf"
        self.assertEqual(gate.process_prompt(prompt, self.cwd), (False, prompt, [], None))

    @unittest.skipIf(os.name == "nt", "Unix socket test; Windows uses named pipes")
    def test_socket_transport_to_local_unix_receiver(self):
        import socket
        from session_transport import send_frames
        sock_dir = tempfile.mkdtemp(prefix="dg")
        self.addCleanup(lambda: __import__("shutil").rmtree(sock_dir, ignore_errors=True))
        sock_file = os.path.join(sock_dir, "i.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(sock_file)
        listener.listen(1)
        self.addCleanup(listener.close)
        frames = build_frames(token="local", session_id="sid", prompt="Test", files=["/tmp/file.md"])
        send_frames(sock_file, encode_frames(frames))
        conn, _ = listener.accept()
        with conn:
            stream = conn.makefile("rb")
            data = [json.loads(stream.readline()), json.loads(stream.readline())]
        self.assertEqual(data[0]["type"], "auth")
        self.assertEqual(data[1]["type"], "user")

    @unittest.skipIf(os.name == "nt", "Unix socket integration test; Windows uses named pipes")
    def test_hook_to_socket_end_to_end(self):
        import socket
        import threading
        # Short path: AF_UNIX paths are limited to ~108 characters.
        with tempfile.TemporaryDirectory(prefix="dg") as sock_dir:
            sock_path = os.path.join(sock_dir, "c.sock")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.settimeout(8)
            listener.bind(sock_path)
            listener.listen(1)
            self.addCleanup(listener.close)
            received = []

            def serve():
                conn, _ = listener.accept()
                with conn:
                    conn.settimeout(8)
                    chunks = []
                    while True:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    received.append(b"".join(chunks))

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            doc = self.cwd / "demo.md"
            doc.write_text("Contact: jane@example.com", encoding="utf-8")
            env = {"CLAUDE_CODE_MESSAGING_SOCKET": sock_path,
                   "CLAUDE_CODE_MESSAGING_TOKEN": "mock-session-token"}
            with patch.dict(os.environ, env):
                result = hook.handle({"prompt": "Popis soubor?'demo.md'",
                                      "cwd": str(self.cwd), "session_id": "session-test"})
            thread.join(timeout=10)
        self.assertEqual(result["decision"], "block")
        self.assertEqual(len(received), 1)
        frames = [json.loads(line) for line in received[0].splitlines()]
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0], {"type": "auth", "token": "mock-session-token"})
        self.assertEqual(frames[1]["session_id"], "session-test")
        body = frames[1]["message"]["content"]
        self.assertIn('soubor? "', body)
        self.assertIn("sanitized_demo_", body)
        self.assertNotIn("jane@example.com", body)
        self.assertNotIn("'demo.md'", body)
        self.assertNotIn(str(doc), body)
        self.assertNotIn("mock-session-token", body)

    def test_socket_payload_is_separate(self):
        frames = build_frames(token="secret", session_id="abc123", prompt="Check file", files=["/tmp/sanitized_x.md"])
        self.assertEqual(frames[0], {"type": "auth", "token": "secret"})
        self.assertEqual(frames[1]["message"]["role"], "user")
        self.assertIn("Check file", frames[1]["message"]["content"])
        self.assertEqual(len(encode_frames(frames).splitlines()), 2)

    def test_hook_does_not_allow_original(self):
        doc = self.cwd / "secret.md"
        doc.write_text("user alice@example.org", encoding="utf-8")
        with patch.dict(os.environ, {"CLAUDE_CODE_MESSAGING_SOCKET": "", "CLAUDE_CODE_MESSAGING_TOKEN": ""}):
            result = hook.handle({"prompt": "Read @secret.md", "cwd": str(self.cwd)}, notify_session=False)
        self.assertEqual(result["decision"], "block")
        self.assertIn("sanitized_", result["reason"])


if __name__ == "__main__":
    unittest.main()
