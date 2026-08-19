from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WorkBuddyAdapter:
    """Reserved adapter for a future enterprise notification channel."""

    def send_reminder(self, plan_payload: dict) -> dict:
        return {
            "channel": "workbuddy",
            "enabled": False,
            "mock": True,
            "sent": False,
            "status": "not_configured",
            "payload": plan_payload,
        }

