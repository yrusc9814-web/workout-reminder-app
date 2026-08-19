from __future__ import annotations

import base64
import ctypes
import json
import os
import platform
import re
import tempfile
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


BILIBILI_DOMAINS = {"bilibili.com", "www.bilibili.com", "b23.tv", "search.bilibili.com"}
FORBIDDEN_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}
AI_API_KEY_VARS = ("WORKOUT_AI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "WUAPI_API_KEY")
AI_BASE_URL_VARS = ("WORKOUT_AI_BASE_URL", "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL", "WUAPI_BASE_URL")
AI_MODEL_VARS = ("WORKOUT_AI_MODEL", "OPENAI_MODEL", "DEEPSEEK_MODEL", "WUAPI_MODEL")
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_AI_MODEL = "deepseek-v4-flash"
AI_SCHEMA_VERSION = "v1"
KEY_STORE_ENV = "WORKOUT_KEY_STORE"

_PROVIDER_ENV = (
    ("workout", ("WORKOUT_AI_API_KEY",), ("WORKOUT_AI_BASE_URL",), ("WORKOUT_AI_MODEL",)),
    ("openai", ("OPENAI_API_KEY",), ("OPENAI_BASE_URL",), ("OPENAI_MODEL",)),
    ("deepseek", ("DEEPSEEK_API_KEY",), ("DEEPSEEK_BASE_URL",), ("DEEPSEEK_MODEL",)),
    ("wuapi", ("WUAPI_API_KEY",), ("WUAPI_BASE_URL",), ("WUAPI_MODEL",)),
)


def _key_store_path() -> str:
    return os.environ.get(KEY_STORE_ENV, "").strip()


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi_protect(value: bytes) -> str:
    if platform.system() != "Windows":
        raise RuntimeError("DPAPI key_store 仅支持 Windows")
    source_buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    protected = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptProtectData(ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(protected))
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    try:
        return base64.b64encode(ctypes.string_at(protected.pbData, protected.cbData)).decode("ascii")
    finally:
        kernel32.LocalFree(protected.pbData)


def _dpapi_unprotect(value: str) -> bytes:
    if platform.system() != "Windows":
        raise RuntimeError("DPAPI key_store 仅支持 Windows")
    encrypted = base64.b64decode(value.encode("ascii"))
    source_buffer = ctypes.create_string_buffer(encrypted)
    source = _DataBlob(len(encrypted), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    plain = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(plain))
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    try:
        return ctypes.string_at(plain.pbData, plain.cbData)
    finally:
        kernel32.LocalFree(plain.pbData)


def _load_key_store() -> dict:
    path = _key_store_path()
    if not path or not os.path.exists(path):
        return {"active_provider": "", "providers": {}}
    with open(path, "r", encoding="utf-8") as handle:
        envelope = json.load(handle)
    plain = _dpapi_unprotect(str(envelope["protected"]))
    value = json.loads(plain.decode("utf-8"))
    return value if isinstance(value, dict) else {"active_provider": "", "providers": {}}


def _save_key_store(value: dict) -> None:
    path = _key_store_path()
    if not path:
        raise RuntimeError(f"未配置 {KEY_STORE_ENV}")
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    envelope = {"version": 1, "protected": _dpapi_protect(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))}
    fd, temporary = tempfile.mkstemp(prefix=".ai-key-store-", suffix=".tmp", dir=parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle, ensure_ascii=False, sort_keys=True)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _env_provider_config() -> dict | None:
    for provider, key_names, base_names, model_names in _PROVIDER_ENV:
        api_key, key_var = first_env(key_names)
        base_url, base_var = first_env(base_names)
        model, model_var = first_env(model_names)
        if api_key and not base_url and provider == "deepseek":
            base_url, base_var = DEFAULT_DEEPSEEK_BASE_URL, "DEFAULT_DEEPSEEK_BASE_URL"
        if api_key and not model:
            model, model_var = DEFAULT_AI_MODEL, "DEFAULT_AI_MODEL"
        if api_key and base_url and model:
            return {
                "provider": provider,
                "source": "api",
                "api_key": api_key,
                "api_key_var": key_var,
                "base_url": base_url.rstrip("/"),
                "base_url_var": base_var,
                "model": model,
                "model_var": model_var,
                "enabled": True,
            }
    return None


