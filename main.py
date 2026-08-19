import re
from calendar import monthrange
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
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
from sqlalchemy import text

from database import (
    Base,
    Exercise,
    Favorite,
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
from notification_service import NotificationRequest, NotificationService
import ai_service
from adapters.dingtalk import DingTalkAdapter
from seed import seed_database
from v25_migration import (
    MigrationInputError,
    StalePreviewError,
    build_preview,
    commit_preview,
)
from v25_catalog import build_catalog_preview, reconcile_catalog


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import database as database_module
    database_module.create_tables()
    # Allow isolated empty-DB E2E by setting WORKOUT_DISABLE_SEED=1
    if os.environ.get("WORKOUT_DISABLE_SEED", "").strip() not in {"1", "true", "TRUE", "yes", "YES"}:
        seed_database()
    database_module.migrate_database()
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# v25 rehearsal preview only: the single source remains in the design workspace.
V25_PREVIEW_SOURCE = Path(r"D:\Vanta-pro\轻动日记\v25\轻动日记-v25.html")
V25_ASSETS_DIR = V25_PREVIEW_SOURCE.parent / "assets"
app.mount("/v25-preview/assets", StaticFiles(directory=V25_ASSETS_DIR), name="v25-preview-assets")


@app.get("/v25-preview/", include_in_schema=False)
@app.head("/v25-preview/", include_in_schema=False)
def v25_preview() -> FileResponse:
    return FileResponse(V25_PREVIEW_SOURCE, media_type="text/html")


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


class FavoritePayload(BaseModel):
    exercise_name: Optional[str] = None
    exerciseName: Optional[str] = None

    def resolved_name(self) -> str:
        value = self.exercise_name if self.exercise_name is not None else self.exerciseName
        value = (value or "").strip()
        if not value:
            raise HTTPException(status_code=422, detail="必须提供动作名称")
        return value


class ReminderPayload(BaseModel):
    plan_id: Optional[int] = None
    title: Optional[str] = None
    message: Optional[str] = None


class DingTalkPayload(BaseModel):
    plan_id: int


class NotificationPayload(BaseModel):
    plan_id: Optional[int] = None
    channel: str = "dingtalk"
    title: Optional[str] = None
    message: Optional[str] = None
    include_todo: bool = True
    force: bool = False


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
        "template_id": plan.template_id,
        "items": [
            {
                "id": item.id,
                "exercise_id": item.exercise_id,
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

    row = WorkoutLog(
        plan_id=plan_id,
        log_date=plan.plan_date,
        action=state,
        status=state,
        notes=notes,
    )
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


def favorite_item(row: Favorite) -> dict:
    return {
        "id": row.id,
        "exercise_name": row.exercise_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@app.get("/api/favorites")
def list_favorites(db: Session = Depends(get_db)) -> dict:
    rows = db.query(Favorite).order_by(Favorite.created_at.asc(), Favorite.id.asc()).all()
    return {"favorites": [favorite_item(row) for row in rows]}


@app.post("/api/favorites")
def create_favorite(payload: FavoritePayload, db: Session = Depends(get_db)) -> dict:
    from sqlalchemy.exc import IntegrityError

    name = payload.resolved_name()
    existing = db.query(Favorite).filter(Favorite.exercise_name == name).one_or_none()
    if existing is not None:
        return {"status": "already_exists", "favorite": favorite_item(existing)}

    row = Favorite(exercise_name=name)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(Favorite).filter(Favorite.exercise_name == name).one_or_none()
        if existing is None:
            raise
        return {"status": "already_exists", "favorite": favorite_item(existing)}
    db.refresh(row)
    return {"status": "created", "favorite": favorite_item(row)}


@app.delete("/api/favorites/{exercise_name}")
def delete_favorite(exercise_name: str, db: Session = Depends(get_db)) -> dict:
    name = (exercise_name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="必须提供动作名称")
    row = db.query(Favorite).filter(Favorite.exercise_name == name).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="未找到收藏动作")
    db.delete(row)
    db.commit()
    return {"status": "deleted", "exercise_name": name}


def _migration_preview_or_error(payload: dict, db: Session) -> dict:
    try:
        return build_preview(db, payload)
    except MigrationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/migration/v24/preview")
@app.post("/api/migrations/v24/preview")
def migration_v24_preview(payload: dict, db: Session = Depends(get_db)) -> dict:
    return _migration_preview_or_error(payload, db)


@app.post("/api/migration/v24/commit")
@app.post("/api/migrations/v24/commit")
def migration_v24_commit(payload: dict, db: Session = Depends(get_db)) -> dict:
    try:
        result = commit_preview(db, payload)
        db.commit()
        return result
    except StalePreviewError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"status": "stale_preview", "message": str(exc)}) from exc
    except MigrationInputError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"status": "blocked", "message": str(exc)}) from exc
    except Exception:
        db.rollback()
        raise


