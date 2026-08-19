from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class DingTalkAdapter:
    webhook_url: Optional[str] = None
    todo_url: Optional[str] = None
    access_token: Optional[str] = None
    post_func: object | None = None

    @classmethod
    def from_env(cls) -> "DingTalkAdapter":
        return cls(
            webhook_url=os.environ.get("DINGTALK_WEBHOOK_URL"),
            todo_url=os.environ.get("DINGTALK_TODO_CREATE_URL"),
            access_token=os.environ.get("DINGTALK_ACCESS_TOKEN"),
        )

    def send_reminder(self, plan_payload: dict) -> dict:
        message_payload = self.build_reminder_payload(plan_payload)
        if not self.webhook_url:
            return {
                "channel": "dingtalk",
                "enabled": False,
                "mock": False,
                "sent": False,
                "status": "not_configured",
                "payload": {
                    "title": message_payload["title"],
                    "text": message_payload["text"],
                    "raw": message_payload,
                },
            }

        try:
            result = self._post(message_payload, self.webhook_url)
        except RuntimeError as exc:
            return {
                "channel": "dingtalk",
                "enabled": True,
                "mock": False,
                "sent": False,
                "status": "failed",
                "error": str(exc),
                "payload": {
                    "title": message_payload["title"],
                    "text": message_payload["text"],
                    "raw": message_payload,
                },
            }

        sent = 200 <= result["http_status"] < 300
        return {
            "channel": "dingtalk",
            "enabled": True,
            "mock": False,
            "sent": sent,
            "status": "sent" if sent else "failed",
            "http_status": result["http_status"],
            "response": result["response_body"],
            "payload": {
                "title": plan_payload["title"],
                "text": message_payload["text"],
                "raw": message_payload,
            },
        }

    def create_todo(self, plan_payload: dict) -> dict:
        todo_payload = self.build_todo_payload(plan_payload)
        if not self.todo_url or not self.access_token:
            return {
                "channel": "dingtalk_todo",
                "enabled": False,
                "created": False,
                "status": "not_configured",
                "payload": todo_payload,
            }

        headers = {"x-acs-dingtalk-access-token": self.access_token}
        try:
            result = self._post(todo_payload, self.todo_url, headers=headers)
        except RuntimeError as exc:
            try:
                error_info = json.loads(str(exc))
            except json.JSONDecodeError:
                error_info = self._network_error(str(exc), self.todo_url, todo_payload)
            return {
                "channel": "dingtalk_todo",
                "enabled": True,
                "created": False,
                "status": "failed",
                "error": error_info.get("error"),
                "error_type": error_info.get("error_type", "unknown"),
                "debug_trace": error_info.get("debug_trace"),
                "payload": todo_payload,
            }

        status_code = result["http_status"]
        body = result["response_body"]
        trace = {
            "request_url": result["request_url"],
            "request_headers": result["request_headers"],
            "request_body": result["request_body"],
            "response_status": status_code,
            "response_body": body,
            "request_id": result.get("request_id"),
        }
        created = 200 <= status_code < 300
        status = "created" if created else "failed"
        permission = None
        try:
            response_data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            response_data = {}
        error_code = str(response_data.get("code") or response_data.get("errcode") or "")
        error_message = str(response_data.get("message") or response_data.get("errmsg") or "")
        if (
            status_code == 403
            and "AccessTokenPermissionDenied" in error_code
            and "Todo.PersonalTodo.Write" in error_message
        ):
            status = "todo_unavailable_due_to_permission"
            permission = "Todo.PersonalTodo.Write"
        return {
            "channel": "dingtalk_todo",
            "enabled": True,
            "created": created,
            "status": status,
            "http_status": status_code,
            "response": body,
            "permission": permission,
            "error_type": "api" if not created else "unknown",
            "debug_trace": trace,
            "payload": todo_payload,
        }

    def _post(self, payload: dict, url: str, headers: Optional[dict] = None) -> dict:
        result = self.post_func(url, payload, headers=headers) if self.post_func else self._post_json(url, payload, headers=headers)
        if isinstance(result, tuple):
            status_code, body = result
            return {
                "http_status": status_code,
                "response_body": body,
                "request_url": url,
                "request_headers": {
                    key: ("***" if "token" in key.lower() or "authorization" in key.lower() else value)
                    for key, value in (headers or {}).items()
                },
                "request_body": payload,
                "response_headers": {},
                "request_id": None,
            }
        return result

    @staticmethod
    def build_training_text(plan_payload: dict) -> str:
        lines = [
            f"【待办】{plan_payload['title']}",
            f"训练日期：{plan_payload['date']}",
            f"主题：{plan_payload.get('theme') or ''}",
            "训练动作：",
        ]
        for item in plan_payload.get("items") or []:
            lines.append(f"- {item['name']}: {item.get('video_url') or ''}")
        if plan_payload.get("notes"):
            lines.append(f"备注：{plan_payload['notes']}")
        lines.append("完成提示：完成后在群里回复“已完成”。")
        return "\n".join(lines)

    @classmethod
    def build_reminder_payload(cls, plan_payload: dict) -> dict:
        text = cls.build_training_text(plan_payload)
        title = f"【待办】{plan_payload['title']}"
        return {
            "msgtype": "markdown",
            "title": title,
            "text": text,
            "markdown": {"title": title, "text": text},
        }

    @classmethod
    def build_todo_payload(cls, plan_payload: dict) -> dict:
        due_date = date.fromisoformat(str(plan_payload["date"])[:10]).isoformat()
        return {
            "subject": f"训练计划：{plan_payload['title']}",
            "description": cls.build_training_text(plan_payload),
            "sourceId": f"workout-plan-{plan_payload['id']}-{due_date}",
            "dueDate": due_date,
        }

    @staticmethod
    def _post_json(url: str, payload: dict, headers: Optional[dict] = None) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        safe_headers = {
            key: ("***" if "token" in key.lower() or "authorization" in key.lower() else value)
            for key, value in request_headers.items()
        }
        request = Request(url, data=data, headers=request_headers, method="POST")
        try:
            with urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8", "replace")
                return {
                    "http_status": response.status,
                    "response_body": body,
                    "request_url": url,
                    "request_headers": safe_headers,
                    "request_body": payload,
                    "response_headers": dict(response.headers.items()),
                    "request_id": response.headers.get("x-acs-request-id") or response.headers.get("x-request-id"),
                }
        except HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            response_headers = dict(exc.headers.items()) if exc.headers else {}
            return {
                "http_status": exc.code,
                "response_body": body,
                "request_url": url,
                "request_headers": safe_headers,
                "request_body": payload,
                "response_headers": response_headers,
                "request_id": response_headers.get("x-acs-request-id") or response_headers.get("x-request-id"),
            }
        except URLError as exc:
            raise RuntimeError(
                json.dumps(
                    {
                        "error": f"钉钉请求失败：{exc}",
                        "error_type": "network",
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

    @staticmethod
    def _network_error(error: str, url: str, payload: dict) -> dict:
        return {
            "error": error,
            "error_type": "network",
            "debug_trace": {
                "request_url": url,
                "request_headers": {"x-acs-dingtalk-access-token": "***"},
                "request_body": payload,
                "response_status": None,
                "response_body": "",
                "request_id": None,
            },
        }