def active_provider_config() -> dict:
    env_config = _env_provider_config()
    if env_config is not None:
        return env_config
    stored = _load_key_store()
    active = str(stored.get("active_provider") or "")
    config = stored.get("providers", {}).get(active, {}) if isinstance(stored.get("providers"), dict) else {}
    if active and isinstance(config, dict) and config.get("api_key") and config.get("base_url") and config.get("model"):
        return {
            "provider": active,
            "source": "api",
            "api_key": str(config["api_key"]),
            "api_key_var": "DPAPI_KEY_STORE",
            "base_url": str(config["base_url"]).rstrip("/"),
            "base_url_var": "DPAPI_KEY_STORE",
            "model": str(config["model"]),
            "model_var": "DPAPI_KEY_STORE",
            "enabled": True,
        }
    return {
        "provider": "local-demo",
        "source": "local-demo",
        "api_key": "",
        "api_key_var": "",
        "base_url": "",
        "base_url_var": "",
        "model": "",
        "model_var": "",
        "enabled": False,
    }


def save_provider_config(provider: str, api_key: str, base_url: str, model: str) -> dict:
    provider = (provider or "").strip().lower()
    if provider == "local-demo":
        stored = _load_key_store()
        stored["active_provider"] = "local-demo"
        _save_key_store(stored)
        return active_provider_config()
    if not re.match(r"^[a-z0-9][a-z0-9_-]{0,40}$", provider):
        raise ValueError("provider 标识不合法")
    if not api_key.strip() or not base_url.strip() or not model.strip():
        raise ValueError("api_key、base_url、model 均不能为空")
    stored = _load_key_store()
    providers = stored.setdefault("providers", {})
    providers[provider] = {"api_key": api_key.strip(), "base_url": base_url.strip().rstrip("/"), "model": model.strip()}
    stored["active_provider"] = provider
    _save_key_store(stored)
    return active_provider_config()


def provider_models() -> dict:
    config = active_provider_config()
    models = [config["model"]] if config["enabled"] else []
    return {"provider": config["provider"], "source": config["source"], "models": models, "active_model": config["model"] or None}


def first_env(names: tuple[str, ...]) -> tuple[str, str]:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    return "", ""


def ai_config() -> dict:
    config = active_provider_config()
    return {
        **config,
        "schema_version": AI_SCHEMA_VERSION,
    }


def safe_base_url_label(base_url: str) -> str:
    if not base_url:
        return ""
    parsed = urlparse(base_url)
    return parsed.netloc or base_url.split("/")[0]


def bilibili_search_url(keyword: str) -> str:
    query = quote((keyword or "训练动作").strip() or "训练动作")
    return f"https://search.bilibili.com/all?keyword={query}"


def validate_bilibili_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if any(host == d or host.endswith("." + d) for d in FORBIDDEN_DOMAINS):
            return False
        if host in BILIBILI_DOMAINS:
            return True
        return any(host.endswith("." + d) for d in BILIBILI_DOMAINS)
    except Exception:
        return False


def validate_ai_draft(draft: dict) -> list[str]:
    errors = []
    if not isinstance(draft, dict):
        return ["AI 返回的数据格式错误，预期为 JSON 对象"]
    if draft.get("schemaVersion") not in {AI_SCHEMA_VERSION, None}:
        errors.append(f"schemaVersion 必须是 {AI_SCHEMA_VERSION}")
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
            for video in exercise.get("videos", []) if isinstance(exercise.get("videos", []), list) else []:
                url = video.get("url", "") if isinstance(video, dict) else ""
                if url and not validate_bilibili_url(url):
                    errors.append(f"动作 {exercise.get('name', eid or i+1)} 的视频 URL 不是合法 Bilibili 链接：{url}")

    templates = draft.get("templates", [])
    template_ids = set()
    if not isinstance(templates, list):
        errors.append("templates 必须是数组")
    else:
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