@app.post("/api/migration/catalog/v24/preview")
@app.post("/api/migrations/catalog/v24/preview")
def catalog_v24_preview(db: Session = Depends(get_db)) -> dict:
    return build_catalog_preview(db)


@app.post("/api/migration/catalog/v24/commit")
@app.post("/api/migrations/catalog/v24/commit")
def catalog_v24_commit(payload: dict | None = None, db: Session = Depends(get_db)) -> dict:
    try:
        result = reconcile_catalog(db, payload or {})
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        status = 409 if "stale_preview" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


def _duration_metrics(db: Session, start: date | None = None, end: date | None = None) -> dict:
    query = db.query(SessionRecord).filter(SessionRecord.status == "completed")
    if start is not None and end is not None:
        query = query.join(WorkoutSession, SessionRecord.session_id == WorkoutSession.id).join(
            WorkoutLog, WorkoutLog.session_id == WorkoutSession.id
        ).filter(
            WorkoutLog.log_date >= start,
            WorkoutLog.log_date <= end,
            WorkoutLog.status == "completed",
        )
    durations = [row.duration_seconds for row in query.all()]
    known = [value for value in durations if value is not None]
    return {
        "duration_seconds": sum(known),
        "duration_known_records": len(known),
        "duration_unknown_records": sum(value is None for value in durations),
        "duration_zero_records": sum(value == 0 for value in known),
    }


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
        **_duration_metrics(db),
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
    completed_training_days = (
        logs_query
        .join(WorkoutPlan, WorkoutLog.plan_id == WorkoutPlan.id)
        .filter(WorkoutLog.status == "completed", WorkoutPlan.is_training_day == True)
        .count()
    )
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
        "completion_rate": _completion_rate(completed_training_days, training_days),
        **_duration_metrics(db, start, end),
    }


def _completion_rate(completed: int, training_days: int) -> float:
    return round((completed / training_days) * 100, 2) if training_days else 0.0


def _stats_detail(db: Session, start: date, end: date, period: str) -> dict:
    plans = db.query(WorkoutPlan).filter(
        WorkoutPlan.plan_date >= start,
        WorkoutPlan.plan_date <= end,
    ).all()
    logs = db.query(WorkoutLog).filter(
        WorkoutLog.log_date >= start,
        WorkoutLog.log_date <= end,
    ).all()
    completed_dates = {
        log.log_date.isoformat()
        for log in logs
        if log.status == "completed"
    }
    training_days = sum(bool(plan.is_training_day) for plan in plans)
    completed = len({day for day in completed_dates if any(
        plan.plan_date.isoformat() == day and plan.is_training_day for plan in plans
    )})
    days = []
    current = start
    while current <= end:
        plan = next((row for row in plans if row.plan_date == current), None)
        day_logs = [row for row in logs if row.log_date == current]
        days.append({
            "date": current.isoformat(),
            "day_of_week": (current.weekday() + 1) % 7,
            "plan_id": plan.id if plan else None,
            "is_training": bool(plan and plan.is_training_day),
            "status": "completed" if any(row.status == "completed" for row in day_logs) else ("planned" if plan else "rest"),
            "duration": _duration_metrics_for_range(db, current, current),
        })
        current += timedelta(days=1)
    result = {
        "period": period,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "training_days": training_days,
        "completed": completed,
        "completion_rate": _completion_rate(completed, training_days),
        "days": days,
    }
    result.update(_duration_metrics(db, start, end))
    return result


