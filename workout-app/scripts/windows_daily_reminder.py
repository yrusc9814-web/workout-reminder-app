#!/usr/bin/env python3
"""Windows one-shot automation entry for Workout Reminder App.

This wrapper is intended for Windows Task Scheduler. It does not change workout
plan logic or DingTalk send logic. It only prepares runtime environment, ensures
that the local FastAPI app is reachable, calls the existing reminder tick script,
and writes a local JSONL run log with explicit success/failure status.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

APP_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = APP_DIR.parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3000
DEFAULT_BASE_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
DEFAULT_HEALTH_URL = f"{DEFAULT_BASE_URL}/api/health"
DEFAULT_TODAY_URL = f"{DEFAULT_BASE_URL}/api/today"
DEFAULT_REMINDER_URL = f"{DEFAULT_BASE_URL}/api/reminders/dingtalk/send"
DEFAULT_TODO_URL = f"{DEFAULT_BASE_URL}/api/todos/dingtalk/create"
DEFAULT_RUN_LOG = APP_DIR / "data" / "windows-reminder-runs.jsonl"
DEFAULT_TICK_LOG = APP_DIR / "data" / "windows-reminder-log.json"
DEFAULT_SECRET_FILE = REPO_DIR / "dingtalk-secrets.txt"
TIMEOUT_SECONDS = 15
SECRET_NAME_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
SENSITIVE_KEYS = {
    "DINGTALK_WEBHOOK_URL",
    "DINGTALK_TODO_CREATE_URL",
    "DINGTALK_ACCESS_TOKEN",
    "DINGTALK_CLIENT_ID",
    "DINGTALK_CLIENT_SECRET",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = SECRET_NAME_RE.match(stripped)
        if not match:
            continue
        key, raw_value = match.group(1), match.group(2).strip()
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {"'", '"'}:
            raw_value = raw_value[1:-1]
        values[key] = raw_value
    return values


def merge_secret_env(env: dict[str, str], secret_file: Path) -> dict[str, str]:
    values = parse_env_file(secret_file)
    for key in SENSITIVE_KEYS:
        value = values.get(key)
        if value and not env.get(key):
            env[key] = value
    return values


def request_json(url: str, payload: dict[str, str], timeout: int = TIMEOUT_SECONDS) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    body = json.loads(raw) if raw else {}
    if not isinstance(body, dict):
        raise RuntimeError("DingTalk token endpoint returned non-object JSON")
    return body


def refresh_access_token_if_possible(env: dict[str, str]) -> str:
    """Return token refresh status without logging secret values."""
    client_id = env.get("DINGTALK_CLIENT_ID")
    client_secret = env.get("DINGTALK_CLIENT_SECRET")
    if not client_id or not client_secret:
        return "skipped_missing_client_credentials"
    body = request_json(
        "https://api.dingtalk.com/v1.0/oauth2/accessToken",
        {"appKey": client_id, "appSecret": client_secret},
    )
    token = body.get("accessToken") or body.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("DingTalk token endpoint did not return accessToken")
    env["DINGTALK_ACCESS_TOKEN"] = token
    return "refreshed"


def http_get_json(url: str, timeout: int = TIMEOUT_SECONDS) -> tuple[int, dict | None, str]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", response.getcode())
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, None, raw
    except (URLError, OSError) as exc:
        return 0, None, str(exc)
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = None
    return status, parsed, raw


def health_ok(health_url: str) -> bool:
    status, body, _ = http_get_json(health_url, timeout=3)
    return status == 200 and isinstance(body, dict)


def wait_for_health(health_url: str, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if health_ok(health_url):
            return True
        time.sleep(1)
    return health_ok(health_url)


def start_app_if_needed(env: dict[str, str], host: str, port: int, health_url: str) -> tuple[subprocess.Popen | None, str]:
    if health_ok(health_url):
        return None, "already_running"
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
        cwd=str(APP_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if wait_for_health(health_url, seconds=30):
        return process, "started"
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
    raise RuntimeError(f"FastAPI app did not become healthy at {health_url}")


def run_tick(env: dict[str, str], tick_log: Path, today_url: str, reminder_url: str, todo_url: str) -> subprocess.CompletedProcess[str]:
    tick_env = env.copy()
    tick_env["WORKOUT_REMINDER_API_URL"] = today_url
    tick_env["WORKOUT_DINGTALK_REMINDER_URL"] = reminder_url
    tick_env["WORKOUT_DINGTALK_TODO_URL"] = todo_url
    tick_env["WORKOUT_REMINDER_LOG_PATH"] = str(tick_log)
    return subprocess.run(
        [sys.executable, "scripts/workout_reminder_tick.py"],
        cwd=str(APP_DIR),
        env=tick_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=90,
    )


def latest_tick_entry(tick_log: Path) -> dict | None:
    if not tick_log.exists():
        return None
    data = json.loads(tick_log.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        return None
    last = data[-1]
    return last if isinstance(last, dict) else None


def append_run_log(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def redact_text(text: str, env: dict[str, str] | None = None) -> str:
    # Do not print secret values accidentally if an upstream exception includes them.
    redacted = text
    values = list(os.environ.values())
    if env:
        values.extend(env.values())
    for value in values:
        if value and len(value) >= 16:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one Windows scheduled workout reminder tick.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--run-log", type=Path, default=DEFAULT_RUN_LOG)
    parser.add_argument("--tick-log", type=Path, default=DEFAULT_TICK_LOG)
    parser.add_argument("--secret-file", type=Path, default=DEFAULT_SECRET_FILE)
    parser.add_argument("--keep-started-app", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base_url = f"http://{args.host}:{args.port}"
    health_url = f"{base_url}/api/health"
    today_url = f"{base_url}/api/today"
    reminder_url = f"{base_url}/api/reminders/dingtalk/send"
    todo_url = f"{base_url}/api/todos/dingtalk/create"
    env = os.environ.copy()
    started_process: subprocess.Popen | None = None
    record: dict = {
        "started_at": utc_now(),
        "app_dir": str(APP_DIR),
        "health_url": health_url,
        "tick_log": str(args.tick_log),
        "secret_file_present": args.secret_file.exists(),
        "secrets": {},
        "status": "failed",
    }
    try:
        secret_values = merge_secret_env(env, args.secret_file)
        record["secrets"] = {key: "SET" if env.get(key) else "NOT_SET" for key in sorted(SENSITIVE_KEYS)}
        record["secret_sources"] = {
            key: str(args.secret_file) if secret_values.get(key) else "environment" if os.environ.get(key) else None
            for key in sorted(SENSITIVE_KEYS)
        }
        record["access_token_refresh"] = refresh_access_token_if_possible(env)
        started_process, app_status = start_app_if_needed(env, args.host, args.port, health_url)
        record["app_status"] = app_status
        record["health_http_200"] = health_ok(health_url)
        tick = run_tick(env, args.tick_log, today_url, reminder_url, todo_url)
        record["tick_returncode"] = tick.returncode
        record["tick_stdout"] = tick.stdout.strip()[-1000:]
        record["tick_stderr"] = redact_text(tick.stderr.strip()[-1000:], env)
        entry = latest_tick_entry(args.tick_log)
        record["latest_tick_entry"] = entry
        reminder_status = entry.get("dingtalk_reminder_status") if entry else None
        record["dingtalk_reminder_status"] = reminder_status
        record["mock_false_expected"] = True
        record["status"] = "success" if tick.returncode == 0 and reminder_status in {"sent", None} else "failed"
        record["finished_at"] = utc_now()
        append_run_log(args.run_log, record)
        print(json.dumps({
            "status": record["status"],
            "health_http_200": record["health_http_200"],
            "app_status": record.get("app_status"),
            "tick_returncode": record["tick_returncode"],
            "dingtalk_reminder_status": record.get("dingtalk_reminder_status"),
            "run_log": str(args.run_log),
            "tick_log": str(args.tick_log),
            "secrets": record["secrets"],
        }, ensure_ascii=False))
        return 0 if record["status"] == "success" else 1
    except Exception as exc:  # noqa: BLE001 - scheduled task needs explicit log on any failure.
        record["error"] = redact_text(str(exc), env)
        record["finished_at"] = utc_now()
        append_run_log(args.run_log, record)
        print(json.dumps({"status": "failed", "error": record["error"], "run_log": str(args.run_log)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if started_process is not None and not args.keep_started_app:
            started_process.terminate()
            try:
                started_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                started_process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
