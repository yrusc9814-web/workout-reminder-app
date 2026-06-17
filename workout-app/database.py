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
    Table,
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
    sessions = relationship("WorkoutSession", back_populates="plan", cascade="all, delete-orphan")


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"
    __table_args__ = (
        UniqueConstraint("plan_id", "sort_order", name="uq_workout_exercises_plan_sort"),
    )

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("workout_plans.id"), nullable=False, index=True)
    exercise_id = Column(Integer, ForeignKey("exercises.id"), nullable=True, index=True)
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


# ── Exercise library (standalone) ──────────────────────────────────────────

template_exercises = Table(
    "template_exercises", Base.metadata,
    Column("template_id", Integer, ForeignKey("templates.id", ondelete="CASCADE"), primary_key=True),
    Column("exercise_id", Integer, ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True),
)


class Exercise(Base):
    """Standalone exercise library — the canonical list of all exercises."""
    __tablename__ = "exercises"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(140), nullable=False, index=True)
    category = Column(String(80), nullable=False, default="")
    body_parts = Column(String(240), nullable=False, default="")
    difficulty = Column(String(20), nullable=False, default="低")
    default_sets = Column(Integer, nullable=False, default=3)
    default_reps = Column(String(20), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    tips = Column(Text, nullable=True)
    video_url = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Template(Base):
    """Training template — groups exercises into a named routine."""
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(140), nullable=False, index=True)
    description = Column(Text, nullable=True)
    difficulty = Column(String(20), nullable=False, default="低强度")
    estimated_minutes = Column(Integer, nullable=False, default=30)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    exercises = relationship(
        "Exercise",
        secondary=template_exercises,
        lazy="selectin",
    )


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'cancelled')",
            name="ck_workout_sessions_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("workout_plans.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="in_progress", index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    rating = Column(Integer, nullable=True)
    ai_feedback = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    plan = relationship("WorkoutPlan", back_populates="sessions")
    records = relationship(
        "SessionRecord",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionRecord.id",
    )


