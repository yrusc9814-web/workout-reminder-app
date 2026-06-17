from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API_URL = "http://127.0.0.1:3000/api/today"
DEFAULT_DINGTALK_REMINDER_URL = "http://127.0.0.1:3000/api/reminders/dingtalk/send"
DEFAULT_DINGTALK_TODO_URL = "http://127.0.0.1:3000/api/todos/dingtalk/create"
DEFAULT_LOG_PATH = Path("data/reminder-log.json")
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
        reason = exc.read().decode("utf-8", "replace") or f"HTTP {exc.code}"
        raise RuntimeError(f"API request failed: {reason}") from exc
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


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Accept": "application/json", "Content-Type": "application/json"}
    safe_headers = dict(request_headers)
    if url.endswith("/api/todos/dingtalk/create"):
        request_headers["x-acs-dingtalk-access-token"] = "***"
        safe_headers["x-acs-dingtalk-access-token"] = "***"
    request = Request(
        url,
        data=data,
        headers=request_headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", response.getcode())
            raw = response.read()
            response_headers = dict(response.headers.items())
    except HTTPError as exc:
        raw = exc.read()
        status = exc.code
        response_headers = dict(exc.headers.items()) if exc.headers else {}
    except URLError as exc:
        raise RuntimeError(
            json.dumps(
                {
                    "error_type": "network",
                    "raw_response": str(getattr(exc, "reason", exc)),
                    "step_index": 2,
                    "debug_trace": {
                        "request_url": url,
                        "request_headers": safe_headers,
                        "request_body": payload,
                        "response_status": None,
                        "response_body": "",
                        "request_id": None,
                    },
                },
                ensure_ascii=False,
            )
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            json.dumps(
                {
                    "error_type": "network",
                    "raw_response": str(exc),
                    "step_index": 2,
                    "debug_trace": {
                        "request_url": url,
                        "request_headers": safe_headers,
                        "request_body": payload,
                        "response_status": None,
                        "response_body": "",
                        "request_id": None,
                    },
                },
                ensure_ascii=False,
            )
        ) from exc

    decoded = raw.decode("utf-8", "replace") if raw else ""
    try:
        body = json.loads(decoded) if decoded else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            json.dumps(
                {
                    "error_type": "payload",
                    "raw_response": decoded,
                    "step_index": 2,
                    "debug_trace": {
                        "request_url": url,
                        "request_headers": safe_headers,
                        "request_body": payload,
                        "response_status": status,
                        "response_body": decoded,
                        "request_id": response_headers.get("x-acs-request-id") or response_headers.get("x-request-id"),
                    },
                    "error": f"DingTalk API returned invalid JSON: {exc}",
                },
                ensure_ascii=False,
            )
        ) from exc
    if not isinstance(body, dict):
        raise RuntimeError(
            json.dumps(
                {
                    "error_type": "payload",
                    "raw_response": decoded,
                    "step_index": 2,
                    "debug_trace": {
                        "request_url": url,
                        "request_headers": safe_headers,
                        "request_body": payload,
                        "response_status": status,
                        "response_body": decoded,
                        "request_id": response_headers.get("x-acs-request-id") or response_headers.get("x-request-id"),
                    },
                    "error": "DingTalk API returned invalid JSON: expected object",
                },
                ensure_ascii=False,
            )
        )
    body.setdefault("http_status", status)
    body.setdefault(
        "debug_trace",
        {
            "request_url": url,
            "request_headers": safe_headers,
            "request_body": payload,
            "response_status": status,
            "response_body": decoded,
            "request_id": response_headers.get("x-acs-request-id") or response_headers.get("x-request-id"),
        },
    )
    return body


def call_dingtalk_paths(plan_identifier: object, reminder_url: str, todo_url: str) -> tuple[dict, dict]:
    payload = {"plan_id": plan_identifier}
    reminder_result = post_json(reminder_url, payload)
    todo_result = post_json(todo_url, payload)
    return reminder_result, todo_result


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


