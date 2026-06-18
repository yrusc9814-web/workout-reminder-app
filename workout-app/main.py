import re
from calendar import monthrange
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import (
    Base,
    Exercise,
    Reminder,
    SessionRecord,
    Setting,
    Template,
    WorkoutExercise,
    WorkoutLog,
    WorkoutPlan,
    WorkoutSession,
    engine,
    get_db,
)
from seed import seed_database


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_database()
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
@app.head("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


class LogPayload(BaseModel):
    plan_id: int
    notes: Optional[str] = None


class SettingPayload(BaseModel):
    key: str = Field(min_length=1)
    value: str


class ReminderPayload(BaseModel):
    plan_id: Optional[int] = None
    title: Optional[str] = None
    message: Optional[str] = None


class DingTalkPayload(BaseModel):
    plan_id: int


def as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_month_token(month: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="月份格式必须是 YYYY-MM") from exc
    return parsed.year, parsed.month


def resolve_year_month(year: Optional[int], month: Optional[str]) -> tuple[int, int]:
    if month is None:
        raise HTTPException(status_code=422, detail="必须提供月份")

    if "-" in month:
        if year is not None:
            raise HTTPException(status_code=422, detail="请使用 year+month，或只使用 month=YYYY-MM")
        return parse_month_token(month)

    try:
        month_num = int(month)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="月份必须是 1-12 或 YYYY-MM") from exc

    if not 1 <= month_num <= 12:
        raise HTTPException(status_code=422, detail="月份必须在 1 到 12 之间")

    if year is None:
        raise HTTPException(status_code=422, detail="月份为数字时必须提供年份")

    return year, month_num


def plan_item(plan: Optional[WorkoutPlan], day: date) -> dict:
    if not plan:
        return {
            "date": day.isoformat(),
            "id": None,
            "title": None,
            "theme": None,
            "notes": None,
            "items": [],
            "type": "rest",
            "is_training": False,
        }

    is_training = bool(plan.is_training_day)
    items = sorted(getattr(plan, "exercises", []) or [], key=lambda x: x.sort_order or 0)
    return {
        "date": as_date(plan.plan_date).isoformat(),
        "id": plan.id,
        "title": plan.title,
        "theme": plan.focus,
        "notes": plan.notes,
        "type": "training" if is_training else "rest",
        "is_training": is_training,
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "sets": item.sets,
                "reps": item.reps,
                "duration_seconds": item.duration_seconds,
                "instructions": item.description,
                "video_url": item.video_url,
                "sort_order": item.sort_order,
            }
            for item in items
        ],
    }


def range_rows(db: Session, start: date, end: date) -> dict:
    rows = (
        db.query(WorkoutPlan)
        .filter(WorkoutPlan.plan_date >= start, WorkoutPlan.plan_date <= end)
        .order_by(WorkoutPlan.plan_date.asc())
        .all()
    )
    return {as_date(row.plan_date): row for row in rows}



def get_plan_or_404(db: Session, plan_id: int) -> WorkoutPlan:
    plan = db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="未找到训练计划")
    return plan


def plan_payload(plan: WorkoutPlan) -> dict:
    return plan_item(plan, as_date(plan.plan_date))


def build_training_text(plan: WorkoutPlan) -> str:
    payload = plan_payload(plan)
    lines = [
        f"【待办】{payload['title']}",
        f"训练日期：{payload['date']}",
        f"主题：{payload['theme'] or ''}",
        "训练动作：",
    ]
    for item in payload["items"]:
        lines.append(f"- {item['name']}: {item['video_url']}")
    if payload.get("notes"):
        lines.append(f"备注：{payload['notes']}")
    lines.append("完成提示：完成后在群里回复“已完成”。")
    return "\n".join(lines)


def build_dingtalk_reminder_payload(plan: WorkoutPlan) -> dict:
    text = build_training_text(plan)
    title = f"【待办】{plan.title}"
    return {
        "msgtype": "markdown",
        "title": title,
        "text": text,
        "markdown": {"title": title, "text": text},
    }


def build_dingtalk_todo_payload(plan: WorkoutPlan) -> dict:
    return {
        "subject": f"训练计划：{plan.title}",
        "description": build_training_text(plan),
        "sourceId": f"workout-plan-{plan.id}-{as_date(plan.plan_date).isoformat()}",
        "dueDate": as_date(plan.plan_date).isoformat(),
    }


def post_json(url: str, payload: dict, headers: Optional[dict] = None) -> dict:
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
            response_headers = dict(response.headers.items())
            request_id = response.headers.get("x-acs-request-id") or response.headers.get("x-request-id")
            return {
                "http_status": response.status,
                "response_body": body,
                "request_url": url,
                "request_headers": safe_headers,
                "request_body": payload,
                "response_headers": response_headers,
                "request_id": request_id,
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        response_headers = dict(exc.headers.items()) if exc.headers else {}
        request_id = None
        if exc.headers:
            request_id = exc.headers.get("x-acs-request-id") or exc.headers.get("x-request-id")
        return {
            "http_status": exc.code,
            "response_body": body,
            "request_url": url,
            "request_headers": safe_headers,
            "request_body": payload,
            "response_headers": response_headers,
            "request_id": request_id,
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

def log_item(row: WorkoutLog) -> dict:
    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "action": row.action,
        "status": row.status,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def write_log(db: Session, plan_id: int, state: str, notes: Optional[str]) -> dict:
    plan = db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="未找到训练计划")

    row = WorkoutLog(plan_id=plan_id, action=state, status=state, notes=notes)
    db.add(row)
    db.commit()
    db.refresh(row)
    return log_item(row)


@app.get("/session.html", include_in_schema=False)
@app.head("/session.html", include_in_schema=False)
def session_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "session.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/today")
@app.get("/api/plans/today")
def today(db: Session = Depends(get_db)) -> dict:
    day = date.today()
    plan = db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == day).first()
    return plan_item(plan, day)


