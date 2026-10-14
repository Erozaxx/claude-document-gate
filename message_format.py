"""The ONLY module dealing with Claude Code's UNOFFICIAL peer wire schema.

Edit session_message.json to change JSON keys, type, priority and message text.
Transport and conversion modules deliberately do not build wire-format JSON.
"""
from __future__ import annotations
import json
import uuid
from pathlib import Path
from string import Template

CONFIG = Path(__file__).with_name("session_message.json")


def _expand(obj, variables):
    if isinstance(obj, str):
        return Template(obj).safe_substitute(variables)
    if isinstance(obj, dict):
        return {k: _expand(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand(v, variables) for v in obj]
    return obj


def build_frames(*, token: str, session_id: str, prompt: str, files: list[str],
                sanitized: bool = True):
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    content = Template(config["body_template"]).safe_substitute(
        prompt=prompt, files="\n".join('- "' + f + '"' for f in files),
        mode="SANITIZED" if sanitized else "CONVERTED",
        adj="sanitized" if sanitized else "converted (sanitization OFF)",
    )
    variables = {
        "token": token,
        "session_id": session_id,
        "msg_id": str(uuid.uuid4()),
        "content": content,
    }
    return [_expand(config["auth_frame"], variables),
            _expand(config["message_frame"], variables)]


def encode_frames(frames) -> bytes:
    return ("\n".join(json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
                      for frame in frames) + "\n").encode("utf-8")
