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
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True, index=True)
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
    template = relationship("Template")


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
    # Preserve a user/import supplied display specification verbatim.
    spec = Column(String(240), nullable=True)
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
    benefit = Column(Text, nullable=True)
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
        # Database-level guard: only one active session per plan
        # SQLite partial unique index via UniqueConstraint with condition not directly
        # supported, so we use a trigger or application-level check + DB constraint
    )

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("workout_plans.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="in_progress", index=True)
    # Frozen action snapshot for context validation after a plan is edited.
    # NULL preserves legacy/imported sessions created before VAN-17.
    plan_action_fingerprint = Column(String(64), nullable=True, index=True)
    # Legacy/imported sessions may have unknown historical start time.
    # Normal API-created sessions explicitly provide a real timestamp.
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
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
    exercise_id = Column(Integer, ForeignKey("exercises.id"), nullable=True, index=True)
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
        # Session-backed logs must remain distinct when a historical session
        # is later found to belong to a different action snapshot.  The
        # coalesced SQLite index added by ensure_schema_columns keeps
        # standalone (NULL session_id) logs idempotent as well.
        UniqueConstraint(
            "plan_id",
            "action",
            "log_date",
            "session_id",
            name="uq_workout_logs_plan_action_date_session",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("workout_plans.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("workout_sessions.id"), nullable=True, index=True)
    # Snapshot fingerprint for legacy completion routes that have no session.
    # NULL preserves rows imported from pre-VAN-17 databases.
    plan_action_fingerprint = Column(String(64), nullable=True, index=True)
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


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("exercise_name", name="uq_favorites_exercise_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    exercise_name = Column(String(140), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MigrationLog(Base):
    __tablename__ = "migration_logs"

    id = Column(Integer, primary_key=True, index=True)
    migration_name = Column(String(120), nullable=False, index=True)
    source_sha256 = Column(String(64), nullable=True)
    preview_hash = Column(String(64), nullable=True, index=True)
    affected_fingerprint = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)
    applied_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


CURRENT_SCHEMA_VERSION = 1


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


def _rebuild_workout_sessions_with_nullable_started_at():
    """Rebuild legacy SQLite sessions without losing rows or IDs.

    SQLite cannot ALTER a NOT NULL column to nullable in place. This is a
    schema-only migration; no business values are transformed and the
    schema_version marker is still written later by migrate_database().
    """
    inspector = inspect(engine)
    if "workout_sessions" not in inspector.get_table_names():
        return False
    columns = {column["name"]: column for column in inspector.get_columns("workout_sessions")}
    started = columns.get("started_at")
    if not started or started.get("nullable", True):
        return False

    raw = engine.raw_connection()
    cursor = raw.cursor()
    try:
        raw.isolation_level = None
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        index_names = [row[1] for row in cursor.execute("PRAGMA index_list(workout_sessions)").fetchall()]
        for index_name in index_names:
            cursor.execute(f' DROP INDEX IF EXISTS "{index_name.replace(chr(34), chr(34) * 2)}"')
        before_count = cursor.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0]
        fingerprint_select = "plan_action_fingerprint" if "plan_action_fingerprint" in columns else "NULL"
        cursor.execute("""
            CREATE TABLE workout_sessions_v25_new (
                id INTEGER NOT NULL PRIMARY KEY,
                plan_id INTEGER NOT NULL,
                status VARCHAR(20) NOT NULL,
                plan_action_fingerprint VARCHAR(64) NULL,
                started_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME NULL,
                notes TEXT NULL,
                rating INTEGER NULL,
                ai_feedback TEXT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NULL,
                CONSTRAINT ck_workout_sessions_status
                    CHECK (status IN ('in_progress', 'completed', 'cancelled')),
                FOREIGN KEY(plan_id) REFERENCES workout_plans(id)
            )
        """)
        cursor.execute(f"""
            INSERT INTO workout_sessions_v25_new
                (id, plan_id, status, plan_action_fingerprint, started_at, completed_at, notes, rating,
                 ai_feedback, created_at, updated_at)
            SELECT id, plan_id, status, {fingerprint_select}, started_at, completed_at, notes, rating,
                   ai_feedback, created_at, updated_at
            FROM workout_sessions
        """)
        cursor.execute("SELECT COUNT(*) FROM workout_sessions_v25_new")
        after_count = cursor.fetchone()[0]
        if before_count != after_count:
            raise RuntimeError(
                f"workout_sessions rebuild row loss: before={before_count}, after={after_count}"
            )
        cursor.execute("DROP TABLE workout_sessions")
        cursor.execute("ALTER TABLE workout_sessions_v25_new RENAME TO workout_sessions")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_workout_sessions_id ON workout_sessions(id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_workout_sessions_plan_id ON workout_sessions(plan_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_workout_sessions_status ON workout_sessions(status)")
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_one_active_session_per_plan "
            "ON workout_sessions(plan_id) WHERE status = 'in_progress'"
        )
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("COMMIT")
        return True
    except Exception:
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
            raw.close()


def _rebuild_workout_logs_with_session_scoped_uniqueness():
    """Migrate legacy logs so each completed session can keep its own fact.

    Older databases enforced uniqueness on ``plan_id + action + log_date``.
    That made a historical completed session prevent a later, explicitly
    started session for the same plan/date from recording its own completion
    after a repaired action snapshot.  Preserve every existing row while
    moving uniqueness to include ``session_id``.
    """
    inspector = inspect(engine)
    if "workout_logs" not in inspector.get_table_names():
        return False
    raw = engine.raw_connection()
    cursor = raw.cursor()
    try:
        table_sql = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'workout_logs'"
        ).fetchone()
        normalized_sql = (table_sql[0] if table_sql else "").lower().replace("\n", " ")
        legacy_constraint = (
            "uq_workout_logs_plan_action_date" in normalized_sql
            and "uq_workout_logs_plan_action_date_session" not in normalized_sql
        ) or "unique (plan_id, action, log_date)" in normalized_sql
        if not legacy_constraint:
            return False

        raw.isolation_level = None
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(workout_logs)").fetchall()}
        fingerprint_select = "plan_action_fingerprint" if "plan_action_fingerprint" in existing_columns else "NULL"
        before_count = cursor.execute("SELECT COUNT(*) FROM workout_logs").fetchone()[0]
        cursor.execute("""
            CREATE TABLE workout_logs_v25_new (
                id INTEGER NOT NULL PRIMARY KEY,
                plan_id INTEGER NOT NULL,
                session_id INTEGER NULL,
                plan_action_fingerprint VARCHAR(64) NULL,
                log_date DATE NOT NULL,
                action VARCHAR(20) NOT NULL,
                status VARCHAR(20) NOT NULL,
                notes TEXT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT ck_workout_logs_action
                    CHECK (action IN ('completed', 'skipped', 'postponed')),
                CONSTRAINT ck_workout_logs_status
                    CHECK (status IN ('completed', 'skipped', 'postponed')),
                CONSTRAINT uq_workout_logs_plan_action_date_session
                    UNIQUE (plan_id, action, log_date, session_id),
                FOREIGN KEY(plan_id) REFERENCES workout_plans(id),
                FOREIGN KEY(session_id) REFERENCES workout_sessions(id)
            )
        """)
        cursor.execute(f"""
            INSERT INTO workout_logs_v25_new
                (id, plan_id, session_id, plan_action_fingerprint, log_date, action, status, notes, created_at)
            SELECT id, plan_id, session_id, {fingerprint_select}, log_date, action, status, notes, created_at
            FROM workout_logs
        """)
        after_count = cursor.execute("SELECT COUNT(*) FROM workout_logs_v25_new").fetchone()[0]
        if before_count != after_count:
            raise RuntimeError(
                f"workout_logs rebuild row loss: before={before_count}, after={after_count}"
            )
        cursor.execute("DROP TABLE workout_logs")
        cursor.execute("ALTER TABLE workout_logs_v25_new RENAME TO workout_logs")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_workout_logs_id ON workout_logs(id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_workout_logs_plan_id ON workout_logs(plan_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_workout_logs_session_id ON workout_logs(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_workout_logs_log_date ON workout_logs(log_date)")
        cursor.execute("COMMIT")
        return True
    except Exception:
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
            raw.close()


def ensure_schema_columns():
    _rebuild_workout_sessions_with_nullable_started_at()
    inspector = inspect(engine)
    ws_columns = {column["name"] for column in inspector.get_columns("workout_sessions")}
    if "plan_action_fingerprint" not in ws_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE workout_sessions ADD COLUMN plan_action_fingerprint VARCHAR(64)"))
    # workout_exercises table
    we_columns = {column["name"] for column in inspector.get_columns("workout_exercises")}
    if "video_url" not in we_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE workout_exercises ADD COLUMN video_url VARCHAR(500)"))
    if "spec" not in we_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE workout_exercises ADD COLUMN spec VARCHAR(240)"))
    # exercises table — benefit column
    ex_columns = {column["name"] for column in inspector.get_columns("exercises")}
    if "benefit" not in ex_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE exercises ADD COLUMN benefit TEXT"))
    # workout_plans — template_id FK
    wp_columns = {column["name"] for column in inspector.get_columns("workout_plans")}
    if "template_id" not in wp_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE workout_plans ADD COLUMN template_id INTEGER REFERENCES templates(id)"))
    # workout_logs — session_id FK
    wl_columns = {column["name"] for column in inspector.get_columns("workout_logs")}
    if "session_id" not in wl_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE workout_logs ADD COLUMN session_id INTEGER REFERENCES workout_sessions(id)"))
    _rebuild_workout_logs_with_session_scoped_uniqueness()
    # Legacy compatibility completions store the action snapshot they saw;
    # rows imported from older schemas remain NULL and are preserved as
    # historical facts.
    wl_columns = {column["name"] for column in inspect(engine).get_columns("workout_logs")}
    if "plan_action_fingerprint" not in wl_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE workout_logs ADD COLUMN plan_action_fingerprint VARCHAR(64)"))
    # Keep standalone logs idempotent while allowing separate session-backed
    # facts for the same plan/date after a repaired action snapshot.
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_workout_logs_plan_action_date_session_coalesced "
            "ON workout_logs(plan_id, action, log_date, COALESCE(session_id, 0))"
        ))
    # At most one active session per plan (SQLite partial unique index)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_one_active_session_per_plan "
            "ON workout_sessions(plan_id) WHERE status = 'in_progress'"
        ))


def enable_foreign_keys():
    """Enable SQLite foreign key enforcement on every new connection."""
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()


def create_tables():
    # MUST register foreign_keys listener BEFORE create_all creates any connections
    enable_foreign_keys()
    Base.metadata.create_all(bind=engine)
    ensure_schema_columns()


def _seed_plan(db, plan_date, is_training_day):
    """Create a seed plan ONLY if one does not already exist for this date.

    Populates WorkoutExercise.exercise_id from the Exercise library by name.
    """
    plan = db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == plan_date).one_or_none()
    if plan is not None:
        # NEVER overwrite existing user data — plans that already exist are skipped
        return

    title = "髋部稳定与核心控制" if is_training_day else "恢复日"
    focus = "低强度髋部稳定 + 核心控制" if is_training_day else "恢复与轻量活动"
    notes = (
        "全程保持轻松、可控、无疼痛；如果出现不适，立即停止。"
        if is_training_day
        else "今天不安排正式训练，保持散步、拉伸等温和活动即可。"
    )

    # Link seed training days to the default template when available
    default_template = db.query(Template).filter(Template.name == "髋部稳定与核心控制").first()

    plan = WorkoutPlan(
        plan_date=plan_date,
        title=title,
        is_training_day=is_training_day,
        focus=focus,
        notes=notes,
        template_id=default_template.id if (is_training_day and default_template) else None,
    )
    db.add(plan)
    db.flush()

    if not is_training_day:
        return

    # Name → Exercise.id lookup for setting correct foreign keys
    name_to_exercise_id = {
        row.name: row.id for row in db.query(Exercise).all()
    }

    for item in TRAINING_EXERCISES:
        exercise = WorkoutExercise(
            plan_id=plan.id,
            sort_order=item["sort_order"],
            name=item["name"],
            description=item["description"],
            sets=item["sets"],
            duration_seconds=item["duration_seconds"],
            reps=item["reps"],
            video_url=item["video_url"],
            exercise_id=name_to_exercise_id.get(item["name"]),
        )
        db.add(exercise)