@app.get("/api/plans/month")
def month_view(
    year: Optional[int] = Query(None, ge=1),
    month: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    year_value, month_value = resolve_year_month(year, month)
    start = date(year_value, month_value, 1)
    end = date(year_value, month_value, monthrange(year_value, month_value)[1])
    rows = range_rows(db, start, end)
    days = []
    current = start
    while current <= end:
        days.append(plan_item(rows.get(current), current))
        current += timedelta(days=1)
    return {"year": year_value, "month": month_value, "days": days}


@app.get("/api/plans/month/summary")
def month_summary(month: str = Query(...), db: Session = Depends(get_db)) -> dict:
    year, month_num = parse_month_token(month)
    return month_view(year=year, month=str(month_num), db=db)


@app.get("/api/plans/week")
def week(date: str = Query(...), db: Session = Depends(get_db)) -> dict:
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式必须是 YYYY-MM-DD")

    start = target - timedelta(days=target.weekday())
    end = start + timedelta(days=6)
    rows = range_rows(db, start, end)
    days = []
    current = start
    while current <= end:
        days.append(plan_item(rows.get(current), current))
        current += timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat(), "days": days}


@app.post("/api/logs/complete")
def complete(payload: LogPayload, db: Session = Depends(get_db)) -> dict:
    return write_log(db, payload.plan_id, "completed", payload.notes)


@app.post("/api/logs/skip")
def skip(payload: LogPayload, db: Session = Depends(get_db)) -> dict:
    return write_log(db, payload.plan_id, "skipped", payload.notes)


@app.post("/api/logs/postpone")
def postpone(payload: LogPayload, db: Session = Depends(get_db)) -> dict:
    return write_log(db, payload.plan_id, "postponed", payload.notes)


@app.get("/api/logs")
def logs(db: Session = Depends(get_db)) -> dict:
    rows = db.query(WorkoutLog).order_by(WorkoutLog.created_at.desc()).all()
    return {"logs": [log_item(row) for row in rows]}


