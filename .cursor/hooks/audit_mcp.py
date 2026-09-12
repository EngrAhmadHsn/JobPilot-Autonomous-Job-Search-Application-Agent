"""Redacted JSONL audit of MCP tool calls. Fail open. Never log secrets."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SECRET_KEYS = (
    "api_key",
    "apikey",
    "token",
    "password",
    "authorization",
    "cookie",
    "secret",
    "credentials",
)
SECRET_KEY_RE = re.compile(
    r"(" + "|".join(re.escape(k) for k in SECRET_KEYS) + r")",
    re.IGNORECASE,
)
REDACTED = "[redacted]"


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


def _redact(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                out[key] = REDACTED
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        if SECRET_KEY_RE.search(value) and len(value) > 32:
            return REDACTED
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, (dict, list)):
            return _redact(parsed)
        return value
    return value


def _parse_maybe_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def main() -> int:
    payload = _read_payload()
    log_dir = Path(__file__).resolve().parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mcp_server_name": payload.get("mcp_server_name"),
            "tool_name": payload.get("tool_name"),
            "duration": payload.get("duration"),
            "has_result": payload.get("result_json") is not None,
            "tool_input": _redact(_parse_maybe_json(payload.get("tool_input"))),
            "result": _redact(_parse_maybe_json(payload.get("result_json"))),
        }
        log_path = log_dir / "mcp-audit.jsonl"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