def _duration_metrics_for_range(db: Session, start: date, end: date) -> dict:
    return _duration_metrics(db, start, end)


@app.get("/api/stats/month/detail")
def stats_month_detail(month: str = Query(...), db: Session = Depends(get_db)) -> dict:
    year, month_num = parse_month_token(month)
    start = date(year, month_num, 1)
    end = date(year, month_num, monthrange(year, month_num)[1])
    return _stats_detail(db, start, end, "month")


@app.get("/api/stats/week/detail")
def stats_week_detail(date_value: str = Query(..., alias="date"), db: Session = Depends(get_db)) -> dict:
    target = date_from_iso(date_value)
    # Contract: Sunday -> Saturday, independent of locale/host settings.
    start = target - timedelta(days=(target.weekday() + 1) % 7)
    return _stats_detail(db, start, start + timedelta(days=6), "week")


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
                "items": plan_item(plan, current)["items"] if plan else [],
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


@app.post("/api/reminders/dingtalk/send")
def send_dingtalk_reminder(payload: ReminderPayload, db: Session = Depends(get_db)) -> dict:
    service = NotificationService(db, dingtalk_adapter=DingTalkAdapter.from_env())
    return service.send_dingtalk_reminder(payload.plan_id, payload.title, payload.message)


@app.post("/api/todos/dingtalk/create")
def create_dingtalk_todo(payload: DingTalkPayload, db: Session = Depends(get_db)) -> dict:
    adapter = DingTalkAdapter.from_env()
    adapter.post_func = post_json
    service = NotificationService(db, dingtalk_adapter=adapter)
    return service.create_dingtalk_todo(payload.plan_id)


@app.post("/api/notifications/send")
def send_notification(payload: NotificationPayload, db: Session = Depends(get_db)) -> dict:
    service = NotificationService(db)
    result = service.send(
        NotificationRequest(
            plan_id=payload.plan_id,
            channel=payload.channel,
            title=payload.title,
            message=payload.message,
            include_todo=payload.include_todo,
            force=payload.force,
        )
    )
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result["detail"])
    return result


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
    benefit: str | None = None
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
            "benefit": self.benefit,
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
        "benefit": ex.benefit,
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
    # Detach plans that reference this template instead of cascading wrongly
    db.query(WorkoutPlan).filter(WorkoutPlan.template_id == template_id).update(
        {WorkoutPlan.template_id: None}
    )
    db.delete(tmpl)
    db.commit()
    return {"status": "deleted", "id": template_id}


# ── Data Management ──────────────────────────────────────────────────────────


class RestoreDefaultsRequest(BaseModel):
    confirm: bool = False
    backup: bool = True


