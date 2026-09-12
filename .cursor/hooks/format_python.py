"""Format and lint edited Python files. Fail open."""

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


def main() -> int:
    payload = _read_payload()
    file_path = payload.get("file_path") or payload.get("path") or ""
    if not file_path or not str(file_path).lower().endswith(".py"):
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