def classify_todo_error(todo_result: dict) -> str:
    if todo_result.get("status") in {"created", "success", "not_configured"}:
        return ""
    if todo_result.get("error_type") and str(todo_result["error_type"]).lower() != "unknown":
        return str(todo_result["error_type"]).lower()
    trace = todo_result.get("debug_trace") or {}
    http_status = trace.get("response_status")
    raw_response = (
        todo_result.get("response")
        or todo_result.get("raw_response")
        or trace.get("response_body")
        or ""
    )
    if http_status is None and todo_result.get("status") == "failed":
        return "network"
    if isinstance(http_status, int) and http_status in {401, 403}:
        return "api"
    if isinstance(http_status, int) and http_status >= 400:
        return "api"
    if raw_response and todo_result.get("status") == "failed":
        return "payload"
    if todo_result.get("status") in {"failed", "todo_unavailable_due_to_permission"}:
        return "api"
    return "payload"


def classify_root_cause_category(todo_result: dict) -> str:
    error_type = classify_todo_error(todo_result)
    trace = todo_result.get("debug_trace") or {}
    response_status = trace.get("response_status")
    raw_response = (
        todo_result.get("response")
        or todo_result.get("raw_response")
        or trace.get("response_body")
        or ""
    )
    if error_type == "network":
        return "NETWORK_ERROR"
    if error_type == "payload":
        return "PAYLOAD_ERROR"
    if error_type == "api":
        return "API_ERROR"
    if isinstance(response_status, int) and response_status in {401, 403}:
        return "AUTH_ERROR"
    if raw_response:
        return "PAYLOAD_ERROR"
    return "API_ERROR"


def build_run_context(run_id: str, step_index: str, payload_snapshot: dict, todo_result: dict) -> dict:
    trace = todo_result.get("debug_trace") or {}
    request_headers = dict(trace.get("request_headers") or {})
    request_headers.setdefault("x-acs-dingtalk-access-token", "***")
    return {
        "run_id": run_id,
        "step_index": step_index,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload_snapshot": payload_snapshot,
        "request_headers": request_headers,
        "response_raw_body": trace.get("response_body") or todo_result.get("response") or todo_result.get("raw_response") or "",
    }


def run(api_url: str, log_path: Path, dingtalk_reminder_url: str, dingtalk_todo_url: str) -> int:
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

    run_id = os.environ.get("WORKOUT_RUN_ID") or uuid.uuid4().hex
    print(reminder_message(today, current_plan_id))
    reminder_result, todo_result = call_dingtalk_paths(
        current_plan_id, dingtalk_reminder_url, dingtalk_todo_url
    )
    todo_error_type = classify_todo_error(todo_result)
    payload_snapshot = {"plan_id": current_plan_id}
    log_entry = {
        "date": plan_date,
        "plan_id": current_plan_id,
        "title": today.get("title"),
        "reminded_at": datetime.now(timezone.utc).isoformat(),
        "api_url": api_url,
        "run_context": build_run_context(run_id, "todo", payload_snapshot, todo_result),
        "dingtalk_reminder_status": reminder_result.get("status"),
        "dingtalk_todo_status": todo_result.get("status"),
        "todo_error_type": todo_error_type,
        "root_cause_category": classify_root_cause_category(todo_result),
    }
    if todo_result.get("status") == "failed":
        log_entry["structured_error"] = {
            "error_type": todo_error_type,
            "raw_response": todo_result.get("response") or todo_result.get("raw_response") or "",
            "step_index": 2,
        }
        if todo_result.get("debug_trace"):
            log_entry["debug_trace"] = todo_result["debug_trace"]
    entries.append(log_entry)
    save_log(log_path, entries)
    return 0


def main() -> int:
    api_url = os.environ.get("WORKOUT_REMINDER_API_URL", DEFAULT_API_URL)
    log_path = Path(os.environ.get("WORKOUT_REMINDER_LOG_PATH", str(DEFAULT_LOG_PATH)))
    dingtalk_reminder_url = os.environ.get("WORKOUT_DINGTALK_REMINDER_URL", DEFAULT_DINGTALK_REMINDER_URL)
    dingtalk_todo_url = os.environ.get("WORKOUT_DINGTALK_TODO_URL", DEFAULT_DINGTALK_TODO_URL)
    try:
        return run(api_url, log_path, dingtalk_reminder_url, dingtalk_todo_url)
    except RuntimeError as exc:
        return error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
