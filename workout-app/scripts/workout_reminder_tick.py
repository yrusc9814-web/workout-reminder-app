#!/usr/bin/env python3
"""Local one-shot workout reminder tick.

Fetches today's workout plan from the app API and records a local reminder log so
scheduled invocations do not remind more than once for the same date + plan.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_API_URL = "http://127.0.0.1:3000/api/today"
DEFAULT_LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "reminder-log.json"
TIMEOUT_SECONDS = 10


def error(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def fetch_today(api_url: str) -> dict:
    request = Request(api_url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", response.getcode())
            if status < 200 or status >= 300:
                raise RuntimeError(f"API returned HTTP {status}")
            raw = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"API returned HTTP {exc.code}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"API request failed: {reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"API request failed: {exc}") from exc

    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"API returned invalid JSON: {exc}") from exc

    if not isinstance(body, dict):
        raise RuntimeError("API returned invalid JSON: expected object")
    return body


def load_log(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    try:
        raw = log_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except OSError as exc:
        raise RuntimeError(f"cannot read reminder log {log_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"reminder log is invalid JSON {log_path}: {exc}") from exc

    if not isinstance(data, list):
        raise RuntimeError(f"reminder log must be a JSON array: {log_path}")
    for item in data:
        if not isinstance(item, dict):
            raise RuntimeError(f"reminder log must contain JSON objects: {log_path}")
    return data


def save_log(log_path: Path, entries: list[dict]) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot write reminder log {log_path}: {exc}") from exc


def plan_id(today: dict) -> object:
    return today.get("plan_id", today.get("id"))


def is_training_day(today: dict) -> bool:
    if today.get("is_training") is True:
        return True
    if str(today.get("type", "")).lower() == "training":
        return True
    return False


def already_reminded(entries: list[dict], plan_date: str, plan_identifier: object) -> bool:
    return any(entry.get("date") == plan_date and entry.get("plan_id") == plan_identifier for entry in entries)


def reminder_message(today: dict, plan_identifier: object) -> str:
    title = today.get("title") or "今日训练"
    theme = today.get("theme")
    if theme:
        return f"REMINDER: {today['date']} 训练日 - {title}（{theme}，plan_id={plan_identifier}）"
    return f"REMINDER: {today['date']} 训练日 - {title}（plan_id={plan_identifier}）"


def run(api_url: str, log_path: Path) -> int:
    today = fetch_today(api_url)
    if not is_training_day(today):
        plan_date = today.get("date", "today")
        print(f"No training plan for {plan_date}; no reminder sent.")
        return 0

    current_plan_id = plan_id(today)
    plan_date = today.get("date")
    if current_plan_id is None:
        raise RuntimeError("API response missing plan id for training day")
    if not isinstance(plan_date, str) or not plan_date:
        raise RuntimeError("API response missing date for training day")

    entries = load_log(log_path)
    if already_reminded(entries, plan_date, current_plan_id):
        print(f"Already reminded for {plan_date} plan_id={current_plan_id}; no duplicate reminder.")
        return 0

    print(reminder_message(today, current_plan_id))
    entries.append(
        {
            "date": plan_date,
            "plan_id": current_plan_id,
            "title": today.get("title"),
            "reminded_at": datetime.now(timezone.utc).isoformat(),
            "api_url": api_url,
        }
    )
    save_log(log_path, entries)
    return 0


def main() -> int:
    api_url = os.environ.get("WORKOUT_REMINDER_API_URL", DEFAULT_API_URL)
    log_path = Path(os.environ.get("WORKOUT_REMINDER_LOG_PATH", str(DEFAULT_LOG_PATH)))
    try:
        return run(api_url, log_path)
    except RuntimeError as exc:
        return error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
