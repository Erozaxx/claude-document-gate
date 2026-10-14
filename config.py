"""Configuration: code defaults < config.default.json < config.json < environment.

Loaded on every hook run (the hook is a short-lived process); nothing is cached.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

# Extensions MarkItDown (as configured by install.py) can convert.
ALLOWED_CONVERT = frozenset({".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm",
                             ".epub", ".csv", ".txt", ".md"})
DEFAULT_CONVERT = (".pdf", ".docx", ".pptx", ".xlsx", ".epub")
DEFAULT_BLOCK = (".doc", ".xls", ".ppt", ".zip", ".7z", ".png", ".jpg", ".jpeg", ".exe", ".bin")
KNOWN_KEYS = ("convert_extensions", "block_extensions", "sanitize")
ENV_CONVERT = "DOCUMENT_GATE_EXTENSIONS"
ENV_BLOCK = "DOCUMENT_GATE_BLOCK_EXTENSIONS"
ENV_SANITIZE = "DOCUMENT_GATE_SANITIZE"
_EXT_RE = re.compile(r"^\.[a-z0-9]{1,16}$")
_TRUE = {"1", "true", "on", "yes"}
_FALSE = {"0", "false", "off", "no"}


class ConfigError(ValueError):
    """Invalid configuration; the message says what and where."""


@dataclass(frozen=True)
class Config:
    convert: frozenset
    block: frozenset
    sanitize: bool = True

    @property
    def detected(self) -> frozenset:
        return self.convert | self.block


def default_config() -> Config:
    return Config(frozenset(DEFAULT_CONVERT), frozenset(DEFAULT_BLOCK), True)


def _norm_ext(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{where}: extension must be a string, got {type(value).__name__}")
    ext = value.strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    if not _EXT_RE.match(ext):
        raise ConfigError(f"{where}: invalid extension {value!r}")
    return ext


def _ext_list(value: object, where: str, *, convert: bool) -> frozenset:
    if not isinstance(value, list):
        raise ConfigError(f"{where}: expected a list of extensions")
    result = frozenset(_norm_ext(v, where) for v in value)
    if convert:
        unknown = sorted(result - ALLOWED_CONVERT)
        if unknown:
            raise ConfigError(f"{where}: unsupported conversion extension(s) {', '.join(unknown)}; "
                              f"allowed: {', '.join(sorted(ALLOWED_CONVERT))}")
    return result


def _parse_bool(value: object, where: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
    raise ConfigError(f"{where}: expected true/false, got {value!r}")


def _read_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path.name}: cannot read/parse ({type(exc).__name__}: {str(exc)[:100]})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: expected a JSON object")
    unknown = sorted(set(data) - set(KNOWN_KEYS))
    if unknown:
        raise ConfigError(f"{path.name}: unknown key(s) {', '.join(unknown)}")
    return data


def _split_env(text: str, where: str, *, convert: bool) -> frozenset:
    return _ext_list([p for p in (x.strip() for x in text.split(",")) if p], where, convert=convert)


def load_config(env=None, project_dir: Path | None = None) -> Config:
    """Raises ConfigError on any invalid layer."""
    env = os.environ if env is None else env
    base = Path(project_dir) if project_dir is not None else PROJECT_DIR
    convert = frozenset(DEFAULT_CONVERT)
    block = frozenset(DEFAULT_BLOCK)
    sanitize = True
    for name in ("config.default.json", "config.json"):
        data = _read_file(base / name)
        if "convert_extensions" in data:
            convert = _ext_list(data["convert_extensions"], f"{name} convert_extensions", convert=True)
        if "block_extensions" in data:
            block = _ext_list(data["block_extensions"], f"{name} block_extensions", convert=False)
        if "sanitize" in data:
            if not isinstance(data["sanitize"], bool):
                raise ConfigError(f"{name} sanitize: expected true/false")
            sanitize = data["sanitize"]
    if ENV_CONVERT in env:
        convert = _split_env(env[ENV_CONVERT], ENV_CONVERT, convert=True)
    if ENV_BLOCK in env:
        block = _split_env(env[ENV_BLOCK], ENV_BLOCK, convert=False)
    if ENV_SANITIZE in env:
        sanitize = _parse_bool(env[ENV_SANITIZE], ENV_SANITIZE)
    # An extension listed in both places is blocked (safer than converting).
    return Config(convert - block, block, sanitize)
