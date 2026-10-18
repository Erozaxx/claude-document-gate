"""File detection, local conversion, verified sanitized cache. No Claude wire schema here."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from config import Config, ConfigError, default_config, load_config
from sanitizer import SANITIZER_VERSION, sanitize

import functools

ROOT = Path(os.environ.get("DOCUMENT_GATE_HOME", str(Path.home() / "local_app" / "claude_document_gate")))
SANITIZED = ROOT / "sanitized"

# Which extensions are detected / converted / blocked comes from config.py.
MAX_SIZE = 25 * 1024 * 1024


# Messages injected by the Claude Code harness (not typed by the user) start with
# one of these prefixes. HEURISTIC based on the current Claude Code format. A user
# can bypass the gate by starting a prompt this way; the hook is not a security
# boundary against the user's own actions.
HARNESS_PREFIXES = (
    "<task-notification>",
    "<cross-session-message",
    "[Cross-session delivery notice]",
    "[Cross-session idle notice]",
    "Another Claude session sent a message",
    "[DOCUMENT_GATE:",  # our own delivered message (SANITIZED / CONVERTED)
)


def is_harness_message(prompt: str) -> bool:
    return prompt.lstrip().startswith(HARNESS_PREFIXES)


def prepare_dirs():
    for p in (ROOT, SANITIZED):
        p.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            p.chmod(0o700)


def atomic_write(path: Path, text: str):
    prepare_dirs()
    fd, tmp = tempfile.mkstemp(prefix=".stage_", dir=str(path.parent))
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass


def secret() -> bytes:
    prepare_dirs()
    key_path = ROOT / "verification.key"
    if not key_path.exists():
        try:
            fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(os.urandom(32))
    return key_path.read_bytes()


def _signature(name: str, sha: str, sanitized: bool) -> str:
    return hmac.new(secret(), f"{name}\n{sha}\n{int(sanitized)}".encode(), hashlib.sha256).hexdigest()


def output_prefix(sanitized: bool) -> str:
    return "sanitized_" if sanitized else "converted_"


def is_verified_sanitized(path: Path, sanitize_mode: bool = True) -> bool:
    """True for our own signed copy that is acceptable in the current mode.

    A converted_ copy (sanitization was OFF) is NOT accepted while sanitize_mode
    is on; a sanitized_ copy is accepted in both modes.
    """
    try:
        path = path.resolve(strict=True)
        if path.parent != SANITIZED.resolve() or path.suffix != ".md":
            return False
        meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
        was_sanitized = meta.get("sanitized")
        if not isinstance(was_sanitized, bool):
            return False
        if not path.name.startswith(output_prefix(was_sanitized)):
            return False
        if sanitize_mode and not was_sanitized:
            return False
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        return (meta.get("sanitizer_version") == SANITIZER_VERSION
                and hmac.compare_digest(meta["sha256"], sha)
                and hmac.compare_digest(meta["signature"], _signature(path.name, sha, was_sanitized)))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def is_converted_copy(path: Path) -> bool:
    """A converted_*.md file (sanitization was OFF) inside our data folder."""
    try:
        path = path.resolve()
        return (path.parent == SANITIZED.resolve() and path.suffix.lower() == ".md"
                and path.name.startswith(output_prefix(False)))
    except OSError:
        return False


def resolve_candidate(raw: str, cwd: Path) -> Path:
    raw = raw.strip().lstrip("@")
    if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", raw):
        raw = "/mnt/" + raw[0].lower() + "/" + raw[3:].replace("\\", "/")
    raw = os.path.expandvars(os.path.expanduser(raw))
    path = Path(raw)
    return (cwd / path if not path.is_absolute() else path).resolve()


@functools.lru_cache(maxsize=16)
def _patterns(exts: frozenset):
    if not exts:
        return ()
    sfx = "|".join(re.escape(x[1:]) for x in sorted(exts, key=len, reverse=True))
    quoted = re.compile(rf'(?P<quote>["\'`])(?P<path>[^"\'`\r\n]{{1,1000}}?\.(?:{sfx}))(?P=quote)', re.I)
    unquoted = re.compile(rf'(?<![A-Za-z0-9_])(?P<path>@?(?:[A-Za-z]:[\\/]|~/|/|\.{{1,2}}[\\/])?[^\s"\'`<>|?;!()\[\]{{}}]{{1,1000}}?\.(?:{sfx}))(?=$|[\s,;!?\])}}])', re.I)
    return ((quoted, True), (unquoted, False))


def find_references(prompt: str, cwd: Path, config: Config | None = None):
    """Return [(start, end, resolved_path_or_None, raw)] without duplicating quoted/unquoted matches.

    Only extensions in config.detected (convert + block) are considered. Tokens
    that do not resolve to an existing file are returned too (path may be None);
    process_prompt() ignores them. Quoting is required for paths with spaces.
    """
    config = config or load_config()
    spans = []
    occupied = []
    for regex, is_quoted in _patterns(config.detected):
        for m in regex.finditer(prompt):
            a, b = m.span() if is_quoted else m.span("path")
            if any(not (b <= lo or a >= hi) for lo, hi in occupied):
                continue
            raw = m.group("path")
            try:
                path = resolve_candidate(raw, cwd)
            except (OSError, ValueError):
                path = None
            spans.append((a, b, path, raw))
            occupied.append((a, b))
    return sorted(spans, key=lambda item: item[0])


def convert_one(path: Path, config: Config | None = None) -> Path:
    config = config or load_config()
    if is_verified_sanitized(path, config.sanitize):
        return path
    if not path.is_file() or path.suffix.lower() not in config.convert:
        raise ValueError("Missing file or unsupported extension")
    if path.stat().st_size > MAX_SIZE:
        raise ValueError("Document exceeds 25 MiB limit")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()[:12]
    safe_stem = re.sub(r"[^A-Za-z0-9_-]", "_", path.stem)[:48] or "document"
    target = SANITIZED / f"{output_prefix(config.sanitize)}{safe_stem}_{digest}.md"
    if is_verified_sanitized(target, config.sanitize):
        return target

    if path.suffix.lower() in {".md", ".txt"}:
        source = data.decode("utf-8-sig", errors="replace")
    else:
        try:
            from markitdown import MarkItDown
        except ImportError as e:
            raise RuntimeError("Install MarkItDown: pip install 'markitdown[all]'") from e
        # convert_local() avoids permissive URI processing
        md = MarkItDown(enable_plugins=False)
        source = md.convert_local(str(path)).text_content
    if not source or not source.strip():
        raise ValueError("Document conversion yielded empty text (scanned PDF needs OCR)")
    if config.sanitize:
        cleaned, counts = sanitize(source, key=secret())
    else:
        cleaned, counts = source, {}
    atomic_write(target, cleaned)
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    meta = {"sha256": sha, "signature": _signature(target.name, sha, config.sanitize),
            "sanitizer_version": SANITIZER_VERSION, "sanitized": config.sanitize,
            "redactions": counts}
    atomic_write(target.with_suffix(".meta.json"), json.dumps(meta, ensure_ascii=False))
    return target


def replacement_with_spacing(prompt: str, start: int, end: int, path: Path) -> str:
    """Replace a path reference without gluing it to adjacent prompt text.

    For example, `Co je to?'D:\\tmp\\smlouva.docx'` should turn into
    `Co je to? "/home/.../sanitized_smlouva.md"`, not `Co je to?"..."`.
    """
    before = prompt[start - 1] if start else ""
    after = prompt[end] if end < len(prompt) else ""
    prefix = " " if before and not before.isspace() and before not in "([{“" else ""
    suffix = " " if after and (after.isalnum() or after in "@#") else ""
    return f'{prefix}"{path}"{suffix}'


def process_prompt(prompt: str, cwd: Path, config: Config | None = None,
                   config_error: str | None = None):
    """returns (found_file, rewritten_user_prompt, converted_paths, reason_if_blocked).

    No existing file -> allow unchanged (a mention of a file that does not exist
    on disk reveals nothing). Any existing file -> NEVER permit original prompt.

    Invalid configuration (config_error, or ConfigError raised while loading):
    detection falls back to the DEFAULT extension lists; prompts without such an
    existing file pass, prompts with one are blocked with a config error.
    """
    if config is None:
        try:
            config = load_config()
        except ConfigError as exc:
            config, config_error = default_config(), str(exc)
    elif config_error is not None:
        config = default_config()
    # ".md" is always detected so that a converted_ copy in the data folder can be
    # caught even when .md is not configured; other .md files are dropped below.
    probe = Config(config.convert, config.block | {".md"}, config.sanitize)
    refs = [r for r in find_references(prompt, cwd, probe)
            if r[2] is not None and r[2].is_file()
            and (r[2].suffix.lower() in config.detected or is_converted_copy(r[2]))]
    if not refs:
        # Image/attachment markers suggest content already expanded. Plain pasted
        # text (<pasted_content>) carries nothing the user could not have typed.
        if re.search(r"\[(?:Image|Attachment):", prompt, re.I):
            return True, "", [], "Inline attachment/paste not safely inspectable; blocked"
        return False, prompt, [], None
    if config_error is not None:
        return True, "", [], "Document gate config error: " + config_error
    if len(prompt) > 14000 or "<pasted_content" in prompt:
        return True, "", [], "Large/expanded prompt with attachment; blocked for manual review"
    output, converted = [], []
    position = 0
    for a, b, path, raw in refs:
        if config.sanitize and is_converted_copy(path):
            return True, "", [], ("Referenced file is an UNSANITIZED converted copy (sanitization is ON); "
                                  "reference the original document instead, it will be converted with sanitization")
        suffix = path.suffix.lower()
        if suffix in config.block or suffix not in config.convert:
            return True, "", [], "Unsupported file format: " + suffix
        if not is_verified_sanitized(path, config.sanitize):
            try:
                path = convert_one(path, config)
            except Exception as e:
                return True, "", [], "Conversion blocked: " + str(e)[:160]
            converted.append(str(path))
        output.append(prompt[position:a])
        output.append(replacement_with_spacing(prompt, a, b, path))
        position = b
    output.append(prompt[position:])
    if not converted:
        # Already verified copy -> ALLOW (no infinite rerouting).
        return False, prompt, [], None
    rewritten = "".join(output)
    if config.sanitize:
        rewritten, _ = sanitize(rewritten, key=secret())
    return True, rewritten, list(dict.fromkeys(converted)), None
