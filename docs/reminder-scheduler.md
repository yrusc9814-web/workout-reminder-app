# 本地定时提醒最小闭环

`scripts/workout_reminder_tick.py` 是一次性本地提醒 tick 脚本，只使用 Python 标准库，调用本地统一通知 API。正式首页的训练提醒仍为未开放状态，不会自动调用此接口；本次修复不启用提醒或修改任务计划。

## 行为

1. POST `/api/notifications/send`，默认请求钉钉提醒和待办，服务端读取今日计划。
2. 无计划（`no_plan`）、休息日（`no_training_plan`）、已成功投递（`duplicate_skipped`）是正常跳过，退出 `0`。
3. HTTP 2xx 之后还须检查业务回执：提醒要求整数 `errcode: 0`；待办要求非空字符串顶层 `id`（CreateTodoTask）或 `taskId`（CreatePersonalTodoTask），且无业务错误。空对象、非对象、坏 JSON、错误回执不代表成功。回执字段依据 [DingTalk 官方 SDK 模型](https://pkg.go.dev/github.com/alibabacloud-go/dingtalk/todo_1_0#CreateTodoTaskResponseBody)。
4. 本次请求的投递全部成功时返回 `sent`、`sent: true`，退出 `0`，服务端写入 SQLite `reminders` 的活动记录供去重。
5. 部分成功返回 `partial_success`；全部失败返回 `failed`；全部未配置返回 `not_configured`。这些结果的顶层 `sent` 均为 `false`，退出 `1`，不会写入成功去重记录。各渠道结果保留在 `reminder` / `todo` 中。
6. 部分成功后的重试会再次执行本次请求的全部投递，因此可能重复提醒或待办。这是当前按计划去重模型的明确限制；本次不引入逐渠道记录或数据库变更。独立兼容提醒入口成功后的记录仍可参与现有按计划去重。
7. API 不可用、非 2xx、坏 JSON、未知业务状态均在 stderr 打印 `ERROR:` 并退出 `1`。Windows 包装入口保留 tick 的实际退出码。

## 默认配置

- 通知 API：`http://127.0.0.1:3000/api/notifications/send`
- 去重：服务端当前数据库 `reminders` 表（脚本不读写旧 JSON 去重日志）。

可通过环境变量覆盖：

```bash
WORKOUT_NOTIFICATION_URL=http://127.0.0.1:3000/api/notifications/send \
WORKOUT_NOTIFICATION_CHANNEL=dingtalk \
WORKOUT_NOTIFICATION_INCLUDE_TODO=1 \
WORKOUT_NOTIFICATION_FORCE=0 \
python scripts/workout_reminder_tick.py
```

> 脚本不会启动服务。运行前需确认目标 API 可访问；`force=1` 会绕过去重。没有凭据返回 `not_configured` 并以 `1` 退出，不会记录成功。

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
- 去重记录：服务端当前数据库 `reminders` 表

如需使用自定义 API 或日志路径，可直接调用 Python 入口并传参：

```bash
python scripts/windows_daily_reminder.py --port 3000 --run-log data/windows-reminder-runs.jsonl
```

## 日志格式

Windows 包装入口的 JSONL 运行日志记录每次 tick 的实际结果；其 `status: success` 代表 tick 正常完成，也包括正常跳过，不一定发送了通知。示例：

```json
{"status":"failed","tick_returncode":1,"tick_stdout":"...partial_success...","tick_stderr":"ERROR: notification delivery did not complete: partial_success"}
```

该运行日志不用于去重。`tick_stdout` 保留通知结果（最多末尾 1000 字符），不能替代渠道的业务回执。

## 测试

在 `workout-app/` 目录运行：

```bash
python -m pytest -q -c /dev/null --rootdir=. tests/test_van22_notifications.py tests/test_workout_reminder_tick.py
```

测试使用临时 SQLite、模拟钉钉回执和本机 loopback HTTP fixture，不发送真实通知。
