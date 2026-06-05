from calendar import monthrange
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import (
    Base,
    Reminder,
    Setting,
    WorkoutLog,
    WorkoutPlan,
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
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


class LogPayload(BaseModel):
    plan_id: int
    notes: Optional[str] = None


class SettingPayload(BaseModel):
    key: str = Field(min_length=1)
    value: str


class ReminderPayload(BaseModel):
    title: Optional[str] = None
    message: Optional[str] = None


def as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_month_token(month: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM") from exc
    return parsed.year, parsed.month


def resolve_year_month(year: Optional[int], month: Optional[str]) -> tuple[int, int]:
    if month is None:
        raise HTTPException(status_code=422, detail="month is required")

    if "-" in month:
        if year is not None:
            raise HTTPException(status_code=422, detail="use either year+month or month=YYYY-MM")
        return parse_month_token(month)

    try:
        month_num = int(month)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="month must be 1-12 or YYYY-MM") from exc

    if not 1 <= month_num <= 12:
        raise HTTPException(status_code=422, detail="month must be between 1 and 12")

    if year is None:
        raise HTTPException(status_code=422, detail="year is required when month is numeric")

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
        raise HTTPException(status_code=404, detail="Plan not found")

    row = WorkoutLog(plan_id=plan_id, action=state, status=state, notes=notes)
    db.add(row)
    db.commit()
    db.refresh(row)
    return log_item(row)


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
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")

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
def send_dingtalk_reminder(payload: ReminderPayload) -> dict:
    return {
        "channel": "dingtalk",
        "enabled": False,
        "mock": True,
        "title": payload.title,
        "message": payload.message,
        "status": "not_sent",
    }
