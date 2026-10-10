"""Format and lint edited Python files. Fail open.

ZCode PostToolUse hook (converted from .cursor/hooks/format_python.py).
Reads the hook JSON payload from stdin and extracts the edited file path
from either the top level or the nested tool_input object.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _read_payload() -> dict:
    raw = sys.stdin.buffer.read()
    text = raw.decode("utf-8-sig", errors="replace").lstrip("\ufeff").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _extract_file_path(payload: dict) -> str:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    for value in (
        payload.get("file_path"),
        tool_input.get("file_path"),
        payload.get("path"),
        tool_input.get("path"),
    ):
        if value:
            return str(value)
    return ""


def main() -> int:
    payload = _read_payload()
    file_path = _extract_file_path(payload)
    if not file_path or not file_path.lower().endswith(".py"):
        return 0

    path = Path(file_path)
    if not path.is_file():
        return 0

    ruff = shutil.which("ruff")
    if ruff is None:
        venv_ruff = Path(sys.executable).with_name("ruff.exe")
        ruff = str(venv_ruff) if venv_ruff.is_file() else None
    if ruff is None:
        return 0

    for args in ([ruff, "format", str(path)], [ruff, "check", str(path)]):
        try:
            subprocess.run(args, check=False, timeout=12)
        except (OSError, subprocess.TimeoutExpired):
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