@app.post("/api/data/restore-defaults")
def restore_defaults(payload: RestoreDefaultsRequest, db: Session = Depends(get_db)) -> dict:
    """Explicitly restore default seed data. Creates a backup before overwriting.

    This is the ONLY path that can overwrite existing user data, and it requires
    explicit confirmation (confirm=True). Without confirmation, it only reports
    what would happen.
    """
    plan_count = db.query(WorkoutPlan).count()
    exercise_count = db.query(Exercise).count()
    template_count = db.query(Template).count()
    session_count = db.query(WorkoutSession).count()
    log_count = db.query(WorkoutLog).count()

    if not payload.confirm:
        return {
            "status": "dry_run",
            "message": "需要明确确认才能恢复默认数据",
            "current_state": {
                "plans": plan_count,
                "exercises": exercise_count,
                "templates": template_count,
                "sessions": session_count,
                "logs": log_count,
            },
            "will_delete": ["workout_plans", "workout_exercises", "workout_sessions", "session_records", "workout_logs", "reminders", "exercises", "templates"],
            "will_keep": ["settings"],
            "action": "发送 confirm=true 并 backup=true 来执行恢复",
        }

    # Create backup before overwriting using SQLite backup API (consistent snapshot)
    backup_info = None
    if payload.backup:
        import database as database_module
        backup_dir = Path(__file__).parent / ".tmp" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_info = database_module.sqlite_backup(database_module.DATABASE_PATH, str(backup_dir))
        if backup_info["integrity"] != "ok":
            raise HTTPException(status_code=500, detail=f"备份完整性校验失败: {backup_info['integrity']}")

    # Wipe user-facing training data and reseed defaults in a single transaction path
    # Order matters under foreign_keys=ON
    db.query(SessionRecord).delete()
    db.query(WorkoutSession).delete()
    db.query(WorkoutLog).delete()
    db.query(WorkoutExercise).delete()
    db.query(Reminder).delete()
    # Clear template FK before deleting templates
    db.query(WorkoutPlan).update({WorkoutPlan.template_id: None})
    db.query(WorkoutPlan).delete()
    db.execute(text("DELETE FROM template_exercises"))
    db.query(Template).delete()
    db.query(Exercise).delete()
    db.commit()

    from database import seed_database as do_seed
    do_seed()

    return {
        "status": "restored",
        "backup": backup_info,
        "message": "默认数据已恢复，原数据已备份",
        "restored": {
            "plans": db.query(WorkoutPlan).count(),
            "exercises": db.query(Exercise).count(),
            "templates": db.query(Template).count(),
        },
    }



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
    """Legacy compatibility endpoint — delegates to _complete_session_unified when possible."""
    from datetime import date as dt_date
    try:
        plan_date = dt_date.fromisoformat(payload.date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="日期格式错误") from exc

    plan = db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == plan_date).first()
    plan_id = plan.id if plan else None

    # If active session exists for this plan, delegate to unified logic
    if plan:
        active_session = db.query(WorkoutSession).filter(
            WorkoutSession.plan_id == plan.id,
            WorkoutSession.status == "in_progress",
        ).first()
        if active_session:
            return _complete_session_unified(db, active_session, payload.notes)

    # No active session — create standalone log with DB-level dedup
    from sqlalchemy.exc import IntegrityError
    log_status = "completed" if payload.status == "done" else "skipped"
    existing = db.query(WorkoutLog).filter(
        WorkoutLog.log_date == plan_date,
        WorkoutLog.action == log_status,
    ).first()
    if existing:
        return {"status": "already_recorded", "plan_id": plan_id, "log_id": existing.id, "completed": payload.completed, "skipped": payload.skipped}

    log = WorkoutLog(plan_id=plan_id, log_date=plan_date, action=log_status, status=log_status, notes=payload.notes or f"训练完成，完成{len(payload.completed)}个动作")
    try:
        db.add(log)
        db.commit()
        db.refresh(log)
    except IntegrityError:
        db.rollback()
        existing2 = db.query(WorkoutLog).filter(WorkoutLog.log_date == plan_date, WorkoutLog.action == log_status).first()
        return {"status": "already_recorded", "plan_id": plan_id, "log_id": existing2.id if existing2 else None, "completed": payload.completed, "skipped": payload.skipped}

    return {"status": "recorded", "plan_id": plan_id, "log_id": log.id, "completed": payload.completed, "skipped": payload.skipped}


# ── Plan Edit ──────────────────────────────────────────────────────────────

