# 运动提醒项目（workout-app）

## 概述

这是一个轻量的 FastAPI 运动提醒/训练计划项目，提供：

- 今日计划查看
- 周计划 / 月计划查看
- 月历查看
- 训练日志记录（完成 / 跳过 / 延期）
- 月度统计与总统计
- 设置读写
- 微信 / 钉钉提醒 mock 接口（不真实发送）
- 本地定时提醒 tick 脚本（一次性检查今日训练并写本地去重日志）
- 静态联调页面

项目目录：`workout-app/`

---

## 运行环境

- Python 3.11+
- SQLite（内置文件数据库，无需额外安装）

依赖见：`requirements.txt`

---

## 安装依赖

在 `workout-app/` 目录下执行：

```bash
python -m ensurepip --upgrade
python -m pip install -r requirements.txt
```

如果当前 Python 环境已经有 pip，可直接：

```bash
python -m pip install -r requirements.txt
```

---

## 启动服务

在 `workout-app/` 目录下执行：

```bash
python run.py
```

默认监听：

- `http://127.0.0.1:3000`
- `http://localhost:3000`

首页联调页：

- `GET /`

静态资源：

- `/static/index.html`
- `/static/app.js`
- `/static/styles.css`

---

## 数据库说明

默认数据库文件：

- `workout.db`

默认行为：

- 服务启动时自动建表
- 服务启动时自动执行 seed
- seed 设计为幂等，可重复执行，不应重复插入脏数据

测试环境可通过环境变量覆盖数据库路径：

```bash
WORKOUT_DB_PATH=/tmp/workout-test.db
```

Windows 下也可传本地绝对路径。

---

## 主要接口

### 健康检查

- `GET /api/health`

返回：

```json
{"status": "ok"}
```

### 今日计划

- `GET /api/today`
- `GET /api/plans/today`

### 月计划

兼容两种形式：

- `GET /api/plans/month?year=2026&month=5`
- `GET /api/plans/month/summary?month=2026-05`

### 周计划

- `GET /api/plans/week?date=2026-05-11`

### 统计

- `GET /api/stats`
- `GET /api/stats/month?month=2026-05`

### 月历

兼容两种形式：

- `GET /api/calendar?year=2026&month=5`
- `GET /api/calendar/month?month=2026-05`

### 设置

- `GET /api/settings`
- `POST /api/settings`

示例：

```json
{
  "key": "reminder_time",
  "value": "07:30"
}
```

### 日志写入

- `POST /api/logs/complete`
- `POST /api/logs/skip`
- `POST /api/logs/postpone`

示例：

```json
{
  "plan_id": 1,
  "notes": "今天状态不错"
}
```

### 提醒 mock 接口

这些接口只返回 mock 结果，不真实发消息：

- `POST /api/reminders/test`
- `POST /api/reminders/wechat/send`
- `POST /api/reminders/dingtalk/send`

示例：

```json
{
  "title": "训练提醒",
  "message": "这是测试消息"
}
```

返回中的 `status` 固定为：

```json
{"status": "not_sent"}
```

---

## 本地定时提醒

新增一次性 tick 脚本：

```bash
python scripts/workout_reminder_tick.py
```

默认读取 `http://127.0.0.1:3000/api/today`，可用 `WORKOUT_REMINDER_API_URL` 覆盖；默认去重日志为 `data/reminder-log.json`，可用 `WORKOUT_REMINDER_LOG_PATH` 覆盖。

行为：训练日且同一 `date + plan_id` 未提醒过时打印提醒并追加 JSON 日志；重复运行不会重复提醒；无训练计划时提示不提醒并正常退出。服务不可用、非 2xx、坏 JSON、日志损坏或写入失败会输出 `ERROR:` 到 stderr 并以 `1` 退出。

更多定时器配置示例见：`docs/reminder-scheduler.md`。

---

## 测试

已补充测试目录：`tests/`

覆盖重点：

- 核心接口可访问
- 月计划 / 周计划 / 月历接口
- 统计接口
- 设置接口读写
- complete / skip / postpone 一致性
- 提醒 mock 接口存在
- seed 幂等
- 错误参数返回 422 / 404
- 前端调用的接口路径与后端契约一致
- 本地定时提醒 tick：训练日写日志、重复不重复、无训练不提醒、服务/JSON/日志错误清晰失败

### 运行测试

由于父仓库根目录的 pytest 配置会影响本子项目，建议在 `workout-app/` 下通过 Python 显式执行：

```bash
python - <<'PY'
import pytest, sys
sys.exit(pytest.main(['-q', '-c', '/dev/null', '--rootdir=.', 'tests']))
PY
```

如果只跑单测文件：

```bash
python - <<'PY'
import pytest, sys
sys.exit(pytest.main(['-q', '-c', '/dev/null', '--rootdir=.', 'tests/test_api.py']))
PY
```

---

## 前端联调说明

首页会主动调用：

- `/api/health`
- `/api/today`
- `/api/plans/week`
- `/api/plans/month`
- `/api/calendar`
- `/api/stats`
- `/api/settings`
- `/api/logs`
- `/api/reminders/test`

页面上的“完成 / 跳过 / 延期”按钮会调用对应日志接口。

提醒测试按钮只调用 mock 接口，不连接真实微信/钉钉。

---

## 当前约束

- 当前种子数据主要覆盖 `2026-05`
- 今天若不在种子计划月份内，`/api/today` 会返回空计划结构，而不是报错
- 微信 / 钉钉提醒仍是 mock，不具备真实发送能力
- 本地定时提醒脚本只做 stdout 提醒与本地日志去重；不会启动服务，也不会真实发送外部消息

---

## 建议验证顺序

1. 安装依赖
2. 启动服务
3. 打开 `http://127.0.0.1:3000`
4. 检查首页是否正常渲染
5. 调用健康检查和核心接口
6. 执行测试套件
