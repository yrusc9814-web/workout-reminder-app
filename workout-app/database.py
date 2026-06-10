import os
from calendar import monthrange
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.sql import func

DATABASE_PATH = os.environ.get(
    "WORKOUT_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "workout.db"),
)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class WorkoutPlan(Base):
    __tablename__ = "workout_plans"

    id = Column(Integer, primary_key=True, index=True)
    plan_date = Column(Date, nullable=False, unique=True, index=True)
    title = Column(String(120), nullable=False)
    is_training_day = Column(Boolean, nullable=False, default=False)
    focus = Column(String(160), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    exercises = relationship(
        "WorkoutExercise",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="WorkoutExercise.sort_order",
    )
    logs = relationship("WorkoutLog", back_populates="plan", cascade="all, delete-orphan")


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"
    __table_args__ = (
        UniqueConstraint("plan_id", "sort_order", name="uq_workout_exercises_plan_sort"),
    )

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("workout_plans.id"), nullable=False, index=True)
    sort_order = Column(Integer, nullable=False)
    name = Column(String(140), nullable=False)
    description = Column(Text, nullable=False)
    sets = Column(Integer, nullable=False, default=1)
    duration_seconds = Column(Integer, nullable=True)
    reps = Column(Integer, nullable=True)
    video_url = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    plan = relationship("WorkoutPlan", back_populates="exercises")


class WorkoutLog(Base):
    __tablename__ = "workout_logs"
    __table_args__ = (
        CheckConstraint(
            "action IN ('completed', 'skipped', 'postponed')",
            name="ck_workout_logs_action",
        ),
        CheckConstraint(
            "status IN ('completed', 'skipped', 'postponed')",
            name="ck_workout_logs_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("workout_plans.id"), nullable=False, index=True)
    log_date = Column(Date, nullable=False, default=date.today)
    action = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    plan = relationship("WorkoutPlan", back_populates="logs")


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("workout_plans.id"), nullable=True, index=True)
    reminder_date = Column(Date, nullable=False, index=True)
    message = Column(String(240), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(120), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


TRAINING_DATES = {
    date(2026, 5, 1),
    date(2026, 5, 4),
    date(2026, 5, 6),
    date(2026, 5, 8),
    date(2026, 5, 11),
    date(2026, 5, 13),
    date(2026, 5, 15),
    date(2026, 5, 18),
    date(2026, 5, 20),
    date(2026, 5, 22),
    date(2026, 5, 25),
    date(2026, 5, 27),
    date(2026, 5, 29),
}

SEED_MONTHS = [(2026, 5), (2026, 6), (2026, 7), (2026, 8)]
FUTURE_TRAINING_WEEKDAYS = {0, 2, 4}  # Monday, Wednesday, Friday


def _future_training_dates():
    training_dates = set()
    for year, month in SEED_MONTHS:
        if year == 2026 and month == 5:
            continue
        for day in range(1, monthrange(year, month)[1] + 1):
            plan_date = date(year, month, day)
            if plan_date.weekday() in FUTURE_TRAINING_WEEKDAYS:
                training_dates.add(plan_date)
    return training_dates


TRAINING_DATES.update(_future_training_dates())

TRAINING_EXERCISES = [
    {
        "sort_order": 1,
        "name": "Supine pelvic clock",
        "video_url": "https://www.youtube.com/results?search_query=supine+pelvic+clock+exercise",
        "description": "Small, slow pelvic tilts while lying down to improve hip awareness and gentle control.",
        "sets": 1,
        "duration_seconds": 180,
        "reps": None,
    },
    {
        "sort_order": 2,
        "name": "Supported bridge hold",
        "video_url": "https://www.youtube.com/results?search_query=supported+bridge+hold+exercise",
        "description": "Gentle hip lift with short holds, stopping before strain or breath holding.",
        "sets": 2,
        "duration_seconds": 20,
        "reps": None,
    },
    {
        "sort_order": 3,
        "name": "Side-lying hip abduction",
        "video_url": "https://www.youtube.com/results?search_query=side+lying+hip+abduction+exercise",
        "description": "Small-range side lift for hip stability with a relaxed pace and neutral pelvis.",
        "sets": 2,
        "duration_seconds": None,
        "reps": 6,
    },
    {
        "sort_order": 4,
        "name": "Dead bug heel taps",
        "video_url": "https://www.youtube.com/results?search_query=dead+bug+heel+taps+exercise",
        "description": "Alternating heel taps with steady breathing and light abdominal bracing.",
        "sets": 2,
        "duration_seconds": None,
        "reps": 6,
    },
    {
        "sort_order": 5,
        "name": "Seated hip march",
        "video_url": "https://www.youtube.com/results?search_query=seated+hip+march+exercise",
        "description": "Slow alternating knee lifts while seated, keeping the trunk quiet and effort easy.",
        "sets": 2,
        "duration_seconds": None,
        "reps": 6,
    },
]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema_columns():
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("workout_exercises")}
    if "video_url" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE workout_exercises ADD COLUMN video_url VARCHAR(500)"))


def create_tables():
    Base.metadata.create_all(bind=engine)
    ensure_schema_columns()


def _seed_plan(db, plan_date, is_training_day):
    title = "Hip stability and core control" if is_training_day else "Rest day"
    focus = "Low-volume hip stability and core control" if is_training_day else "Recovery"
    notes = (
        "Keep effort easy, controlled, and pain-free."
        if is_training_day
        else "Rest and normal gentle movement only."
    )

    plan = db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == plan_date).one_or_none()
    if plan is None:
        plan = WorkoutPlan(
            plan_date=plan_date,
            title=title,
            is_training_day=is_training_day,
            focus=focus,
            notes=notes,
        )
        db.add(plan)
        db.flush()
    else:
        plan.title = title
        plan.is_training_day = is_training_day
        plan.focus = focus
        plan.notes = notes

    if not is_training_day:
        for exercise in list(plan.exercises):
            db.delete(exercise)
        return

    existing = {exercise.sort_order: exercise for exercise in plan.exercises}
    wanted_orders = {item["sort_order"] for item in TRAINING_EXERCISES}

    for exercise in list(plan.exercises):
        if exercise.sort_order not in wanted_orders:
            db.delete(exercise)

    for item in TRAINING_EXERCISES:
        exercise = existing.get(item["sort_order"])
        if exercise is None:
            exercise = WorkoutExercise(plan_id=plan.id, sort_order=item["sort_order"])
            db.add(exercise)

        exercise.name = item["name"]
        exercise.description = item["description"]
        exercise.sets = item["sets"]
        exercise.duration_seconds = item["duration_seconds"]
        exercise.reps = item["reps"]
        exercise.video_url = item["video_url"]


def seed_database():
    db = SessionLocal()
    try:
        for year, month in SEED_MONTHS:
            for day in range(1, monthrange(year, month)[1] + 1):
                plan_date = date(year, month, day)
                _seed_plan(db, plan_date, plan_date in TRAINING_DATES)

        setting = db.query(Setting).filter(Setting.key == "seed_month").one_or_none()
        if setting is None:
            setting = Setting(key="seed_month", value="2026-05..2026-08")
            db.add(setting)
        else:
            setting.value = "2026-05..2026-08"

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    create_tables()
    seed_database()