SEED_EXERCISES = [
    {"name": "仰卧骨盆时钟", "category": "核心控制", "body_parts": "核心", "difficulty": "低", "default_sets": 1, "default_reps": None, "duration_seconds": 180, "notes": "仰卧屈膝，想象骨盆是一只时钟，缓慢做前后、左右和绕圈倾斜", "benefit": "主要激活腹横肌与骨盆底肌，改善骨盆前倾，增强腰椎-骨盆带的神经肌肉控制能力，适合久坐人群日常矫正。", "tips": "慢一点|不要憋气|感受骨盆微动", "video_url": "https://www.bilibili.com/video/BV1X625B5EWd/"},
    {"name": "支撑臀桥停留", "category": "髋部稳定", "body_parts": "臀部,核心", "difficulty": "低", "default_sets": 2, "default_reps": None, "duration_seconds": 20, "notes": "脚掌踩稳，轻轻抬起髋部并短暂停留", "benefit": "主要刺激臀大肌与腘绳肌，改善髋伸肌群募集模式，纠正臀部\"失忆症\"，减轻腰椎在日常负重中的压力。", "tips": "不顶腰|保持呼吸|收紧臀部", "video_url": "https://www.bilibili.com/video/BV1Jg4y1z7Nm/"},
    {"name": "侧卧髋外展", "category": "髋部稳定", "body_parts": "臀部,腿部", "difficulty": "低", "default_sets": 2, "default_reps": "6次/侧", "duration_seconds": None, "notes": "侧卧保持骨盆稳定，小幅抬起上侧腿", "benefit": "主要激活臀中肌与髋外展肌群，增强骨盆侧向稳定性，改善步态中髋关节的侧向控制能力。", "tips": "骨盆稳定|节奏放慢", "video_url": "https://www.bilibili.com/video/BV1No4y1h7NH/"},
    {"name": "死虫式脚跟点地", "category": "核心控制", "body_parts": "核心", "difficulty": "低", "default_sets": 2, "default_reps": "6次/侧", "duration_seconds": None, "notes": "仰卧收紧核心，左右交替让脚跟轻点地面", "benefit": "训练核心抗伸展能力，强化腹横肌与多裂肌协同，提升脊柱在四肢运动中的稳定性，减少下背代偿风险。", "tips": "腰背贴地|均匀呼吸", "video_url": "https://www.bilibili.com/video/BV1Bu411V7rW/"},
    {"name": "坐姿抬腿", "category": "髋部稳定", "body_parts": "髋部,核心", "difficulty": "低", "default_sets": 2, "default_reps": "6次/侧", "duration_seconds": None, "notes": "坐稳后左右交替抬膝，躯干保持安静", "benefit": "主要激活髋屈肌群与核心稳定肌群，改善坐姿下的躯干控制能力，增强下肢独立运动时的骨盆稳定性。", "tips": "不耸肩|不后仰", "video_url": "https://www.bilibili.com/video/BV1Rv4y1d7XM/"},
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
    """Seed the database ONLY when it is empty (no WorkoutPlan rows exist).

    Once a user has any plan data, subsequent restarts will NEVER overwrite it.
    This replaces the old behaviour where every startup re-seeded all months.
    """
    db = SessionLocal()
    try:
        existing_plan_count = db.query(WorkoutPlan).count()
        if existing_plan_count > 0:
            # Database already has user data — skip ALL seeding
            return

        # Seed exercise library FIRST so plan seeding can set foreign keys
        _seed_exercise_library(db)

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


def migrate_database():
    """Independent migration — runs on ANY database (not just empty ones).

    Idempotent: running it twice produces the same result with no data changes.
    Only backfills data where a unique match is possible.
    """
    import os
    from collections import defaultdict

    # Consistent pre-migration backup when source DB exists
    backup_info = None
    if os.path.exists(DATABASE_PATH):
        backup_dir = os.path.join(os.path.dirname(DATABASE_PATH), ".tmp", "backups")
        try:
            backup_info = sqlite_backup(DATABASE_PATH, backup_dir)
            if backup_info.get("integrity") != "ok":
                raise RuntimeError(f"pre-migration backup integrity failed: {backup_info.get('integrity')}")
        except Exception as exc:
            # If backup helper is unavailable during early import edge cases, fail closed
            raise RuntimeError(f"pre-migration backup failed: {exc}") from exc

    db = SessionLocal()
    try:
        executed = False

        # 1. Backfill WorkoutExercise.exercise_id from Exercise library by unique name only
        name_groups = defaultdict(list)
        for row in db.query(Exercise).all():
            name_groups[row.name].append(row.id)
        unique_name_map = {name: ids[0] for name, ids in name_groups.items() if len(ids) == 1}
        orphan_wes = db.query(WorkoutExercise).filter(WorkoutExercise.exercise_id.is_(None)).all()
        migrated_we = 0
        ambiguous_we = 0
        for we in orphan_wes:
            matched_id = unique_name_map.get(we.name)
            if matched_id is not None:
                we.exercise_id = matched_id
                migrated_we += 1
                executed = True
            else:
                ambiguous_we += 1
        if migrated_we or ambiguous_we:
            print(f"migrate: backfilled {migrated_we} WorkoutExercise.exercise_id rows" + (f" ({ambiguous_we} ambiguous)" if ambiguous_we else ""))

        # 2. Backfill WorkoutPlan.template_id from Template by matching exercise set
        templates = db.query(Template).all()
        template_exercise_sets = {}
        for t in templates:
            template_exercise_sets[t.id] = frozenset(
                ex.name for ex in t.exercises
            )
        orphan_plans = db.query(WorkoutPlan).filter(
            WorkoutPlan.template_id.is_(None),
            WorkoutPlan.is_training_day == True,
        ).all()
        migrated_plan = 0
        ambiguous_plan = 0
        for plan in orphan_plans:
            plan_exercise_names = frozenset(we.name for we in plan.exercises)
            matches = [
                tid for tid, tnames in template_exercise_sets.items()
                if tnames and tnames == plan_exercise_names
            ]
            if len(matches) == 1:
                plan.template_id = matches[0]
                migrated_plan += 1
                executed = True
            elif plan_exercise_names:
                ambiguous_plan += 1
        if migrated_plan or ambiguous_plan:
            print(f"migrate: backfilled {migrated_plan} WorkoutPlan.template_id rows" + (f" ({ambiguous_plan} ambiguous)" if ambiguous_plan else ""))

        db.flush()
        integrity = db.execute(text("PRAGMA integrity_check")).scalar_one()
        if integrity != "ok":
            raise RuntimeError(f"schema/data migration integrity check failed: {integrity}")

        # The version marker is deliberately the final row mutation in this
        # migration transaction. It is never advanced before data validation.
        version_row = db.query(SchemaVersion).filter(SchemaVersion.id == 1).one_or_none()
        if version_row is None:
            version_row = SchemaVersion(id=1, version=CURRENT_SCHEMA_VERSION)
            db.add(version_row)
        else:
            version_row.version = CURRENT_SCHEMA_VERSION
        db.flush()
        db.commit()
        return {
            "migrated_workout_exercises": migrated_we,
            "ambiguous_workout_exercises": ambiguous_we,
            "migrated_plans": migrated_plan,
            "ambiguous_plans": ambiguous_plan,
            "backup": backup_info,
            "integrity": integrity,
            "schema_version": CURRENT_SCHEMA_VERSION,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def sqlite_backup(source_path: str, dest_dir: str) -> dict:
    """Consistent backup using SQLite backup API. Returns path, SHA-256, size, integrity."""
    import hashlib
    import sqlite3
    import os
    from datetime import datetime

    os.makedirs(dest_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest_path = os.path.join(dest_dir, f"workout-backup-{timestamp}.db")

    src = sqlite3.connect(source_path)
    dst = sqlite3.connect(dest_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    size = os.path.getsize(dest_path)
    sha = hashlib.sha256()
    with open(dest_path, "rb") as f:
        sha.update(f.read())

    # Verify integrity
    verify_conn = sqlite3.connect(dest_path)
    try:
        integrity = verify_conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        verify_conn.close()

    return {"path": dest_path, "sha256": sha.hexdigest(), "size_bytes": size, "integrity": integrity}