class PlanUpdatePayload(BaseModel):
    title: str | None = None
    is_training_day: bool | None = None
    focus: str | None = None
    notes: str | None = None
    template_id: int | None = None


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

    # Handle template switching: replace exercises with template's exercise list
    if payload.template_id is not None:
        plan.template_id = payload.template_id
        tmpl = db.query(Template).filter(Template.id == payload.template_id).first()
        if tmpl is None:
            raise HTTPException(status_code=404, detail="模板不存在")
        # Remove old exercises, replace with template exercises
        for item in list(plan.exercises):
            db.delete(item)
        db.flush()
        for idx, ex in enumerate(tmpl.exercises, start=1):
            db.add(WorkoutExercise(
                plan_id=plan.id,
                exercise_id=ex.id,
                sort_order=idx,
                name=ex.name,
                description=ex.notes or "",
                sets=ex.default_sets,
                duration_seconds=ex.duration_seconds,
                reps=_parse_reps(ex.default_reps),
                video_url=ex.video_url,
            ))

    # Handle training day ↔ rest day conversion
    if payload.is_training_day is False:
        # Changed to rest day: clear exercises and template
        plan.template_id = None
        for item in list(plan.exercises):
            db.delete(item)

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
    return ai_service.first_env(names)


def _ai_config() -> dict:
    return ai_service.ai_config()


def _safe_base_url_label(base_url: str) -> str:
    return ai_service.safe_base_url_label(base_url)


def _bilibili_search_url(keyword: str) -> str:
    return ai_service.bilibili_search_url(keyword)


def _validate_bilibili_url(url: str) -> bool:
    return ai_service.validate_bilibili_url(url)


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
    return ai_service.call_ai_chat(base_url, api_key, model, system_prompt, user_prompt, timeout=timeout)


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


class AIChatMessage(BaseModel):
    role: str
    content: str | list[dict]


class AIChatRequest(BaseModel):
    messages: list[AIChatMessage]
    model: str | None = None
    provider: str | None = None


class AIProviderRequest(BaseModel):
    provider: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""


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
            "exercise_id": item.exercise_id,  # may be None if not linked to exercise library
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
        "template_id": plan.template_id,
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
    return ai_service.call_openai_compatible(base_url, api_key, model, system_prompt, user_prompt, timeout=timeout)


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
    analyzer = ai_service.SessionAnalyzer(ai_call=call_openai_compatible, config_func=_ai_config)
    return analyzer.analyze(session_to_v31_dict(session), plan_to_v31_dict(session.plan))


# ── Unified completion logic (single source of truth for both completion endpoints) ──

def _complete_session_unified(db: Session, session: WorkoutSession, payload_notes: str | None = None, payload_rating: int | None = None) -> dict:
    """Unified completion: validates state, creates WorkoutLog with DB-level dedup, returns consistent result."""
    from sqlalchemy.exc import IntegrityError

    if session.status == "completed":
        completed_records = db.query(SessionRecord).filter(
            SessionRecord.session_id == session.id,
            SessionRecord.status == "completed",
        ).count()
        return {"status": "already_completed", "session": session_to_v31_dict(session), "summary": {"completed_records": completed_records}}

    if session.status == "cancelled":
        raise HTTPException(status_code=422, detail="已取消的训练会话无法完成")

    if session.status != "in_progress":
        raise HTTPException(status_code=422, detail=f"训练会话状态为 {session.status}，无法完成")

    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)
    if payload_notes is not None:
        session.notes = payload_notes
    if payload_rating is not None:
        session.rating = payload_rating

    completed_records = db.query(SessionRecord).filter(
        SessionRecord.session_id == session.id,
        SessionRecord.status == "completed",
    ).count()

    # Try to create WorkoutLog with session_id tracking; unique constraint prevents duplicates
    try:
        log = WorkoutLog(
            plan_id=session.plan_id,
            session_id=session.id,
            log_date=session.plan.plan_date,
            action="completed",
            status="completed",
            notes=payload_notes,
        )
        db.add(log)
        db.commit()
    except IntegrityError:
        db.rollback()
        # Re-apply session terminal state after rollback, without re-creating log
        session = _require_session(db, session.id)
        if session.status != "completed":
            session.status = "completed"
            session.completed_at = datetime.now(timezone.utc)
            if payload_notes is not None:
                session.notes = payload_notes
            if payload_rating is not None:
                session.rating = payload_rating
            db.commit()
        db.refresh(session)
        existing_log = db.query(WorkoutLog).filter(
            WorkoutLog.plan_id == session.plan_id,
            WorkoutLog.action == "completed",
            WorkoutLog.log_date == session.plan.plan_date,
        ).first()
        return {
            "status": "already_completed",
            "session": session_to_v31_dict(session),
            "summary": {"completed_records": completed_records},
            "log_id": existing_log.id if existing_log else None,
        }

    db.refresh(session)
    db.refresh(log)
    return {
        "status": "completed",
        "session": session_to_v31_dict(session),
        "summary": {"completed_records": completed_records},
        "log_id": log.id,
    }


