"""Phase 8A — Mock Apple Calendar / Reminders adapter.

This adapter handles sync_target values starting with 'apple_'
(apple_calendar, apple_reminder). Uses MD5-based fake external IDs.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from .base import AdapterResult, SyncAdapter


class MockAppleAdapter(SyncAdapter):
    """Mock adapter for Apple Calendar/Reminders.

    Always succeeds. Generates deterministic external_id from sync_id + target.
    """

    @property
    def target_name(self) -> str:
        return "apple_calendar"

    def validate_config(self) -> tuple[bool, Optional[str]]:
        return (True, None)

    def push(self, task_data: dict, sync_state: dict) -> AdapterResult:
        raw = f"{sync_state['sync_id']}:{sync_state['sync_target']}"
        external_id = hashlib.md5(raw.encode()).hexdigest()[:12]
        return AdapterResult(
            success=True,
            external_id=external_id,
            sync_result="success",
        )

    def pull(self, external_id: str) -> Optional[dict]:
        return {
            "external_id": external_id,
            "source": "apple_calendar",
            "title": "[Mock] Synced Task",
            "status": "completed",
        }
