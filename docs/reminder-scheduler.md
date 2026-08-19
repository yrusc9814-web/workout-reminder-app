# 本地定时提醒最小闭环

本项目新增 `scripts/workout_reminder_tick.py` 作为一次性本地提醒 tick 脚本。它只使用 Python 标准库；训练日首次触发时调用本地钉钉提醒和钉钉代办 API，不接微信，不修改任务计划。

## 行为

1. 读取今日计划 API。
2. 如果今天不是训练日，打印“不提醒”提示并以 `0` 退出。
3. 如果今天是训练日，检查本地提醒日志中是否已存在同一 `date + plan_id`。
4. 未提醒过则在 stdout 打印提醒，调用钉钉提醒 / 钉钉代办 API，并向 JSON 日志追加一条记录。
5. 已提醒过则打印“已提醒，不重复提醒”提示并以 `0` 退出。
6. API 不可用、非 2xx、坏 JSON、日志读取/解析/写入失败时，在 stderr 打印清晰 `ERROR:` 并以 `1` 退出。

## 默认配置

- 今日计划 API：`http://127.0.0.1:3000/api/today`
- 钉钉提醒 API：`http://127.0.0.1:3000/api/reminders/dingtalk/send`
- 钉钉代办 API：`http://127.0.0.1:3000/api/todos/dingtalk/create`
- 日志：`workout-app/data/reminder-log.json`

可通过环境变量覆盖：

```bash
WORKOUT_REMINDER_API_URL=http://127.0.0.1:3000/api/today \
WORKOUT_REMINDER_LOG_PATH=data/reminder-log.json \
WORKOUT_DINGTALK_REMINDER_URL=http://127.0.0.1:3000/api/reminders/dingtalk/send \
WORKOUT_DINGTALK_TODO_URL=http://127.0.0.1:3000/api/todos/dingtalk/create \
python scripts/workout_reminder_tick.py
```

> 注意：脚本不会启动服务。运行前需要用户自行确认 workout-app 服务已在目标 API 地址可访问。没有钉钉凭据时 API 返回 `not_configured`，脚本仍会记录状态但不能证明真实送达。

## 定时器示例

### Linux / macOS cron

每天 07:30 执行一次：

```cron
30 7 * * * cd /path/to/workout-app && /usr/bin/python3 scripts/workout_reminder_tick.py >> data/reminder-cron.out 2>> data/reminder-cron.err
```

### Windows 任务计划程序

本项目提供 Windows 自动化入口：

- `scripts/windows_daily_reminder.py`
- `scripts/windows_daily_reminder.cmd`

该入口用于任务计划程序的一次性运行：会加载现有环境变量 / `../dingtalk-secrets.txt`（不打印密钥），必要时临时启动本地 FastAPI 服务，检查 `/api/health`，调用既有 `scripts/workout_reminder_tick.py`，并写入本地 JSONL 运行日志。

推荐任务操作配置：

- 程序：`D:\workout-reminder-app-github\workout-app\scripts\windows_daily_reminder.cmd`
- 参数：可留空
- 起始于：`D:\workout-reminder-app-github\workout-app`

当前本机上线启用配置：

- 任务名：`Workout Reminder App Daily Tick`
- 触发器：每天 `08:30`
- 程序：`D:\workout-reminder-app-github\workout-app\scripts\windows_daily_reminder.cmd`
- 参数：空
- 起始于：`D:\workout-reminder-app-github\workout-app`
- 权限：当前 Windows 用户交互登录、非最高权限运行
- 运行日志：`data/windows-reminder-runs.jsonl`
- 去重日志：`data/windows-reminder-log.json`

如需使用自定义 API 或日志路径，可直接调用 Python 入口并传参：

```bash
python scripts/windows_daily_reminder.py --port 3000 --run-log data/windows-reminder-runs.jsonl --tick-log data/windows-reminder-log.json
```

## 日志格式

`data/reminder-log.json` 是 JSON 数组，每次成功提醒追加一项：

```json
[
  {
    "date": "2026-05-11",
    "plan_id": 1,
    "title": "力量训练",
    "reminded_at": "2026-06-09T00:00:00.000000+00:00",
    "api_url": "http://127.0.0.1:3000/api/today",
    "dingtalk_reminder_status": "not_configured",
    "dingtalk_todo_status": "not_configured"
  }
]
```

该日志用于本地去重，建议不要手工破坏 JSON 结构。

## 测试

在 `workout-app/` 目录运行：

```bash
python - <<'PY'
import pytest, sys
sys.exit(pytest.main(['-q','-c','/dev/null','--rootdir=.','tests']))
PY
```