class SessionRecord(Base):
    __tablename__ = "session_records"
    __table_args__ = (
        UniqueConstraint("session_id", "exercise_id", name="uq_session_records_session_exercise"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'skipped')",
            name="ck_session_records_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("workout_sessions.id"), nullable=False, index=True)
    exercise_id = Column(Integer, ForeignKey("exercises.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")
    sets_completed = Column(Integer, nullable=True)
    reps_completed = Column(String(40), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    session = relationship("WorkoutSession", back_populates="records")
    exercise = relationship("Exercise")


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
        "name": "仰卧骨盆时钟",
        "video_url": "https://www.bilibili.com/video/BV1X625B5EWd/",
        "description": "仰卧屈膝，想象骨盆是一只时钟，缓慢做前后、左右和绕圈倾斜，找回髋部感知与骨盆控制。",
        "sets": 1,
        "duration_seconds": 180,
        "reps": None,
    },
    {
        "sort_order": 2,
        "name": "支撑臀桥停留",
        "video_url": "https://www.bilibili.com/video/BV1Jg4y1z7Nm/",
        "description": "脚掌踩稳，轻轻抬起髋部并短暂停留，保持呼吸顺畅，不憋气、不顶腰。",
        "sets": 2,
        "duration_seconds": 20,
        "reps": None,
    },
    {
        "sort_order": 3,
        "name": "侧卧髋外展",
        "video_url": "https://www.bilibili.com/video/BV1No4y1h7NH/",
        "description": "侧卧保持骨盆稳定，小幅抬起上侧腿，节奏放慢，重点感受臀中肌发力。",
        "sets": 2,
        "duration_seconds": None,
        "reps": 6,
    },
    {
        "sort_order": 4,
        "name": "死虫式脚跟点地",
        "video_url": "https://www.bilibili.com/video/BV1Bu411V7rW/",
        "description": "仰卧收紧核心，左右交替让脚跟轻点地面，保持腰背稳定和呼吸连续。",
        "sets": 2,
        "duration_seconds": None,
        "reps": 6,
    },
    {
        "sort_order": 5,
        "name": "坐姿抬腿",
        "video_url": "https://www.bilibili.com/video/BV1Rv4y1d7XM/",
        "description": "坐稳后左右交替抬膝，躯干保持安静，动作慢而可控，避免耸肩或后仰。",
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
    title = "髋部稳定与核心控制" if is_training_day else "恢复日"
    focus = "低强度髋部稳定 + 核心控制" if is_training_day else "恢复与轻量活动"
    notes = (
        "全程保持轻松、可控、无疼痛；如果出现不适，立即停止。"
        if is_training_day
        else "今天不安排正式训练，保持散步、拉伸等温和活动即可。"
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


SEED_EXERCISES = [
    {"name": "仰卧骨盆时钟", "category": "核心控制", "body_parts": "核心", "difficulty": "低", "default_sets": 1, "default_reps": None, "duration_seconds": 180, "notes": "仰卧屈膝，想象骨盆是一只时钟，缓慢做前后、左右和绕圈倾斜", "tips": "慢一点|不要憋气|感受骨盆微动", "video_url": "https://www.bilibili.com/video/BV1X625B5EWd/"},
    {"name": "支撑臀桥停留", "category": "髋部稳定", "body_parts": "臀部,核心", "difficulty": "低", "default_sets": 2, "default_reps": None, "duration_seconds": 20, "notes": "脚掌踩稳，轻轻抬起髋部并短暂停留", "tips": "不顶腰|保持呼吸|收紧臀部", "video_url": "https://www.bilibili.com/video/BV1Jg4y1z7Nm/"},
    {"name": "侧卧髋外展", "category": "髋部稳定", "body_parts": "臀部,腿部", "difficulty": "低", "default_sets": 2, "default_reps": "6次/侧", "duration_seconds": None, "notes": "侧卧保持骨盆稳定，小幅抬起上侧腿", "tips": "骨盆稳定|节奏放慢", "video_url": "https://www.bilibili.com/video/BV1No4y1h7NH/"},
    {"name": "死虫式脚跟点地", "category": "核心控制", "body_parts": "核心", "difficulty": "低", "default_sets": 2, "default_reps": "6次/侧", "duration_seconds": None, "notes": "仰卧收紧核心，左右交替让脚跟轻点地面", "tips": "腰背贴地|均匀呼吸", "video_url": "https://www.bilibili.com/video/BV1Bu411V7rW/"},
    {"name": "坐姿抬腿", "category": "髋部稳定", "body_parts": "髋部,核心", "difficulty": "低", "default_sets": 2, "default_reps": "6次/侧", "duration_seconds": None, "notes": "坐稳后左右交替抬膝，躯干保持安静", "tips": "不耸肩|不后仰", "video_url": "https://www.bilibili.com/video/BV1Rv4y1d7XM/"},
]

SEED_TEMPLATES = [
    {"name": "髋部稳定与核心控制", "description": "专注核心稳定与髋部控制，适合日常训练与康复巩固。", "difficulty": "低强度", "estimated_minutes": 35, "exercise_names": ["仰卧骨盆时钟", "支撑臀桥停留", "侧卧髋外展", "死虫式脚跟点地", "坐姿抬腿"]},
]


def _seed_exercise_library(db):
    """Seed the standalone exercise library and templates if empty."""
    if db.query(Exercise).count() > 0:
        return
    for item in SEED_EXERCISES:
        ex = Exercise(**item)
        db.add(ex)
    db.flush()

    name_map = {ex.name: ex for ex in db.query(Exercise).all()}
    for tdata in SEED_TEMPLATES:
        tmpl = Template(
            name=tdata["name"],
            description=tdata["description"],
            difficulty=tdata["difficulty"],
            estimated_minutes=tdata["estimated_minutes"],
        )
        db.add(tmpl)
        db.flush()
        enames = tdata["exercise_names"]
        tmpl.exercises = [name_map[n] for n in enames if n in name_map]


def seed_database():
    db = SessionLocal()
    try:
        for year, month in SEED_MONTHS:
            for day in range(1, monthrange(year, month)[1] + 1):
                plan_date = date(year, month, day)
                _seed_plan(db, plan_date, plan_date in TRAINING_DATES)

        _seed_exercise_library(db)

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
