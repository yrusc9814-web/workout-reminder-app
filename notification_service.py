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

        successful = set() if request.force else self._successful_channels(plan)
        reminder_channel = "workbuddy" if request.channel == "workbuddy" else "dingtalk_reminder"
        required = {reminder_channel}
        if request.channel != "workbuddy" and request.include_todo:
            required.add("dingtalk_todo")
        if required <= successful:
            return {
                "status": "duplicate_skipped",
                "sent": False,
                "plan_id": plan.id,
                "date": plan.plan_date.isoformat(),
            }

        plan_payload = self.plan_payload(plan)
        if reminder_channel in successful:
            reminder = {"channel": request.channel, "status": "duplicate_skipped", "sent": True, "previously_sent": True}
        else:
            reminder = (self.workbuddy if request.channel == "workbuddy" else self.dingtalk).send_reminder(plan_payload)
            self._record(plan, request, reminder_channel, reminder)

        todo = None
        if "dingtalk_todo" in required:
            if "dingtalk_todo" in successful:
                todo = {"channel": "dingtalk_todo", "status": "duplicate_skipped", "created": True, "previously_sent": True}
            else:
                todo = self.dingtalk.create_todo(plan_payload)
                self._record(plan, request, "dingtalk_todo", todo)

        status = self._combined_status(reminder, todo)
        return {
            "status": status,
            "sent": status == "sent",
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
        return result.get("reminder", result)

    def create_dingtalk_todo(self, plan_id: int) -> dict:
        plan = self.db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
        if plan is None:
            return {"status": "not_found", "created": False, "detail": "未找到训练计划"}
        result = self.dingtalk.create_todo(self.plan_payload(plan))
        self._record(plan, NotificationRequest(plan_id=plan_id), "dingtalk_todo", result)
        return result

    def _today_plan(self) -> WorkoutPlan | None:
        return self.db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == date.today()).first()

    def _successful_channels(self, plan: WorkoutPlan) -> set[str]:
        rows = (
            self.db.query(Reminder)
            .filter(
                Reminder.plan_id == plan.id,
                Reminder.reminder_date == plan.plan_date,
                Reminder.is_active == True,
            )
            .all()
        )
        # Historical rows have no channel information; retain their original
        # whole-plan meaning rather than guessing which deliveries succeeded.
        if any(row.delivery_channel is None for row in rows):
            return {"dingtalk_reminder", "dingtalk_todo", "workbuddy"}
        return {row.delivery_channel for row in rows}

    def _record(self, plan: WorkoutPlan, request: NotificationRequest, channel: str, result: dict) -> None:
        """Persist each confirmed success before attempting the next delivery."""
        success_key = "created" if channel == "dingtalk_todo" else "sent"
        if result.get(success_key) is not True:
            return
        row = Reminder(
            plan_id=plan.id,
            reminder_date=plan.plan_date,
            delivery_channel=channel,
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
        successes = [reminder.get("sent") is True]
        results = [reminder]
        if todo is not None:
            successes.append(todo.get("created") is True)
            results.append(todo)
        if all(successes):
            return "sent"
        if any(successes):
            return "partial_success"
        if all(result.get("status") == "not_configured" for result in results):
            return "not_configured"
        return "failed"

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