# ── API routes ───────────────────────────────────────────────────────────────

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
    # Bind template_id when the exercise set uniquely matches a template
    wanted = frozenset(payload.exerciseIds)
    matches = []
    for tmpl in db.query(Template).all():
        tmpl_ids = frozenset(ex.id for ex in tmpl.exercises)
        if tmpl_ids and tmpl_ids == wanted:
            matches.append(tmpl.id)
    plan.template_id = matches[0] if len(matches) == 1 else None
    db.commit()
    db.refresh(plan)
    return {"status": "ok", "plan": plan_to_v31_dict(plan)}


@app.post("/api/session/start")
def start_session(payload: SessionStartRequest, db: Session = Depends(get_db)) -> dict:
    from sqlalchemy.exc import IntegrityError
    plan = _require_plan(db, payload.plan_id)

    if not plan.is_training_day:
        raise HTTPException(status_code=422, detail="今天是休息日，无法开始训练")

    # Check if an active session already exists for this plan (with transaction guard)
    existing = db.query(WorkoutSession).filter(
        WorkoutSession.plan_id == plan.id,
        WorkoutSession.status == "in_progress",
    ).first()
    if existing:
        db.refresh(existing)
        return {"status": "resumed", "session": session_to_v31_dict(existing), "plan": plan_to_v31_dict(plan)}

    try:
        # Normal API-created sessions always carry an actual start timestamp;
        # NULL is reserved for legacy/imported historical sessions.
        session = WorkoutSession(
            plan_id=plan.id,
            status="in_progress",
            started_at=datetime.now(timezone.utc),
        )
        db.add(session)
        # Unique partial index may raise here under concurrent starts
        db.flush()
        for item in plan.exercises:
            exercise_id = item.exercise_id
            if exercise_id is None:
                matched = db.query(Exercise).filter(Exercise.name == item.name).first()
                exercise_id = matched.id if matched else None
            if exercise_id is not None:
                db.add(SessionRecord(session_id=session.id, exercise_id=exercise_id, status="pending"))
            else:
                db.add(SessionRecord(session_id=session.id, exercise_id=None, status="pending", notes=f"未匹配动作库: {item.name}"))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing2 = db.query(WorkoutSession).filter(
            WorkoutSession.plan_id == plan.id,
            WorkoutSession.status == "in_progress",
        ).first()
        if existing2:
            return {"status": "resumed", "session": session_to_v31_dict(existing2), "plan": plan_to_v31_dict(plan)}
        raise

    db.refresh(session)
    return {"status": "started", "session": session_to_v31_dict(session), "plan": plan_to_v31_dict(plan)}