def call_ai_messages(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    timeout: int = 60,
) -> str:
    chat_url = f"{base_url.rstrip('/')}/chat/completions"
    body_bytes = json.dumps(
        {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    try:
        req = Request(chat_url, data=body_bytes, headers=headers, method="POST")
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
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


def call_ai_chat(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int = 60,
) -> str:
    return call_ai_messages(
        base_url,
        api_key,
        model,
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        timeout=timeout,
    )


def call_openai_compatible(base_url: str, api_key: str, model: str, system_prompt: str, user_prompt: str, timeout: int = 60) -> dict:
    content = call_ai_chat(base_url, api_key, model, system_prompt, user_prompt, timeout=timeout)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI 返回非 JSON：{content[:300]}") from exc


@dataclass
class PlanGenerator:
    chat_func: callable = call_ai_chat
    config_func: callable = ai_config

    def health(self) -> dict:
        config = self.config_func()
        enabled = config["enabled"]
        return {
            "enabled": enabled,
            "provider": "openai-compatible",
            "model": config["model"] if enabled else "",
            "base_url": safe_base_url_label(config["base_url"]) if enabled else "",
            "key_configured": bool(config["api_key"]),
            "schema_version": AI_SCHEMA_VERSION,
            "config_vars": {
                "credential_configured": bool(config["api_key"]),
                "base_url_configured": bool(config["base_url_var"]),
                "model_configured": bool(config["model_var"]),
            },
            "message": "AI 服务已配置" if enabled else "AI 服务未配置，请设置 WORKOUT_AI_API_KEY/WORKOUT_AI_BASE_URL/WORKOUT_AI_MODEL，或兼容的 OPENAI/DEEPSEEK/WUAPI 环境变量",
        }

    def generate(self, prompt: str) -> dict:
        config = self.config_func()
        if not config["enabled"]:
            return self.fallback(prompt)
        content = self.chat_func(config["base_url"], config["api_key"], config["model"], self.prompt(), prompt)
        try:
            draft = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"AI 返回的不是合法 JSON：{str(exc)[:200]}") from exc
        draft.setdefault("schemaVersion", AI_SCHEMA_VERSION)
        errors = validate_ai_draft(draft)
        if errors:
            raise ValueError("AI 生成的草稿校验失败：\n" + "\n".join(errors))
        return draft_response(draft, ai_enabled=True)

    @staticmethod
    def fallback(prompt: str) -> dict:
        query = (prompt or "训练计划").strip()[:80] or "训练计划"
        return {
            "status": "fallback",
            "ai_enabled": False,
            "draft": None,
            "schema_version": AI_SCHEMA_VERSION,
            "fallback": {
                "query": query,
                "search_url": bilibili_search_url(query),
                "message": "AI 服务未配置，已提供 Bilibili 搜索回退链接；不会伪造 AI 结果。",
            },
            "warnings": ["AI 服务未配置，未调用外部模型"],
        }

    @staticmethod
    def prompt() -> str:
        return """你是一个运动训练计划生成助手。根据用户描述生成结构化训练数据 JSON。

输出格式必须严格遵循 schemaVersion=v1。AI 只能输出 draft JSON，禁止写数据库，禁止触发通知。
{
  "schemaVersion": "v1",
  "version": "1.0",
  "source": "ai_generated",
  "title": "训练标题",
  "theme": "训练主题",
  "recommendedDate": "YYYY-MM-DD",
  "exercises": [],
  "templates": [],
  "schedule": {}
}

硬性要求：只输出 JSON；视频只能给 Bilibili 搜索链接或 bilibili.com/b23.tv 链接；所有文本使用中文。"""


@dataclass
class SessionAnalyzer:
    ai_call: callable = call_openai_compatible
    config_func: callable = ai_config

    def analyze(self, session_payload: dict, plan_payload: dict) -> dict:
        config = self.config_func()
        if not config["enabled"]:
            return self.local_analysis(session_payload)
        return self.ai_call(
            config["base_url"],
            config["api_key"],
            config["model"],
            "你是运动训练复审助手，只能给 session 评分、训练调整建议，禁止输出写库指令。请返回 JSON。",
            json.dumps({"session": session_payload, "plan": plan_payload, "schemaVersion": AI_SCHEMA_VERSION}, ensure_ascii=False),
        )

    @staticmethod
    def local_analysis(session_payload: dict) -> dict:
        records = session_payload.get("records") or []
        total = len(records) or 1
        completed = sum(1 for record in records if record.get("status") == "completed")
        return {
            "session_id": session_payload.get("id"),
            "schema_version": AI_SCHEMA_VERSION,
            "score": round((completed / total) * 100),
            "summary": "训练记录已完成分析。",
            "adjustments": ["保持当前低强度节奏", "下次训练优先保证动作质量"],
        }


@dataclass
class VideoRecommender:
    chat_func: callable = call_ai_chat
    config_func: callable = ai_config

    def suggest(self, exercise_name: str, description: str = "", notes: str = "") -> dict:
        config = self.config_func()
        if not config["enabled"]:
            query = exercise_name or description or "训练动作"
            return {
                "status": "fallback",
                "ai_enabled": False,
                "schema_version": AI_SCHEMA_VERSION,
                "query": query,
                "search_url": bilibili_search_url(query),
                "candidates": [bilibili_search_url(query)],
                "message": "AI 服务未配置，返回 Bilibili 搜索回退链接。",
            }
        content = self.chat_func(
            config["base_url"],
            config["api_key"],
            config["model"],
            self.prompt(),
            f"动作名称：{exercise_name}\n描述：{description}\n备注：{notes}",
            timeout=30,
        )
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"AI 返回的不是合法 JSON：{str(exc)[:200]}") from exc
        search_urls = result.get("searchUrls", [])
        if not isinstance(search_urls, list):
            search_urls = []
        for url in search_urls:
            if not validate_bilibili_url(url):
                raise ValueError(f"AI 返回了非 Bilibili 视频链接（已拒绝）：{url}")
        keywords = result.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        query = str(keywords[0]) if keywords else exercise_name
        search_url = str(search_urls[0]) if search_urls else bilibili_search_url(query)
        return {
            "status": "ok",
            "ai_enabled": True,
            "schema_version": AI_SCHEMA_VERSION,
            "query": query,
            "search_url": search_url,
            "candidates": search_urls or [search_url],
        }

    @staticmethod
    def prompt() -> str:
        return """你是一个健身教练，帮助用户在B站寻找训练教学视频。返回 JSON，包含 keywords、searchUrls、recommendedTitle、note。所有 searchUrls 必须使用 bilibili.com 域名，不得使用 youtube.com 或 youtu.be。"""


