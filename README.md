# Workout Reminder App

## 项目简介

Workout Reminder App 是一个轻量级运动提醒与训练计划联调项目，位于本仓库的 `workout-app/` 子目录。当前 `baseline-review` 分支已经完成基础运行闭环：FastAPI 后端、SQLite 本地数据、静态联调页面、核心 API、mock 提醒接口、测试用例与文档说明。

本仓库根目录包含其他历史/上游内容；本项目的业务代码范围仅限：

```text
workout-app/
```

## 技术栈

- Python 3.11+
- FastAPI
- Uvicorn
- SQLAlchemy 2.x
- SQLite
- Pydantic 2.x
- 原生 HTML / CSS / JavaScript 静态联调页
- pytest

## 安装依赖

进入项目子目录：

```bash
cd workout-app
```

安装依赖：

```bash
python -m ensurepip --upgrade
python -m pip install -r requirements.txt
```

如果当前 Python 环境已经有 pip，可直接执行：

```bash
python -m pip install -r requirements.txt
```

## 初始化数据库

默认数据库文件位于：

```text
workout-app/workout.db
```

服务启动时会自动：

1. 创建数据表
2. 执行 seed 初始化
3. 保持 seed 幂等，重复执行不会重复插入基础计划数据

也可以手动初始化：

```bash
python seed.py
```

测试或临时运行时，可通过环境变量覆盖数据库路径：

```bash
WORKOUT_DB_PATH=/tmp/workout-test.db python run.py
```

Windows 环境下可使用本地绝对路径作为 `WORKOUT_DB_PATH`。

## 启动命令

在 `workout-app/` 目录下执行：

```bash
python run.py
```

默认监听：

```text
0.0.0.0:3000
```

## 访问地址

本机访问：

```text
http://127.0.0.1:3000
```

首页静态联调页：

```text
GET /
```

静态资源：

```text
/static/index.html
/static/app.js
/static/styles.css
```

## 测试命令

由于仓库根目录存在更大项目的 pytest 配置，建议在 `workout-app/` 目录下使用隔离配置运行测试：

```bash
cd workout-app
python - <<'PY'
import pytest, sys
sys.exit(pytest.main(['-q', '-c', '/dev/null', '--rootdir=.', 'tests']))
PY
```

当前已验证测试结果：

```text
24 passed
```

## 当前功能清单

### 页面

- 静态首页联调页
- 今日计划展示
- 周计划展示
- 月计划展示
- 月历展示
- 统计展示
- 设置读取/保存
- 完成 / 跳过 / 延期操作按钮
- mock 提醒测试
- 基础移动端适配

### API

健康检查：

```text
GET /api/health
```

今日计划：

```text
GET /api/today
GET /api/plans/today
```

月计划：

```text
GET /api/plans/month?year=2026&month=5
GET /api/plans/month?month=2026-05
GET /api/plans/month/summary?month=2026-05
```

周计划：

```text
GET /api/plans/week?date=2026-05-11
```

统计：

```text
GET /api/stats
GET /api/stats/month?month=2026-05
```

月历：

```text
GET /api/calendar?year=2026&month=5
GET /api/calendar?month=2026-05
GET /api/calendar/month?month=2026-05
```

设置：

```text
GET /api/settings
POST /api/settings
```

训练日志：

```text
GET /api/logs
POST /api/logs/complete
POST /api/logs/skip
POST /api/logs/postpone
```

提醒 mock 接口：

```text
POST /api/reminders/test
POST /api/reminders/wechat/send
POST /api/reminders/dingtalk/send
```

这些提醒接口当前只返回 mock 结果，不会真实发送微信或钉钉消息。

## 已知限制

1. 当前种子数据主要覆盖 `2026-05`。
2. `/api/today` 如果当天不在种子计划范围内，会返回空计划结构，而不是自动生成新计划。
3. 微信和钉钉提醒接口是 mock，不连接真实外部平台。
4. `/api/stats/month` 当前按日志写入日期统计，不按计划所属月份统计。
5. 项目没有迁移系统；当前使用 SQLAlchemy 建表和幂等 seed 满足轻量本地运行。
6. 仓库根目录包含其他内容，提交时应限制变更范围，避免把无关目录纳入 Workout Reminder App 变更。

## 当前归档状态

当前 `baseline-review` 分支已完成运行、测试、API 验证与 push 收口。详见：

```text
docs/final-closure-report.md
```