@app.get("/api/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    total = db.query(WorkoutPlan).count()
    active = db.query(WorkoutPlan).filter(WorkoutPlan.is_training_day == True).count()
    completed = db.query(WorkoutLog).filter(WorkoutLog.status == "completed").count()
    skipped = db.query(WorkoutLog).filter(WorkoutLog.status == "skipped").count()
    postponed = db.query(WorkoutLog).filter(WorkoutLog.status == "postponed").count()
    return {
        "plans": total,
        "training_days": active,
        "rest_days": total - active,
        "completed": completed,
        "skipped": skipped,
        "postponed": postponed,
    }


@app.get("/api/stats/month")
def stats_month(month: str = Query(...), db: Session = Depends(get_db)) -> dict:
    year, month_num = parse_month_token(month)
    start = date(year, month_num, 1)
    end = date(year, month_num, monthrange(year, month_num)[1])
    plans_query = db.query(WorkoutPlan).filter(
        WorkoutPlan.plan_date >= start,
        WorkoutPlan.plan_date <= end,
    )
    logs_query = db.query(WorkoutLog).filter(
        WorkoutLog.log_date >= start,
        WorkoutLog.log_date <= end,
    )
    total = plans_query.count()
    training_days = plans_query.filter(WorkoutPlan.is_training_day == True).count()
    completed = logs_query.filter(WorkoutLog.status == "completed").count()
    skipped = logs_query.filter(WorkoutLog.status == "skipped").count()
    postponed = logs_query.filter(WorkoutLog.status == "postponed").count()
    return {
        "month": month,
        "plans": total,
        "training_days": training_days,
        "rest_days": total - training_days,
        "completed": completed,
        "skipped": skipped,
        "postponed": postponed,
    }


@app.get("/api/calendar")
def calendar_view(
    year: Optional[int] = Query(None, ge=1),
    month: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    if month is None:
        today_date = date.today()
        year_value = year or today_date.year
        month_value = today_date.month
    else:
        year_value, month_value = resolve_year_month(year, month)

    start = date(year_value, month_value, 1)
    end = date(year_value, month_value, monthrange(year_value, month_value)[1])
    rows = range_rows(db, start, end)
    days = []
    current = start
    while current <= end:
        plan = rows.get(current)
        days.append(
            {
                "date": current.isoformat(),
                "plan_id": plan.id if plan else None,
                "title": plan.title if plan else None,
                "type": "training" if plan and plan.is_training_day else "rest",
                "is_training": bool(plan.is_training_day) if plan else False,
            }
        )
        current += timedelta(days=1)
    return {"year": year_value, "month": month_value, "days": days}


@app.get("/api/calendar/month")
def calendar_month(month: str = Query(...), db: Session = Depends(get_db)) -> dict:
    year, month_num = parse_month_token(month)
    return calendar_view(year=year, month=str(month_num), db=db)


@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    rows = db.query(Setting).order_by(Setting.key.asc()).all()
    reminders = db.query(Reminder).order_by(Reminder.reminder_date.asc()).all()
    return {
        "settings": {row.key: row.value for row in rows},
        "reminders": [
            {
                "id": row.id,
                "message": row.message,
                "reminder_date": row.reminder_date.isoformat(),
                "enabled": bool(row.is_active),
            }
            for row in reminders
        ],
    }


@app.post("/api/settings")
def set_setting(payload: SettingPayload, db: Session = Depends(get_db)) -> dict:
    row = db.query(Setting).filter(Setting.key == payload.key).first()
    if row:
        row.value = payload.value
    else:
        row = Setting(key=payload.key, value=payload.value)
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"key": row.key, "value": row.value}


@app.post("/api/reminders/test")
def test_reminder(payload: ReminderPayload) -> dict:
    return {
        "enabled": False,
        "mock": True,
        "title": payload.title,
        "message": payload.message,
        "status": "not_sent",
    }


@app.post("/api/reminders/wechat/send")
def send_wechat_reminder(payload: ReminderPayload) -> dict:
    return {
        "channel": "wechat",
        "enabled": False,
        "mock": True,
        "title": payload.title,
        "message": payload.message,
        "status": "not_sent",
    }


@app.post("/api/reminders/dingtalk/send")
def send_dingtalk_reminder(payload: ReminderPayload, db: Session = Depends(get_db)) -> dict:
    if payload.plan_id is None:
        return {
            "channel": "dingtalk",
            "enabled": False,
            "mock": True,
            "title": payload.title,
            "message": payload.message,
            "status": "not_sent",
        }

    plan = get_plan_or_404(db, payload.plan_id)
    message_payload = build_dingtalk_reminder_payload(plan)
    webhook_url = os.environ.get("DINGTALK_WEBHOOK_URL")
    if not webhook_url:
        return {
            "channel": "dingtalk",
            "enabled": False,
            "mock": False,
            "sent": False,
            "status": "not_configured",
            "payload": {"title": message_payload["title"], "text": message_payload["text"], "raw": message_payload},
        }

    try:
        status_code, body = post_json(webhook_url, message_payload)
    except RuntimeError as exc:
        return {
            "channel": "dingtalk",
            "enabled": True,
            "mock": False,
            "sent": False,
            "status": "failed",
            "error": str(exc),
            "payload": {"title": message_payload["title"], "text": message_payload["text"], "raw": message_payload},
        }

    sent = 200 <= status_code < 300
    return {
        "channel": "dingtalk",
        "enabled": True,
        "mock": False,
        "sent": sent,
        "status": "sent" if sent else "failed",
        "http_status": status_code,
        "response": body,
        "payload": {"title": plan.title, "text": message_payload["text"], "raw": message_payload},
    }


@app.post("/api/todos/dingtalk/create")
def create_dingtalk_todo(payload: DingTalkPayload, db: Session = Depends(get_db)) -> dict:
    plan = get_plan_or_404(db, payload.plan_id)
    todo_payload = build_dingtalk_todo_payload(plan)
    todo_url = os.environ.get("DINGTALK_TODO_CREATE_URL")
    token = os.environ.get("DINGTALK_ACCESS_TOKEN")
    if not todo_url or not token:
        return {
            "channel": "dingtalk_todo",
            "enabled": False,
            "created": False,
            "status": "not_configured",
            "payload": todo_payload,
        }

    headers = {"x-acs-dingtalk-access-token": token}
    try:
        result = post_json(todo_url, todo_payload, headers=headers)
    except RuntimeError as exc:
        try:
            error_info = json.loads(str(exc))
        except json.JSONDecodeError:
            error_info = {
                "error": str(exc),
                "error_type": "network",
                "debug_trace": {
                    "request_url": todo_url,
                    "request_headers": {"x-acs-dingtalk-access-token": "***"},
                    "request_body": todo_payload,
                    "response_status": None,
                    "response_body": "",
                    "request_id": None,
                },
            }
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

    if isinstance(result, tuple):
        status_code, body = result
        trace = {
            "request_url": todo_url,
            "request_headers": {"x-acs-dingtalk-access-token": "***"},
            "request_body": todo_payload,
            "response_status": status_code,
            "response_body": body,
            "request_id": None,
        }
    else:
        status_code = result["http_status"]
        body = result["response_body"]
        trace = {
            "request_url": result["request_url"],
            "request_headers": result["request_headers"],
            "request_body": result["request_body"],
            "response_status": result["http_status"],
            "response_body": result["response_body"],
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
    error_type = "api" if not created else "unknown"
    if status == "failed" and status_code == 0:
        error_type = "network"
    return {
        "channel": "dingtalk_todo",
        "enabled": True,
        "created": created,
        "status": status,
        "http_status": status_code,
        "response": body,
        "permission": permission,
        "error_type": error_type,
        "debug_trace": trace,
        "payload": todo_payload,
    }


# ── Exercise Library CRUD ──────────────────────────────────────────────────

class ExercisePayload(BaseModel):
    name: str
    category: str = ""
    body_parts: str = ""
    bodyParts: list[str] | None = None
    difficulty: str = "低"
    default_sets: int = 3
    defaultSets: int | None = None
    default_reps: str | None = None
    defaultReps: str | None = None
    duration_seconds: int | None = None
    durationSeconds: int | None = None
    notes: str | None = None
    tips: str | list[str] | None = None
    video_url: str | None = None
    videos: list[dict] | None = None

    def to_model_dict(self) -> dict:
        videos = self.videos or []
        default_video = next((item for item in videos if item.get("isDefault")), videos[0] if videos else {})
        tips = self.tips
        return {
            "name": self.name,
            "category": self.category,
            "body_parts": ",".join(self.bodyParts) if self.bodyParts is not None else self.body_parts,
            "difficulty": self.difficulty,
            "default_sets": self.defaultSets if self.defaultSets is not None else self.default_sets,
            "default_reps": self.defaultReps if self.defaultReps is not None else self.default_reps,
            "duration_seconds": self.durationSeconds if self.durationSeconds is not None else self.duration_seconds,
            "notes": self.notes,
            "tips": "|".join(tips) if isinstance(tips, list) else tips,
            "video_url": default_video.get("url") or self.video_url,
        }


def exercise_to_dict(ex: Exercise) -> dict:
    return {
        "id": ex.id,
        "name": ex.name,
        "category": ex.category,
        "body_parts": ex.body_parts,
        "difficulty": ex.difficulty,
        "default_sets": ex.default_sets,
        "default_reps": ex.default_reps,
        "duration_seconds": ex.duration_seconds,
        "notes": ex.notes,
        "tips": ex.tips,
        "video_url": ex.video_url,
    }


@app.get("/api/exercises")
def list_exercises(db: Session = Depends(get_db)) -> dict:
    rows = db.query(Exercise).order_by(Exercise.name.asc()).all()
    return {"exercises": [exercise_to_dict(r) for r in rows]}


@app.get("/api/exercises/{exercise_id}")
def get_exercise(exercise_id: int, db: Session = Depends(get_db)) -> dict:
    ex = db.query(Exercise).filter(Exercise.id == exercise_id).first()
    if not ex:
        raise HTTPException(status_code=404, detail="动作不存在")
    return exercise_to_dict(ex)


@app.post("/api/exercises", status_code=201)
def create_exercise(payload: ExercisePayload, db: Session = Depends(get_db)) -> dict:
    ex = Exercise(**payload.to_model_dict())
    db.add(ex)
    db.commit()
    db.refresh(ex)
    return exercise_to_dict(ex)


@app.put("/api/exercises/{exercise_id}")
def update_exercise(exercise_id: int, payload: ExercisePayload, db: Session = Depends(get_db)) -> dict:
    ex = db.query(Exercise).filter(Exercise.id == exercise_id).first()
    if not ex:
        raise HTTPException(status_code=404, detail="动作不存在")
    for key, value in payload.to_model_dict().items():
        setattr(ex, key, value)
    db.commit()
    db.refresh(ex)
    return exercise_to_dict(ex)


@app.delete("/api/exercises/{exercise_id}")
def delete_exercise(exercise_id: int, db: Session = Depends(get_db)) -> dict:
    ex = db.query(Exercise).filter(Exercise.id == exercise_id).first()
    if not ex:
        raise HTTPException(status_code=404, detail="动作不存在")
    db.delete(ex)
    db.commit()
    return {"status": "deleted", "id": exercise_id}


# ── Template CRUD ──────────────────────────────────────────────────────────

class TemplatePayload(BaseModel):
    name: str
    description: str | None = None
    difficulty: str = "低强度"
    estimated_minutes: int = 30
    exercise_ids: list[int] = []


def template_to_dict(tmpl: Template) -> dict:
    return {
        "id": tmpl.id,
        "name": tmpl.name,
        "description": tmpl.description,
        "difficulty": tmpl.difficulty,
        "estimated_minutes": tmpl.estimated_minutes,
        "exercises": [exercise_to_dict(ex) for ex in tmpl.exercises],
    }


@app.get("/api/templates")
def list_templates(db: Session = Depends(get_db)) -> dict:
    rows = db.query(Template).order_by(Template.name.asc()).all()
    return {"templates": [template_to_dict(r) for r in rows]}


@app.get("/api/templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db)) -> dict:
    tmpl = db.query(Template).filter(Template.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    return template_to_dict(tmpl)


@app.post("/api/templates", status_code=201)
def create_template(payload: TemplatePayload, db: Session = Depends(get_db)) -> dict:
    tmpl = Template(
        name=payload.name,
        description=payload.description,
        difficulty=payload.difficulty,
        estimated_minutes=payload.estimated_minutes,
    )
    db.add(tmpl)
    db.flush()
    if payload.exercise_ids:
        exercises = db.query(Exercise).filter(Exercise.id.in_(payload.exercise_ids)).all()
        tmpl.exercises = exercises
    db.commit()
    db.refresh(tmpl)
    return template_to_dict(tmpl)


@app.put("/api/templates/{template_id}")
def update_template(template_id: int, payload: TemplatePayload, db: Session = Depends(get_db)) -> dict:
    tmpl = db.query(Template).filter(Template.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    tmpl.name = payload.name
    tmpl.description = payload.description
    tmpl.difficulty = payload.difficulty
    tmpl.estimated_minutes = payload.estimated_minutes
    if payload.exercise_ids is not None:
        exercises = db.query(Exercise).filter(Exercise.id.in_(payload.exercise_ids)).all()
        tmpl.exercises = exercises
    db.commit()
    db.refresh(tmpl)
    return template_to_dict(tmpl)


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)) -> dict:
    tmpl = db.query(Template).filter(Template.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(tmpl)
    db.commit()
    return {"status": "deleted", "id": template_id}


# ── Training Completion ────────────────────────────────────────────────────

class TrainingCompletePayload(BaseModel):
    date: str
    template_id: int | None = None
    completed: list[str] = []
    skipped: list[str] = []
    status: str = "done"
    notes: str | None = None


@app.post("/api/training/complete")
def training_complete(payload: TrainingCompletePayload, db: Session = Depends(get_db)) -> dict:
    """Record training session completion. Links to backend plan if one exists."""
    from datetime import date as dt_date
    try:
        plan_date = dt_date.fromisoformat(payload.date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="日期格式错误") from exc

    plan = db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == plan_date).first()
    plan_id = plan.id if plan else None

    log = WorkoutLog(
        plan_id=plan_id,
        log_date=plan_date,
        action="completed" if payload.status == "done" else "skipped",
        status="completed" if payload.status == "done" else "skipped",
        notes=payload.notes or f"训练完成，完成{len(payload.completed)}个动作，跳过{len(payload.skipped)}个动作",
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return {
        "status": "recorded",
        "plan_id": plan_id,
        "log_id": log.id,
        "completed": payload.completed,
        "skipped": payload.skipped,
    }


# ── Plan Edit ──────────────────────────────────────────────────────────────

class PlanUpdatePayload(BaseModel):
    title: str | None = None
    is_training_day: bool | None = None
    focus: str | None = None
    notes: str | None = None


@app.put("/api/plans/{plan_id}")
def update_plan(plan_id: int, payload: PlanUpdatePayload, db: Session = Depends(get_db)) -> dict:
    plan = db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    if payload.title is not None:
        plan.title = payload.title
    if payload.is_training_day is not None:
        plan.is_training_day = payload.is_training_day
    if payload.focus is not None:
        plan.focus = payload.focus
    if payload.notes is not None:
        plan.notes = payload.notes
    db.commit()
    db.refresh(plan)
    return plan_item(plan, plan.plan_date)


# ---------------------------------------------------------------------------
# AI 辅助能力（第二阶段）
# ---------------------------------------------------------------------------

BILIBILI_DOMAINS = {"bilibili.com", "www.bilibili.com", "b23.tv", "search.bilibili.com"}
FORBIDDEN_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}
AI_API_KEY_VARS = ("WORKOUT_AI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "WUAPI_API_KEY")
AI_BASE_URL_VARS = ("WORKOUT_AI_BASE_URL", "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL", "WUAPI_BASE_URL")
AI_MODEL_VARS = ("WORKOUT_AI_MODEL", "OPENAI_MODEL", "DEEPSEEK_MODEL", "WUAPI_MODEL")
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_AI_MODEL = "deepseek-v4-flash"


def _first_env(names: tuple[str, ...]) -> tuple[str, str]:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    return "", ""


def _ai_config() -> dict:
    api_key, api_key_var = _first_env(AI_API_KEY_VARS)
    base_url, base_url_var = _first_env(AI_BASE_URL_VARS)
    model, model_var = _first_env(AI_MODEL_VARS)
    if api_key and not base_url and api_key_var == "DEEPSEEK_API_KEY":
        base_url = DEFAULT_DEEPSEEK_BASE_URL
        base_url_var = "DEFAULT_DEEPSEEK_BASE_URL"
    if api_key and not model:
        model = DEFAULT_AI_MODEL
        model_var = "DEFAULT_AI_MODEL"
    return {
        "api_key": api_key,
        "api_key_var": api_key_var,
        "base_url": base_url.rstrip("/"),
        "base_url_var": base_url_var,
        "model": model,
        "model_var": model_var,
        "enabled": bool(api_key and base_url and model),
    }


def _safe_base_url_label(base_url: str) -> str:
    if not base_url:
        return ""
    parsed = urlparse(base_url)
    return parsed.netloc or base_url.split("/")[0]


def _bilibili_search_url(keyword: str) -> str:
    query = quote((keyword or "训练动作").strip() or "训练动作")
    return f"https://search.bilibili.com/all?keyword={query}"


def _validate_bilibili_url(url: str) -> bool:
    """白名单校验：只允许 bilibili.com / b23.tv，拒绝 youtube / youtu.be 等."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # 显式拒绝
        if any(host == d or host.endswith("." + d) for d in FORBIDDEN_DOMAINS):
            return False
        if host in BILIBILI_DOMAINS:
            return True
        if any(host.endswith("." + d) for d in BILIBILI_DOMAINS):
            return True
        return False
    except Exception:
        return False


def _validate_ai_draft(draft: dict) -> list[str]:
    """校验 AI 生成的草稿 JSON 结构，返回中文错误列表."""
    errors = []

    if not isinstance(draft, dict):
        return ["AI 返回的数据格式错误，预期为 JSON 对象"]

    for field_name in ("version", "title", "theme", "recommendedDate"):
        if not draft.get(field_name) or not isinstance(draft.get(field_name), str):
            errors.append(f"缺少 {field_name} 字段")

    exercises = draft.get("exercises", [])
    exercise_ids = set()
    if not isinstance(exercises, list):
        errors.append("exercises 必须是数组")
    else:
        if len(exercises) == 0:
            errors.append("exercises 至少需要 1 个动作")
        for i, exercise in enumerate(exercises):
            if not isinstance(exercise, dict):
                errors.append(f"第 {i+1} 个动作格式错误")
                continue
            eid = exercise.get("id", "")
            if not eid or not isinstance(eid, str):
                errors.append(f"第 {i+1} 个动作缺少 id 或 id 不是字符串")
            else:
                if not re.match(r"^[A-Za-z0-9_]+$", eid):
                    errors.append(f"动作 {eid} 的 ID 格式不合法，只允许英文、数字、下划线")
                if eid in exercise_ids:
                    errors.append(f"重复动作 ID：{eid}")
                exercise_ids.add(eid)
            if not exercise.get("name") or not isinstance(exercise.get("name"), str):
                errors.append(f"动作 {eid or i+1} 缺少 name 字段")
            has_reps = bool(exercise.get("defaultReps"))
            has_duration = exercise.get("durationSeconds") is not None
            if not exercise.get("defaultSets") or not (has_reps or has_duration):
                errors.append(f"动作 {exercise.get('name', eid or i+1)} 缺少组数/次数/时长")
            if not exercise.get("notes") or not isinstance(exercise.get("notes"), str):
                errors.append(f"动作 {exercise.get('name', eid or i+1)} 缺少注意事项")

            videos = exercise.get("videos", [])
            if isinstance(videos, list):
                default_count = 0
                for v in videos:
                    if not isinstance(v, dict):
                        errors.append(f"动作 {exercise.get('name', eid or i+1)} 的视频格式错误")
                        continue
                    url = v.get("url", "")
                    if url and not _validate_bilibili_url(url):
                        ename = exercise.get("name", exercise.get("id", ""))
                        errors.append(f"动作 {ename} 的视频 URL 不是合法 Bilibili 链接：{url}")
                    if v.get("isDefault"):
                        default_count += 1
                if default_count > 1:
                    ename = exercise.get("name", exercise.get("id", ""))
                    errors.append(f"动作 {ename} 存在多个默认视频")

    templates = draft.get("templates", [])
    if not isinstance(templates, list):
        errors.append("templates 必须是数组")
    else:
        template_ids = set()
        for i, tmpl in enumerate(templates):
            if not isinstance(tmpl, dict):
                errors.append(f"第 {i+1} 个模板格式错误")
                continue
            tid = tmpl.get("id", "")
            if not tid:
                errors.append(f"第 {i+1} 个模板缺少 id")
            if not tmpl.get("name"):
                errors.append(f"模板 {tid or i+1} 缺少 name")
            if tid in template_ids:
                errors.append(f"重复模板 ID：{tid}")
            template_ids.add(tid)
            for eid in tmpl.get("exerciseIds", []):
                if eid not in exercise_ids:
                    errors.append(f"模板 {tmpl.get('name', tid)} 引用不存在动作：{eid}")

    schedule = draft.get("schedule", {})
    if not isinstance(schedule, dict):
        errors.append("schedule 必须是对象")
    else:
        for ds, entry in schedule.items():
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(ds)):
                errors.append(f"日期 {ds} 格式错误，应为 YYYY-MM-DD")
            if not isinstance(entry, dict):
                errors.append(f"日期 {ds} 的计划格式错误")
                continue
            if entry.get("type") == "training" and not entry.get("templateId"):
                errors.append(f"日期 {ds} 是训练日但缺少 templateId")
            if entry.get("templateId") and entry.get("templateId") not in template_ids:
                errors.append(f"日期 {ds} 引用不存在模板：{entry.get('templateId')}")

    return errors


def _call_ai_chat(
    base_url: str, api_key: str, model: str,
    system_prompt: str, user_prompt: str,
    timeout: int = 60,
) -> str:
    """调用 OpenAI-compatible Chat Completions API，返回 message content 字符串."""
    chat_url = f"{base_url.rstrip('/')}/chat/completions"
    body_bytes = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
    }, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        req = Request(chat_url, data=body_bytes, headers=headers, method="POST")
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            data = json.loads(body)
    except HTTPError as exc:
        eb = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"AI 服务响应错误 {exc.code}: {eb[:300]}")
    except URLError as exc:
        raise RuntimeError(f"AI 服务连接失败: {exc.reason}")
    except Exception as exc:
        raise RuntimeError(f"AI 服务请求异常: {str(exc)[:300]}")

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"AI 服务返回结构异常: {str(exc)[:200]}")


class AIImportRequest(BaseModel):
    prompt: str
    current_data: Optional[dict] = None


class AISuggestVideoRequest(BaseModel):
    exercise_name: str = ""
    description: str = ""
    notes: str = ""


class PlanGenerateRequest(BaseModel):
    date: str
    title: str | None = None
    theme: str | None = None
    exerciseIds: list[int] = []
    notes: str | None = None


class SessionStartRequest(BaseModel):
    plan_id: int


class SessionUpdateRequest(BaseModel):
    session_id: int
    exercise_id: int
    status: str = "completed"
    sets_completed: int | None = None
    reps_completed: str | None = None
    duration_seconds: int | None = None
    notes: str | None = None


class SessionCompleteRequest(BaseModel):
    session_id: int
    notes: str | None = None
    rating: int | None = None


class AIAnalyzeRequest(BaseModel):
    session_id: int | None = None
    prompt: str | None = None


class AIFeedbackRequest(BaseModel):
    session_id: int
    rating: int
    comment: str | None = None


def date_from_iso(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="日期格式必须是 YYYY-MM-DD") from exc


def _parse_reps(value: str | None) -> int | None:
    number = re.sub(r"[^0-9]", "", value or "")
    return int(number) if number else None


def plan_to_v31_dict(plan: WorkoutPlan) -> dict:
    items = [
        {
            "id": item.id,
            "exercise_id": item.exercise_id if item.exercise_id is not None else item.id,
            "name": item.name,
            "sortOrder": item.sort_order,
            "sets": item.sets,
            "reps": item.reps,
            "durationSeconds": item.duration_seconds,
            "videoUrl": item.video_url,
            "notes": item.description,
        }
        for item in sorted(plan.exercises, key=lambda row: row.sort_order)
    ]
    return {
        "id": plan.id,
        "date": as_date(plan.plan_date).isoformat(),
        "title": plan.title,
        "theme": plan.focus,
        "notes": plan.notes,
        "isTrainingDay": bool(plan.is_training_day),
        "items": items,
    }


def session_record_to_v31_dict(record: SessionRecord) -> dict:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "exercise_id": record.exercise_id,
        "status": record.status,
        "sets_completed": record.sets_completed,
        "reps_completed": record.reps_completed,
        "duration_seconds": record.duration_seconds,
        "notes": record.notes,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


def session_to_v31_dict(session: WorkoutSession) -> dict:
    return {
        "id": session.id,
        "plan_id": session.plan_id,
        "status": session.status,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "notes": session.notes,
        "rating": session.rating,
        "ai_feedback": session.ai_feedback,
        "records": [session_record_to_v31_dict(record) for record in session.records],
    }


def call_openai_compatible(base_url: str, api_key: str, model: str, system_prompt: str, user_prompt: str, timeout: int = 60) -> dict:
    content = _call_ai_chat(base_url, api_key, model, system_prompt, user_prompt, timeout=timeout)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI 返回非 JSON：{content[:300]}") from exc


def _require_plan(db: Session, plan_id: int) -> WorkoutPlan:
    plan = db.query(WorkoutPlan).filter(WorkoutPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    return plan


def _require_session(db: Session, session_id: int) -> WorkoutSession:
    session = db.query(WorkoutSession).filter(WorkoutSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="训练会话不存在")
    return session


def _local_ai_analysis(session: WorkoutSession) -> dict:
    completed = sum(1 for record in session.records if record.status == "completed")
    total = len(session.records) or 1
    score = round((completed / total) * 100)
    return {
        "session_id": session.id,
        "score": score,
        "summary": "训练记录已完成分析。",
        "adjustments": ["保持当前低强度节奏", "下次训练优先保证动作质量"],
    }


def _run_session_analysis(session: WorkoutSession) -> dict:
    config = _ai_config()
    if not config["enabled"]:
        return _local_ai_analysis(session)
    payload = {"session": session_to_v31_dict(session), "plan": plan_to_v31_dict(session.plan)}
    return call_openai_compatible(
        config["base_url"],
        config["api_key"],
        config["model"],
        "你是运动训练复审助手，只能给 session 评分、训练调整建议，禁止输出写库指令。请返回 JSON。",
        json.dumps(payload, ensure_ascii=False),
    )


@app.get("/api/plans")
def list_v31_plans(date: str | None = Query(None), db: Session = Depends(get_db)) -> dict:
    query = db.query(WorkoutPlan).order_by(WorkoutPlan.plan_date.asc())
    if date:
        query = query.filter(WorkoutPlan.plan_date == date_from_iso(date))
    return {"plans": [plan_to_v31_dict(plan) for plan in query.all()]}


@app.post("/api/plans/generate")
def generate_plan(payload: PlanGenerateRequest, db: Session = Depends(get_db)) -> dict:
    plan_date = date_from_iso(payload.date)
    plan = db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == plan_date).first()
    if plan is None:
        plan = WorkoutPlan(plan_date=plan_date, title=payload.title or "生成训练计划", is_training_day=True, focus=payload.theme or "训练建议", notes=payload.notes or "")
        db.add(plan)
        db.flush()
    else:
        plan.title = payload.title or plan.title
        plan.is_training_day = True
        plan.focus = payload.theme or plan.focus
        plan.notes = payload.notes if payload.notes is not None else plan.notes
        for item in list(plan.exercises):
            db.delete(item)
        db.flush()
    for idx, exercise_id in enumerate(payload.exerciseIds, start=1):
        exercise = db.query(Exercise).filter(Exercise.id == exercise_id).first()
        if not exercise:
            raise HTTPException(status_code=404, detail=f"动作不存在：{exercise_id}")
        db.add(WorkoutExercise(plan_id=plan.id, exercise_id=exercise.id, sort_order=idx, name=exercise.name, description=exercise.notes or "", sets=exercise.default_sets, duration_seconds=exercise.duration_seconds, reps=_parse_reps(exercise.default_reps), video_url=exercise.video_url))
    db.commit()
    db.refresh(plan)
    return {"status": "ok", "plan": plan_to_v31_dict(plan)}


@app.post("/api/session/start")
def start_session(payload: SessionStartRequest, db: Session = Depends(get_db)) -> dict:
    plan = _require_plan(db, payload.plan_id)
    session = WorkoutSession(plan_id=plan.id, status="in_progress")
    db.add(session)
    db.flush()
    for item in plan.exercises:
        db.add(SessionRecord(session_id=session.id, exercise_id=item.exercise_id if item.exercise_id is not None else item.id, status="pending"))
    db.commit()
    db.refresh(session)
    return {"status": "started", "session": session_to_v31_dict(session), "plan": plan_to_v31_dict(plan)}


@app.post("/api/session/update")
def update_session(payload: SessionUpdateRequest, db: Session = Depends(get_db)) -> dict:
    session = _require_session(db, payload.session_id)
    record = db.query(SessionRecord).filter(SessionRecord.session_id == session.id, SessionRecord.exercise_id == payload.exercise_id).first()
    if record is None:
        record = SessionRecord(session_id=session.id, exercise_id=payload.exercise_id)
        db.add(record)
    record.status = payload.status
    record.sets_completed = payload.sets_completed
    record.reps_completed = payload.reps_completed
    record.duration_seconds = payload.duration_seconds
    record.notes = payload.notes
    if payload.status == "completed":
        record.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(record)
    return {"status": "updated", "record": session_record_to_v31_dict(record)}


@app.post("/api/session/complete")
def complete_session(payload: SessionCompleteRequest, db: Session = Depends(get_db)) -> dict:
    session = _require_session(db, payload.session_id)
    session.status = "completed"
    session.completed_at = datetime.utcnow()
    session.notes = payload.notes
    session.rating = payload.rating
    completed_records = db.query(SessionRecord).filter(SessionRecord.session_id == session.id, SessionRecord.status == "completed").count()
    db.add(WorkoutLog(plan_id=session.plan_id, action="completed", status="completed", notes=payload.notes))
    db.commit()
    db.refresh(session)
    return {"status": "completed", "session": session_to_v31_dict(session), "summary": {"completed_records": completed_records}}


@app.post("/api/ai/feedback")
def ai_feedback(payload: AIFeedbackRequest, db: Session = Depends(get_db)) -> dict:
    session = _require_session(db, payload.session_id)
    return {"status": "feedback_recorded", "session_id": session.id, "rating": payload.rating, "comment": payload.comment}


@app.get("/api/ai/health")
def ai_health():
    config = _ai_config()
    enabled = config["enabled"]
    return {
        "enabled": enabled,
        "provider": "openai-compatible",
        "model": config["model"] if enabled else "",
        "base_url": _safe_base_url_label(config["base_url"]) if enabled else "",
        "key_configured": bool(config["api_key"]),
        "config_vars": {
            "credential_configured": bool(config["api_key"]),
            "base_url_configured": bool(config["base_url_var"]),
            "model_configured": bool(config["model_var"]),
        },
        "message": "AI 服务已配置" if enabled
        else "AI 服务未配置，请设置 WORKOUT_AI_API_KEY/WORKOUT_AI_BASE_URL/WORKOUT_AI_MODEL，或兼容的 OPENAI/DEEPSEEK/WUAPI 环境变量",
    }


def _fallback_ai_preview(prompt: str) -> dict:
    query = (prompt or "训练计划").strip()[:80] or "训练计划"
    search_url = _bilibili_search_url(query)
    return {
        "status": "fallback",
        "ai_enabled": False,
        "draft": None,
        "fallback": {
            "query": query,
            "search_url": search_url,
            "message": "AI 服务未配置，已提供 Bilibili 搜索回退链接；不会伪造 AI 结果。",
        },
        "warnings": ["AI 服务未配置，未调用外部模型"],
    }


def _draft_response(draft: dict, ai_enabled: bool = True) -> dict:
    plans_list = []
    schedule = draft.get("schedule", {})
    if isinstance(schedule, dict):
        for date_str, entry in schedule.items():
            if isinstance(entry, dict):
                plans_list.append({
                    "date": date_str,
                    "type": entry.get("type", "rest"),
                    "templateId": entry.get("templateId", ""),
                    "status": entry.get("status", "pending"),
                    "note": entry.get("note", ""),
                })
    return {
        "status": "draft",
        "ai_enabled": ai_enabled,
        "draft": {
            "title": draft.get("title", ""),
            "theme": draft.get("theme", ""),
            "recommendedDate": draft.get("recommendedDate", ""),
            "exercises": draft.get("exercises", []),
            "templates": draft.get("templates", []),
            "plans": plans_list,
        },
        "warnings": [],
    }


def _build_ai_import_prompt() -> str:
    return """你是一个运动训练计划生成助手。根据用户描述生成结构化训练数据 JSON。

输出格式必须严格遵循：
{
  "version": "1.0",
  "source": "ai_generated",
  "title": "训练标题",
  "theme": "训练主题",
  "recommendedDate": "YYYY-MM-DD",
  "exercises": [
    {
      "id": "英文ID", "name": "动作名称", "category": "分类",
      "bodyParts": ["部位"], "difficulty": "低/中/高",
      "defaultSets": 3, "defaultReps": "12次", "durationSeconds": null,
      "notes": "注意事项", "tips": ["要点1"],
      "videos": [{"id":"vid","title":"Bilibili 搜索标题","platform":"bilibili","url":"https://search.bilibili.com/all?keyword=搜索词","isDefault":true,"remark":"搜索词或B站链接"}]
    }
  ],
  "templates": [
    { "id": "模板ID", "name": "名称", "description": "", "exerciseIds": ["动作ID"], "difficulty": "低强度", "estimatedMinutes": 30 }
  ],
  "schedule": {
    "YYYY-MM-DD": { "type": "training", "templateId": "模板ID", "status": "pending", "note": "" }
  }
}

硬性要求：
- 只输出 JSON，不要 Markdown，不要解释
- title、theme、recommendedDate 必填
- exercises 至少 1 个动作，每个动作必须有名称、组数、次数或时长、注意事项
- 视频只能给 Bilibili 搜索链接或 bilibili.com/b23.tv 链接
- 严禁输出 YouTube/youtu.be 链接
- templates 至少 1 个，exerciseIds 必须引用存在的动作 ID
- schedule 日期只包含训练日
- 所有文本使用中文"""


@app.post("/api/ai/import-plan")
def ai_import_plan(payload: AIImportRequest):
    config = _ai_config()
    if not config["enabled"]:
        return _fallback_ai_preview(payload.prompt)

    try:
        content = _call_ai_chat(
            config["base_url"], config["api_key"], config["model"],
            _build_ai_import_prompt(), payload.prompt,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"AI 调用失败，未生成正式导入结果：{exc}")

    try:
        draft = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail=f"AI 返回的不是合法 JSON：{str(exc)[:200]}"
        )

    errors = _validate_ai_draft(draft)
    if errors:
        raise HTTPException(
            status_code=422,
            detail="AI 生成的草稿校验失败：\n" + "\n".join(errors),
        )

    return _draft_response(draft, ai_enabled=True)


@app.post("/api/ai/analyze")
def ai_analyze(payload: AIAnalyzeRequest, db: Session = Depends(get_db)):
    if payload.session_id is not None:
        session = _require_session(db, payload.session_id)
        analysis = _run_session_analysis(session)
        return {"status": "analysis", "analysis": analysis, "warnings": []}
    if payload.prompt:
        return ai_import_plan(AIImportRequest(prompt=payload.prompt))
    raise HTTPException(status_code=422, detail="必须提供 session_id 或 prompt")


@app.post("/api/ai/suggest-bilibili-video")
def ai_suggest_bilibili_video(payload: AISuggestVideoRequest):
    config = _ai_config()
    ex_name = payload.exercise_name or ""
    ex_desc = payload.description or ""
    ex_notes = payload.notes or ""
    if not config["enabled"]:
        query = ex_name or ex_desc or "训练动作"
        search_url = _bilibili_search_url(query)
        return {
            "status": "fallback",
            "ai_enabled": False,
            "query": query,
            "search_url": search_url,
            "candidates": [search_url],
            "message": "AI 服务未配置，返回 Bilibili 搜索回退链接。",
        }

    system_prompt = """你是一个健身教练，帮助用户在B站寻找训练教学视频。

根据动作信息返回 JSON：
{
  "keywords": ["B站搜索关键词1", "关键词2"],
  "searchUrls": ["https://search.bilibili.com/all?keyword=关键词1"],
  "recommendedTitle": "推荐的B站视频标题",
  "note": "搜索建议说明"
}
所有 searchUrls 必须使用 bilibili.com 域名，不得使用 youtube.com 或 youtu.be。"""

    user_prompt = f"动作名称：{ex_name}\n描述：{ex_desc}\n备注：{ex_notes}"

    try:
        content = _call_ai_chat(config["base_url"], config["api_key"], config["model"], system_prompt, user_prompt, timeout=30)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"AI 调用失败，未生成视频建议：{exc}")

    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail=f"AI 返回的不是合法 JSON：{str(exc)[:200]}"
        )

    if not isinstance(result, dict):
        raise HTTPException(status_code=422, detail="AI 返回格式错误")

    keywords = result.get("keywords", [])
    search_urls = result.get("searchUrls", [])
    if not isinstance(keywords, list):
        keywords = []
    if not isinstance(search_urls, list):
        search_urls = []

    for url in search_urls:
        if not _validate_bilibili_url(url):
            raise HTTPException(
                status_code=422,
                detail=f"AI 返回了非 Bilibili 视频链接（已拒绝）：{url}",
            )

    query = str(keywords[0]) if keywords else ex_name
    search_url = str(search_urls[0]) if search_urls else _bilibili_search_url(query)

    return {
        "status": "ok",
        "ai_enabled": True,
        "query": query,
        "search_url": search_url,
        "candidates": search_urls or [search_url],
    }
