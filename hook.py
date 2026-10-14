"""Claude Code UserPromptSubmit hook: block originals, send sanitized references.

This hook writes the notification SYNCHRONOUSLY into its own session inbox.
Doing so while this hook process is alive lets Claude Code verify its
own-child origin via Linux process ancestry, avoiding the detached-worker
classification that can cause a held peer message in bypass mode.

Only file references detectable in prompt text can be guarded here.
Do NOT interpret this as a universal security boundary for all attachments.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from config import ConfigError, default_config, load_config
from document_gate import is_harness_message, process_prompt
from message_format import build_frames, encode_frames
from session_transport import send_frames


def decision_block(reason: str) -> dict:
    return {"decision": "block", "reason": reason, "suppressOriginalPrompt": True}


def handle(payload: dict, *, notify_session: bool = True) -> dict:
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        return decision_block("Document gate: malformed prompt payload; blocked.")
    # Don't silently process unknown attachment fields as textual paths.
    if any(payload.get(k) for k in ("attachments", "files", "media")):
        return decision_block(
            "Document gate: non-text attachment metadata detected. This hook cannot "
            "safely extract its bytes; original prompt blocked. Supply a local file path."
        )
    # Harness-generated messages are not user input; checked after attachment fields.
    if is_harness_message(prompt):
        return {}

    cwd = Path(payload.get("cwd") or os.getcwd())
    try:
        config, config_error = load_config(), None
    except ConfigError as exc:
        config, config_error = default_config(), str(exc)
    found, rewritten, files, error = process_prompt(prompt, cwd, config, config_error)
    if not found:
        return {}
    if error:
        if not error.startswith("Document gate"):
            error = "Document gate: " + error
        return decision_block(error + ". Original message was NOT sent to the model.")

    targets = "\n".join(files)
    label = ("Sanitized file(s):" if config.sanitize
             else "Converted file(s) (sanitization OFF):")
    address = os.getenv("CLAUDE_CODE_MESSAGING_SOCKET", "")
    token = os.getenv("CLAUDE_CODE_MESSAGING_TOKEN", "")
    session_id = payload.get("session_id", "")
    if not address or not token or not session_id:
        return decision_block(
            "Original prompt blocked. " + label + "\n" + targets +
            "\nAutomatic notification unavailable (missing session inbox, token, or session ID). "
            "Submit a NEW request referencing only the sanitized file(s)."
        )

    if not notify_session:
        return decision_block("Original prompt blocked; " + label + "\n" + targets)

    try:
        # The socket schema stays isolated in session_message.json/message_format.py.
        frames = build_frames(
            token=token,
            session_id=session_id,
            prompt=rewritten,
            files=files,
            sanitized=config.sanitize,
        )
        # No Popen, new session, delay or detached subprocess here: the sender
        # is the hook process itself, while its Claude Code parent is still alive.
        send_frames(address, encode_frames(frames))
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        return decision_block(
            "Original prompt blocked. " + label + "\n" + targets +
            "\nSession notification failed: " + type(exc).__name__ +
            ". Submit a NEW request referencing only the sanitized file(s)."
        )

    return decision_block(
        "Original file request blocked before inference. " + label + "\n" +
        targets +
        "\nNotification written directly from this hook to its own session inbox. "
        "Whether Claude Code delivers it is controlled by its inbound policy."
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        outcome = handle(payload)
    except Exception as exc:
        # Fail closed if Python runs to completion. Claude Code hook timeouts
        # can still fail open without additional client-level safeguards.
        outcome = decision_block(
            "Document gate failed; original request blocked: " +
            type(exc).__name__ + ": " + str(exc)[:180]
        )
    print(json.dumps(outcome, ensure_ascii=False))


if __name__ == "__main__":
    main()