@app.post("/api/session/update")
def update_session(payload: SessionUpdateRequest, db: Session = Depends(get_db)) -> dict:
    session = _require_session(db, payload.session_id)
    if session.status != "in_progress":
        raise HTTPException(status_code=422, detail=f"训练会话状态为 {session.status}，无法更新动作记录")

    # Map in_progress → pending (non-last-set completion)
    # DB constraint only allows: pending, completed, skipped
    status_map = {
        "in_progress": "pending",
        "completed": "completed",
        "skipped": "skipped",
        "pending": "pending",
    }
    db_status = status_map.get(payload.status)
    if db_status is None:
        raise HTTPException(status_code=422, detail=f"不允许的动作记录状态: {payload.status}")

    # Validate exercise exists in this session's records (which were created by session/start)
    existing_record = db.query(SessionRecord).filter(
        SessionRecord.session_id == session.id,
        SessionRecord.exercise_id == payload.exercise_id,
    ).first()
    if existing_record is None:
        raise HTTPException(status_code=422, detail=f"动作 {payload.exercise_id} 不在此训练会话中")

    existing_record.status = db_status
    existing_record.sets_completed = payload.sets_completed
    existing_record.reps_completed = payload.reps_completed
    existing_record.duration_seconds = payload.duration_seconds
    existing_record.notes = payload.notes
    if db_status == "completed":
        existing_record.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(existing_record)
    return {"status": "updated", "record": session_record_to_v31_dict(existing_record)}


@app.post("/api/session/complete")
def complete_session(payload: SessionCompleteRequest, db: Session = Depends(get_db)) -> dict:
    session = _require_session(db, payload.session_id)
    return _complete_session_unified(db, session, payload.notes, payload.rating)


@app.post("/api/session/cancel")
def cancel_session(payload: SessionCompleteRequest, db: Session = Depends(get_db)) -> dict:
    session = _require_session(db, payload.session_id)
    if session.status == "cancelled":
        return {"status": "already_cancelled", "session": session_to_v31_dict(session)}
    if session.status == "completed":
        raise HTTPException(status_code=422, detail="已完成的训练会话无法取消")
    session.status = "cancelled"
    session.completed_at = datetime.now(timezone.utc)
    session.notes = payload.notes
    db.commit()
    db.refresh(session)
    return {"status": "cancelled", "session": session_to_v31_dict(session)}


@app.get("/api/session/current")
def current_session(plan_id: int | None = Query(None), db: Session = Depends(get_db)) -> dict:
    """Return the current active session for a plan, or the latest active session."""
    query = db.query(WorkoutSession).filter(WorkoutSession.status == "in_progress")
    if plan_id is not None:
        plan = _require_plan(db, plan_id)
        query = query.filter(WorkoutSession.plan_id == plan.id)
    session = query.order_by(WorkoutSession.started_at.desc()).first()
    if session is None:
        return {"session": None, "message": "没有活跃的训练会话"}
    return {"session": session_to_v31_dict(session), "plan": plan_to_v31_dict(session.plan)}


@app.get("/api/session/{session_id}/summary")
def get_session_summary(session_id: int, db: Session = Depends(get_db)) -> dict:
    """Generate a training summary for a completed session.

    If AI is configured, includes AI-generated adjustments.
    If AI is not configured, returns a local summary based on completion data.
    """
    session = _require_session(db, session_id)
    plan_data = plan_to_v31_dict(session.plan)
    session_data = session_to_v31_dict(session)

    # Local summary always available
    completed = sum(1 for r in session.records if r.status == "completed")
    skipped = sum(1 for r in session.records if r.status == "skipped")
    total = len(session.records) or 1
    score = round((completed / total) * 100)

    local_summary = {
        "session_id": session.id,
        "date": session.plan.plan_date.isoformat() if session.plan else None,
        "score": score,
        "completed_exercises": completed,
        "skipped_exercises": skipped,
        "total_exercises": total,
        "duration_minutes": None,  # Could be calculated from record timestamps
        "adjustments": ["保持当前低强度节奏", "下次训练优先保证动作质量"],
        "suggestion_draft": None,
    }

    # Try AI analysis if configured
    try:
        ai_analysis = _run_session_analysis(session)
        if ai_analysis:
            local_summary["ai_analysis"] = ai_analysis
            local_summary["ai_generated"] = True
    except Exception:
        local_summary["ai_generated"] = False

    # Generate suggestion draft for next plan
    local_summary["suggestion_draft"] = {
        "note": "基于本次完成情况，下次继续当前计划节奏",
        "completed_count": completed,
        "skipped_count": skipped,
    }

    return {"status": "ok", "summary": local_summary}


