from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from adapters.dingtalk import DingTalkAdapter
from adapters.workbuddy import WorkBuddyAdapter
from database import Reminder, WorkoutPlan


@dataclass
class NotificationRequest:
    plan_id: Optional[int] = None
    channel: str = "dingtalk"
    title: Optional[str] = None
    message: Optional[str] = None
    include_todo: bool = True
    force: bool = False


class NotificationService:
    def __init__(
        self,
        db: Session,
        dingtalk_adapter: DingTalkAdapter | None = None,
        workbuddy_adapter: WorkBuddyAdapter | None = None,
    ) -> None:
        self.db = db
        self.dingtalk = dingtalk_adapter or DingTalkAdapter.from_env()
        self.workbuddy = workbuddy_adapter or WorkBuddyAdapter()

    def send(self, request: NotificationRequest) -> dict:
        if request.plan_id is None:
            plan = self._today_plan()
            if plan is None:
                return self._mock_result(request, "no_plan")
        else:
            plan = self.db.query(WorkoutPlan).filter(WorkoutPlan.id == request.plan_id).first()
            if plan is None:
                return {"status": "not_found", "sent": False, "detail": "未找到训练计划"}

        if not plan.is_training_day:
            return {
                "status": "no_training_plan",
                "sent": False,
                "plan_id": plan.id,
                "date": plan.plan_date.isoformat(),
            }

        if not request.force and self._already_sent(plan):
            return {
                "status": "duplicate_skipped",
                "sent": False,
                "plan_id": plan.id,
                "date": plan.plan_date.isoformat(),
            }

        plan_payload = self.plan_payload(plan)
        if request.channel == "workbuddy":
            reminder = self.workbuddy.send_reminder(plan_payload)
            todo = None
        else:
            reminder = self.dingtalk.send_reminder(plan_payload)
            todo = self.dingtalk.create_todo(plan_payload) if request.include_todo else None

        self._record(plan, request, reminder)
        return {
            "status": self._combined_status(reminder, todo),
            "sent": reminder.get("sent") is True,
            "plan_id": plan.id,
            "date": plan.plan_date.isoformat(),
            "channel": request.channel,
            "reminder": reminder,
            "todo": todo,
        }

    def send_dingtalk_reminder(self, plan_id: Optional[int], title: Optional[str], message: Optional[str]) -> dict:
        if plan_id is None:
            return self._mock_result(NotificationRequest(title=title, message=message), "not_sent")
        result = self.send(NotificationRequest(plan_id=plan_id, channel="dingtalk", include_todo=False, force=True))
        return result["reminder"]

    def create_dingtalk_todo(self, plan_id: int) -> dict:
        plan = self.db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
        if plan is None:
            return {"status": "not_found", "created": False, "detail": "未找到训练计划"}
        return self.dingtalk.create_todo(self.plan_payload(plan))

    def _today_plan(self) -> WorkoutPlan | None:
        return self.db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == date.today()).first()

    def _already_sent(self, plan: WorkoutPlan) -> bool:
        return (
            self.db.query(Reminder)
            .filter(
                Reminder.plan_id == plan.id,
                Reminder.reminder_date == plan.plan_date,
                Reminder.is_active == True,
            )
            .first()
            is not None
        )

    def _record(self, plan: WorkoutPlan, request: NotificationRequest, result: dict) -> None:
        """Only record a successful delivery. Failed attempts leave no active record so the
        system will retry on next request instead of incorrectly skipping as duplicate."""
        if not result.get("sent"):
            return
        row = Reminder(
            plan_id=plan.id,
            reminder_date=plan.plan_date,
            message=request.message or result.get("status") or "notification_sent",
            is_active=True,
        )
        self.db.add(row)
        self.db.commit()

    @staticmethod
    def plan_payload(plan: WorkoutPlan) -> dict:
        return {
            "id": plan.id,
            "plan_id": plan.id,
            "date": plan.plan_date.isoformat(),
            "title": plan.title,
            "theme": plan.focus,
            "notes": plan.notes,
            "type": "training" if plan.is_training_day else "rest",
            "is_training": bool(plan.is_training_day),
            "items": [
                {
                    "name": item.name,
                    "description": item.description,
                    "sets": item.sets,
                    "reps": item.reps,
                    "duration_seconds": item.duration_seconds,
                    "video_url": item.video_url,
                }
                for item in plan.exercises
            ],
        }

    @staticmethod
    def _combined_status(reminder: dict, todo: dict | None) -> str:
        if todo and todo.get("status") in {"failed", "todo_unavailable_due_to_permission"}:
            return todo["status"]
        return str(reminder.get("status") or "unknown")

    @staticmethod
    def _mock_result(request: NotificationRequest, status: str) -> dict:
        return {
            "channel": request.channel,
            "enabled": False,
            "mock": True,
            "title": request.title,
            "message": request.message,
            "status": status,
            "sent": False,
        }

