from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional
from pathlib import Path

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

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    seed_database()


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


def plan_item(plan: Optional[WorkoutPlan], day: date) -> dict:
    if not plan:
        return {
            "date": day.isoformat(),
            "plan": None,
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


@app.get("/api/plans/today")
def today(db: Session = Depends(get_db)) -> dict:
    day = date.today()
    plan = db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == day).first()
    return plan_item(plan, day)


@app.get("/api/plans/month")
def month(
    year: int = Query(..., ge=1),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> dict:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    rows = range_rows(db, start, end)
    days = []
    current = start
    while current <= end:
        days.append(plan_item(rows.get(current), current))
        current += timedelta(days=1)
    return {"year": year, "month": month, "days": days}


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


@app.get("/api/calendar")
def calendar_view(
    year: Optional[int] = Query(None, ge=1),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
) -> dict:
    today_date = date.today()
    year = year or today_date.year
    month = month or today_date.month

    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
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
    return {"year": year, "month": month, "days": days}


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
