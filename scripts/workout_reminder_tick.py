from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_NOTIFICATION_URL = "http://127.0.0.1:3000/api/notifications/send"
TIMEOUT_SECONDS = 10


def error(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def post_notification(url: str) -> dict:
    payload = {
        "channel": os.environ.get("WORKOUT_NOTIFICATION_CHANNEL", "dingtalk"),
        "include_todo": os.environ.get("WORKOUT_NOTIFICATION_INCLUDE_TODO", "1") not in {"0", "false", "False"},
        "force": os.environ.get("WORKOUT_NOTIFICATION_FORCE", "0") in {"1", "true", "True"},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
            status = getattr(response, "status", response.getcode())
    except HTTPError as exc:
        reason = exc.read().decode("utf-8", "replace") or f"HTTP {exc.code}"
        raise RuntimeError(f"notification API request failed: {reason}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"notification API request failed: {reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"notification API request failed: {exc}") from exc

    if status < 200 or status >= 300:
        raise RuntimeError(f"notification API returned HTTP {status}")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"notification API returned invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise RuntimeError("notification API returned invalid JSON: expected object")
    return body


def run(notification_url: str) -> int:
    result = post_notification(notification_url)
    status = result.get("status", "unknown")
    plan_id = result.get("plan_id", "n/a")
    date = result.get("date", "today")
    print(f"NOTIFICATION: {date} plan_id={plan_id} status={status}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    notification_url = os.environ.get("WORKOUT_NOTIFICATION_URL", DEFAULT_NOTIFICATION_URL)
    try:
        return run(notification_url)
    except RuntimeError as exc:
        return error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