@app.post("/api/ai/feedback")
def ai_feedback(payload: AIFeedbackRequest, db: Session = Depends(get_db)) -> dict:
    session = _require_session(db, payload.session_id)
    session.rating = payload.rating
    session.ai_feedback = payload.comment
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    return {
        "status": "feedback_recorded",
        "session_id": session.id,
        "rating": session.rating,
        "comment": session.ai_feedback,
    }


@app.get("/api/ai/health")
def ai_health():
    return ai_service.PlanGenerator(config_func=_ai_config).health()


def _public_provider_config(config: dict) -> dict:
    return {
        "provider": config["provider"],
        "active_provider": config["provider"],
        "source": config["source"],
        "enabled": bool(config["enabled"]),
        "key_configured": bool(config["api_key"]),
        "base_url": config["base_url"],
        "model": config["model"],
        "schema_version": ai_service.AI_SCHEMA_VERSION,
    }


@app.get("/api/ai/models")
def ai_models() -> dict:
    try:
        return ai_service.provider_models()
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=f"AI provider 配置不可用：{exc}") from exc


@app.get("/api/ai/provider")
def ai_provider() -> dict:
    try:
        return _public_provider_config(ai_service.active_provider_config())
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=f"AI provider 配置不可用：{exc}") from exc


@app.put("/api/ai/provider")
def update_ai_provider(payload: AIProviderRequest) -> dict:
    try:
        config = ai_service.save_provider_config(
            payload.provider,
            payload.api_key,
            payload.base_url,
            payload.model,
        )
        return _public_provider_config(config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=f"AI provider 保存失败：{exc}") from exc


@app.post("/api/ai/chat")
def ai_chat(payload: AIChatRequest) -> dict:
    if not payload.messages:
        raise HTTPException(status_code=422, detail="messages 不能为空")
    messages = [message.model_dump() for message in payload.messages]
    try:
        config = ai_service.active_provider_config()
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=f"AI provider 配置不可用：{exc}") from exc
    if payload.provider and payload.provider != config["provider"]:
        raise HTTPException(status_code=409, detail="请求 provider 不是当前唯一生效 provider")
    model = payload.model or config["model"]
    if config["enabled"]:
        try:
            content = ai_service.call_ai_messages(
                config["base_url"], config["api_key"], model, messages, timeout=60
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=f"AI 调用失败：{exc}") from exc
        source = "api"
    else:
        last_user = next((item["content"] for item in reversed(messages) if item["role"] == "user"), "")
        content = f"本地备用建议 · 非 AI 模型回复：已收到“{str(last_user)[:120]}”。"
        source = "local-demo"
    return {
        "status": "ok",
        "source": source,
        "provider": config["provider"],
        "model": model or None,
        "message": {"role": "assistant", "content": content},
        "messages": messages,
    }


def _fallback_ai_preview(prompt: str) -> dict:
    return ai_service.PlanGenerator().fallback(prompt)


def _draft_response(draft: dict, ai_enabled: bool = True) -> dict:
    return ai_service.draft_response(draft, ai_enabled=ai_enabled)


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
    try:
        return ai_service.PlanGenerator(chat_func=_call_ai_chat, config_func=_ai_config).generate(payload.prompt)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"AI 调用失败，未生成正式导入结果：{exc}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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
    try:
        return ai_service.VideoRecommender(chat_func=_call_ai_chat, config_func=_ai_config).suggest(
            payload.exercise_name or "",
            payload.description or "",
            payload.notes or "",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"AI 调用失败，未生成视频建议：{exc}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
