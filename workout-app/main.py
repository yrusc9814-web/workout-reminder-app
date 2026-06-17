import re
from calendar import monthrange
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

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


def post_json(url: str, payload: dict, headers: Optional[dict] = None) -> tuple[int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    request = Request(url, data=data, headers=request_headers, method="POST")
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, body
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return exc.code, body
    except URLError as exc:
        raise RuntimeError(f"钉钉请求失败：{exc}") from exc

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
        status_code, body = post_json(todo_url, todo_payload, headers=headers)
    except RuntimeError as exc:
        return {
            "channel": "dingtalk_todo",
            "enabled": True,
            "created": False,
            "status": "failed",
            "error": str(exc),
            "payload": todo_payload,
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
    return {
        "channel": "dingtalk_todo",
        "enabled": True,
        "created": created,
        "status": status,
        "http_status": status_code,
        "response": body,
        "permission": permission,
        "payload": todo_payload,
    }


# ---------------------------------------------------------------------------
# AI 辅助能力（第二阶段）
# ---------------------------------------------------------------------------

BILIBILI_DOMAINS = {"bilibili.com", "www.bilibili.com", "b23.tv"}
FORBIDDEN_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


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

    if "version" not in draft:
        errors.append("缺少 version 字段")

    exercises = draft.get("exercises", [])
    if not isinstance(exercises, list):
        errors.append("exercises 必须是数组")
    else:
        if len(exercises) == 0:
            errors.append("exercises 至少需要 1 个动作")

        exercise_ids = set()
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
            if not exercise.get("name") or not isinstance(exercise["name"], str):
                errors.append(f"动作 {eid or i+1} 缺少 name 字段")

            videos = exercise.get("videos", [])
            if isinstance(videos, list):
                default_count = 0
                for v in videos:
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
            if not isinstance(entry, dict):
                errors.append(f"日期 {ds} 的计划格式错误")
                continue
            if entry.get("type") == "training" and not entry.get("templateId"):
                errors.append(f"日期 {ds} 是训练日但缺少 templateId")

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


@app.get("/api/ai/health")
def ai_health():
    base_url = os.environ.get("WORKOUT_AI_BASE_URL", "")
    api_key = os.environ.get("WORKOUT_AI_API_KEY", "")
    model = os.environ.get("WORKOUT_AI_MODEL", "gpt-4o-mini")
    key_configured = bool(base_url and api_key)
    return {
        "enabled": key_configured,
        "provider": "openai-compatible",
        "model": model if key_configured else "",
        "key_configured": key_configured,
        "message": "AI 服务已配置" if key_configured
        else "AI 服务未配置，请设置环境变量 WORKOUT_AI_BASE_URL 和 WORKOUT_AI_API_KEY",
    }


@app.post("/api/ai/import-plan")
def ai_import_plan(payload: AIImportRequest):
    base_url = os.environ.get("WORKOUT_AI_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("WORKOUT_AI_API_KEY", "")
    model = os.environ.get("WORKOUT_AI_MODEL", "gpt-4o-mini")

    if not base_url or not api_key:
        raise HTTPException(
            status_code=400,
            detail="AI 服务未配置，请设置 WORKOUT_AI_BASE_URL 和 WORKOUT_AI_API_KEY",
        )

    system_prompt = """你是一个运动训练计划生成助手。根据用户描述生成结构化训练数据 JSON。

输出格式必须严格遵循：
{
  "version": "1.0",
  "source": "ai_generated",
  "exercises": [
    {
      "id": "英文ID", "name": "动作名称", "category": "分类",
      "bodyParts": ["部位"], "difficulty": "低/中/高",
      "defaultSets": 3, "defaultReps": "12次", "durationSeconds": null,
      "notes": "说明", "tips": ["要点1"],
      "videos": [{"id":"vid","title":"标题","platform":"bilibili","url":"https://www.bilibili.com/video/BVxxx","isDefault":true,"remark":""}]
    }
  ],
  "templates": [
    { "id": "模板ID", "name": "名称", "description": "", "exerciseIds": ["动作ID"] }
  ],
  "schedule": {
    "YYYY-MM-DD": { "type": "training", "templateId": "模板ID", "status": "pending", "note": "" }
  }
}

要求：
- exercises 至少 1 个动作，每个动作必须有 id（英文字母数字下划线）和 name
- 默认视频 URL 必须是 bilibili.com 或 b23.tv
- templates 至少 1 个，exerciseIds 必须引用存在的动作 ID
- schedule 日期只包含训练日
- 所有文本使用中文"""

    try:
        content = _call_ai_chat(base_url, api_key, model, system_prompt, payload.prompt)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

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

    # 转换 schedule 为 plans 数组
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
        "draft": {
            "exercises": draft.get("exercises", []),
            "templates": draft.get("templates", []),
            "plans": plans_list,
        },
        "warnings": [],
    }


@app.post("/api/ai/suggest-bilibili-video")
def ai_suggest_bilibili_video(payload: AISuggestVideoRequest):
    base_url = os.environ.get("WORKOUT_AI_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("WORKOUT_AI_API_KEY", "")
    model = os.environ.get("WORKOUT_AI_MODEL", "gpt-4o-mini")

    if not base_url or not api_key:
        raise HTTPException(
            status_code=400,
            detail="AI 服务未配置，请设置 WORKOUT_AI_BASE_URL 和 WORKOUT_AI_API_KEY",
        )

    ex_name = payload.exercise_name or ""
    ex_desc = payload.description or ""
    ex_notes = payload.notes or ""

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
        content = _call_ai_chat(base_url, api_key, model, system_prompt, user_prompt, timeout=30)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

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

    # 校验所有 searchUrls 必须在 Bilibili 白名单内
    for url in search_urls:
        if not _validate_bilibili_url(url):
            raise HTTPException(
                status_code=422,
                detail=f"AI 返回了非 Bilibili 视频链接（已拒绝）：{url}",
            )

    query = keywords[0] if keywords else ex_name
    search_url = search_urls[0] if search_urls else (
        f"https://search.bilibili.com/all?keyword={query}"
    )

    return {
        "status": "ok",
        "query": query,
        "search_url": search_url,
        "candidates": search_urls,
    }
