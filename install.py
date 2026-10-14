"""One-command Windows/WSL installer for Claude Document Gate.

Run with any supported Python (3.10--3.14): python install.py
It creates .venv, installs markitdown[all], validates the setup and registers
UserPromptSubmit with the *virtualenv* interpreter. No global pip installs.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"
REQUIREMENT = "markitdown[all]"
HOOK_TIMEOUT = 180


class InstallationError(RuntimeError):
    """Expected installation failure with an actionable error message."""


def venv_python(venv: Path = VENV_DIR) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def check_python_version() -> None:
    if not (3, 10) <= sys.version_info[:2] <= (3, 14):
        raise InstallationError(
            "MarkItDown requires Python 3.10–3.14. "
            f"Current version: {sys.version_info.major}.{sys.version_info.minor}. "
            "Install a supported Python and invoke install.py with it."
        )


def run_checked(command: list[str], *, description: str) -> None:
    print(f"\n→ {description}", flush=True)
    try:
        subprocess.run(command, cwd=PROJECT_DIR, check=True)
    except FileNotFoundError as exc:
        raise InstallationError(f"Cannot run {command[0]!r}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise InstallationError(
            f"{description} failed (exit code {exc.returncode}). "
            "Claude Code hook was NOT changed."
        ) from exc


def ensure_venv(*, target: Path = VENV_DIR) -> Path:
    py = venv_python(target)
    if py.is_file():
        print(f"→ Reusing virtual environment: {target}")
    else:
        if target.exists() and any(target.iterdir()):
            raise InstallationError(
                f"Virtual environment appears incomplete: {target}. "
                "Rename/delete that .venv directory and retry."
            )
        run_checked([sys.executable, "-m", "venv", str(target)],
                    description="Creating isolated Python virtual environment")
    if not py.is_file():
        raise InstallationError(f"Virtualenv interpreter not found after setup: {py}")
    # IMPORTANT: venv/bin/python often symlinks to system Python. .resolve()
    # would erase the venv path and break sys.prefix isolation.
    return py.absolute()


def verify_markitdown(py: Path) -> None:
    """Import smoke-test in the interpreter that will run the Claude hook."""
    try:
        check = subprocess.run(
            [str(py), "-c", "from markitdown import MarkItDown; MarkItDown(enable_plugins=False)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False,
        )
    except OSError as exc:
        raise InstallationError(f"Cannot launch virtual environment Python: {exc}") from exc
    if check.returncode != 0:
        raise InstallationError(
            "MarkItDown import validation failed in .venv. "
            "See pip output above. Claude hook was NOT changed."
        )


def install_dependencies(py: Path, *, upgrade: bool) -> None:
    # pip honors already-satisfied requirements, so this is safe to rerun and
    # checks all requested extras, not only import of the base distribution.
    cmd = [str(py), "-m", "pip", "--disable-pip-version-check", "install"]
    if upgrade:
        cmd.append("--upgrade")
    cmd.append(REQUIREMENT)
    run_checked(cmd, description=f"Ensuring {REQUIREMENT} is installed in .venv (network may be required)")
    verify_markitdown(py)


def command_for_hook(py: Path, script: Path) -> str:
    args = [str(py), str(script)]
    return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)


def is_our_hook(hook: object, script: Path) -> bool:
    if not isinstance(hook, dict):
        return False
    command = hook.get("command", "")
    if not isinstance(command, str):
        return False
    # Match the target by path; keep hooks owned by other products unchanged.
    normalized = command.replace("\\", "/").lower()
    path = str(script).replace("\\", "/").lower()
    return path in normalized or ("claude-document-gate" in normalized and "/hook.py" in normalized)


def write_json_atomic(settings: Path, config: dict) -> None:
    """Back up existing settings and atomically write the new JSON."""
    settings.parent.mkdir(parents=True, exist_ok=True)
    if settings.exists():
        backup = settings.with_name("settings.json.document-gate.bak")
        shutil.copy2(settings, backup)
        print(f"→ Backed up old settings: {backup}")
    payload = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    fd, filename = tempfile.mkstemp(prefix=".settings.document-gate-", suffix=".tmp", dir=settings.parent)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(filename, settings)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def default_settings_path() -> Path:
    # Respect Claude's config location when explicitly overridden.
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser()
    return config_dir / "settings.json"


def data_dir() -> Path:
    return Path(os.environ.get("DOCUMENT_GATE_HOME",
                               str(Path.home() / "local_app" / "claude_document_gate")))


def unregister_hook(*, settings: Path | None = None) -> str:
    """Remove only our hook from settings.json; keep all other hooks and keys."""
    if settings is None:
        settings = default_settings_path()
    if not settings.exists():
        result = "No settings.json found; nothing to remove"
        print(f"→ {result}: {settings}")
        return result
    try:
        config = json.loads(settings.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallationError(f"Cannot read/parse {settings}; left it unchanged: {exc}") from exc
    if not isinstance(config, dict):
        raise InstallationError(f"Expected JSON object in {settings}; left it unchanged")
    hooks = config.get("hooks")
    entries = hooks.get("UserPromptSubmit") if isinstance(hooks, dict) else None
    if not isinstance(entries, list):
        result = "Claude Document Gate hook is not registered"
        print(f"→ {result}: {settings}")
        return result
    script = PROJECT_DIR / "hook.py"
    removed = 0
    kept_groups = []
    for group in entries:
        group_hooks = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(group_hooks, list):
            kept_groups.append(group)
            continue
        remaining = [h for h in group_hooks if not is_our_hook(h, script)]
        removed += len(group_hooks) - len(remaining)
        if remaining:
            group["hooks"] = remaining
            kept_groups.append(group)
        elif len(remaining) == len(group_hooks):
            kept_groups.append(group)
        # else: group became empty because of us -> drop it
    if not removed:
        result = "Claude Document Gate hook is not registered"
        print(f"→ {result}: {settings}")
        return result
    if kept_groups:
        hooks["UserPromptSubmit"] = kept_groups
    else:
        del hooks["UserPromptSubmit"]
        if not hooks:
            del config["hooks"]
    write_json_atomic(settings, config)
    result = f"Removed {removed} Claude Document Gate hook(s)"
    print(f"→ {result}: {settings}")
    return result


def register_hook(py: Path, *, settings: Path | None = None) -> str:
    if settings is None:
        settings = default_settings_path()
    script = PROJECT_DIR / "hook.py"
    command = command_for_hook(py, script)
    if settings.exists():
        try:
            config = json.loads(settings.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallationError(f"Cannot read/parse {settings}; left it unchanged: {exc}") from exc
        if not isinstance(config, dict):
            raise InstallationError(f"Expected JSON object in {settings}; left it unchanged")
    else:
        config = {}
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallationError("'hooks' in settings.json must be an object. Left it unchanged.")
    entries = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(entries, list):
        raise InstallationError("'hooks.UserPromptSubmit' must be a list. Left it unchanged.")
    desired = {"type": "command", "command": command, "timeout": HOOK_TIMEOUT}
    matches = [h for group in entries if isinstance(group, dict)
               for h in group.get("hooks", []) if is_our_hook(h, script)]
    if matches:
        for hook in matches:
            hook.update(desired)
        result = "Updated existing Claude Document Gate hook to use .venv"
    else:
        entries.append({"hooks": [desired]})
        result = "Registered new UserPromptSubmit hook"
    if not settings.exists() or json.loads(settings.read_text(encoding="utf-8-sig")) != config:
        write_json_atomic(settings, config)
    print(f"→ {result}: {settings}")
    return result


def ensure_user_config() -> None:
    """Create config.json from config.default.json only when it does not exist."""
    target = PROJECT_DIR / "config.json"
    source = PROJECT_DIR / "config.default.json"
    if target.exists():
        print(f"→ Keeping existing configuration: {target}")
    elif source.is_file():
        shutil.copyfile(source, target)
        print(f"→ Created configuration from defaults: {target}")
    else:
        print(f"→ config.default.json not found; skipping {target.name} creation")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upgrade", action="store_true",
                        help="Upgrade MarkItDown and its dependencies to the latest compatible versions")
    parser.add_argument("--skip-tests", action="store_true", help="Skip local sanity tests")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove the hook from Claude Code settings.json (keeps .venv and data)")
    parser.add_argument("--allow-macos", action="store_true",
                        help="Proceed on macOS, which is experimental and not officially supported")
    args = parser.parse_args(argv)
    if sys.platform == "darwin" and not args.allow_macos and not args.uninstall:
        print("WARNING: macOS is experimental and not officially supported yet "
              "(the session inbox transport has only been tested on Linux/WSL and Windows).\n"
              "Re-run with --allow-macos if you want to continue anyway.", file=sys.stderr)
        return 2
    if args.uninstall:
        try:
            unregister_hook()
        except (InstallationError, OSError) as exc:
            print(f"\nERROR: {exc}", file=sys.stderr)
            return 1
        print("\nNot deleted (remove manually if you no longer need them):")
        print(f"  virtual environment: {VENV_DIR}")
        print(f"  sanitized cache and verification key: {data_dir()}")
        print("Restart Claude Code for the change to take effect.")
        return 0
    try:
        check_python_version()
        py = ensure_venv()
        install_dependencies(py, upgrade=args.upgrade)
        if not args.skip_tests:
            run_checked([str(py), "-m", "unittest", "discover", "-s", "tests", "-v"],
                        description="Running local smoke tests before registering hook")
        ensure_user_config()
        register_hook(py)
    except (InstallationError, OSError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    print("\n✓ Installed. Restart Claude Code. Keep this project folder at the same path.")
    print("Note: message delivery into Claude Code session still depends on an unofficial protocol.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