@dataclass
class ExerciseExplainer:
    def explain(self, exercise: dict) -> dict:
        return {
            "schema_version": AI_SCHEMA_VERSION,
            "status": "draft",
            "exercise": exercise,
            "explanation": exercise.get("notes") or "保持动作稳定，优先保证质量。",
        }


def draft_response(draft: dict, ai_enabled: bool = True) -> dict:
    plans_list = []
    schedule = draft.get("schedule", {})
    if isinstance(schedule, dict):
        for date_str, entry in schedule.items():
            if isinstance(entry, dict):
                plans_list.append(
                    {
                        "date": date_str,
                        "type": entry.get("type", "rest"),
                        "templateId": entry.get("templateId", ""),
                        "status": entry.get("status", "pending"),
                        "note": entry.get("note", ""),
                    }
                )
    return {
        "status": "draft",
        "ai_enabled": ai_enabled,
        "schema_version": AI_SCHEMA_VERSION,
        "draft": {
            "schemaVersion": draft.get("schemaVersion", AI_SCHEMA_VERSION),
            "title": draft.get("title", ""),
            "theme": draft.get("theme", ""),
            "recommendedDate": draft.get("recommendedDate", ""),
            "exercises": draft.get("exercises", []),
            "templates": draft.get("templates", []),
            "plans": plans_list,
        },
        "warnings": [],
    }

