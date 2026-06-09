# workout-app 最终归档报告

## 1. 项目目录

`D:\workout-reminder-app-github\workout-app`

## 2. 当前可用入口

- 前端地址：`http://127.0.0.1:3000/`
- 今日计划 API：`http://127.0.0.1:3000/api/today`

## 3. 启动命令

```bash
cd D:/workout-reminder-app-github/workout-app && python -m uvicorn main:app --host 127.0.0.1 --port 3000
```

也可在项目目录运行：

```bash
python run.py
```

## 4. 当前 API 清单

| # | Method | Path | 说明 |
|---|---|---|---|
| 1 | GET | `/` | 静态本地个人运动提醒仪表盘 |
| 2 | GET | `/api/health` | 健康检查 |
| 3 | GET | `/api/today` | 今日计划 |
| 4 | GET | `/api/plans/today` | 今日计划兼容路径 |
| 5 | GET | `/api/plans/month` | 月计划，支持 `year=2026&month=5` 或 `month=YYYY-MM` |
| 6 | GET | `/api/plans/month/summary` | 月计划摘要兼容路径，支持 `month=YYYY-MM` |
| 7 | GET | `/api/plans/week` | 周计划，支持 `date=YYYY-MM-DD` |
| 8 | POST | `/api/logs/complete` | 记录完成 |
| 9 | POST | `/api/logs/skip` | 记录跳过 |
| 10 | POST | `/api/logs/postpone` | 记录延期 |
| 11 | GET | `/api/logs` | 查看日志 |
| 12 | GET | `/api/stats` | 总统计 |
| 13 | GET | `/api/stats/month` | 月统计，支持 `month=YYYY-MM` |
| 14 | GET | `/api/calendar` | 月历，支持 `year=2026&month=5` 或 `month=YYYY-MM` |
| 15 | GET | `/api/calendar/month` | 月历兼容路径，支持 `month=YYYY-MM` |
| 16 | GET | `/api/settings` | 获取设置 |
| 17 | POST | `/api/settings` | 保存设置 |
| 18 | POST | `/api/reminders/test` | 提醒 mock，不真实发送 |
| 19 | POST | `/api/reminders/wechat/send` | 微信提醒 mock，不真实发送 |
| 20 | POST | `/api/reminders/dingtalk/send` | 钉钉提醒 mock，不真实发送 |

## 5. Seed 数据范围与提醒闭环

`database.py` 当前 seed 范围为 `2026-05` 到 `2026-08`：

- `2026-05`：保留原有训练日安排，不破坏既有 5 月数据。
- `2026-06` / `2026-07` / `2026-08`：按周一、周三、周五生成训练日，其余日期为休息日。
- 未来三个月训练日数量：2026-06 为 13 天，2026-07 为 14 天，2026-08 为 13 天。
- 总 seed 计划数为 123 天，训练日 53 天，训练动作 265 条。
- `WorkoutPlan.plan_date` 有唯一约束；seed 按日期查找并更新，重复运行不会为同一天重复插入计划。

服务启动时会自动执行 seed。若本地已有 `workout.db`，重启服务即可写入新增月份；也可手动执行：

```bash
python seed.py
```

如果使用自定义数据库，请确保手动 seed 时带同一个 `WORKOUT_DB_PATH`。

## 6. 本地定时提醒最小闭环

`scripts/workout_reminder_tick.py` 用于本地定时任务一次性检查今日计划：

- 默认读取 `http://127.0.0.1:3000/api/today`，支持 `WORKOUT_REMINDER_API_URL` 覆盖。
- 默认写入 `data/reminder-log.json`，支持 `WORKOUT_REMINDER_LOG_PATH` 覆盖。
- 训练日且同一 `date + plan_id` 未提醒过时，stdout 打印提醒并追加 JSON 日志。
- 同日同计划重复运行不重复提醒。
- 无训练计划 stdout 提示不提醒并 `exit 0`。
- API 不可用、非 2xx、坏 JSON、日志损坏或写入失败时，stderr 输出 `ERROR:` 并 `exit 1`。
- 详细定时器配置见 `docs/reminder-scheduler.md`。

## 7. 桌面快捷方式脚本

新增 `scripts/create_desktop_shortcut.ps1`，用于在 Windows 当前用户桌面创建标准 Internet Shortcut：`Workout Reminder App.url`：

- 目标 URL：`http://127.0.0.1:3000`
- 不需要管理员权限。
- 不修改系统策略。
- 不创建启动项。
- 不删除或覆盖无关文件；若既有 `.url` 的 `URL=` 目标相同则幂等退出，目标不同或格式不符则拒绝覆盖。
- 不提交快捷方式文件。

运行示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/create_desktop_shortcut.ps1
```

快捷方式只打开前端地址；若打不开，请先确认后端服务已启动：

```bash
cd D:/workout-reminder-app-github/workout-app && python -m uvicorn main:app --host 127.0.0.1 --port 3000
```

## 8. 测试状态

pytest 覆盖重点：

- 核心接口可访问。
- 月计划 / 周计划 / 月历接口。
- 统计接口。
- 设置接口读写。
- complete / skip / postpone 一致性。
- 提醒 mock 接口存在。
- seed 幂等。
- 2026-06/07/08 未来月份 seed、每周一/三/五训练日、`/api/plans/month?month=2026-06`、模拟未来训练日 `/api/today`。
- 前端调用的接口路径与后端契约一致。
- 首页前端已优化为本地个人运动提醒仪表盘，保留轻量 HTML/CSS/JS，无 React/Vue/Tailwind/Vite。
- 本地定时提醒 tick：训练日写日志、重复不重复、无训练不提醒、服务/JSON/日志错误清晰失败。

建议运行方式：

```bash
python - <<'PY'
import pytest, sys
sys.exit(pytest.main(['-q', '-c', '/dev/null', '--rootdir=.', 'tests']))
PY
```

## 9. 文件清单

- `main.py`
- `database.py`
- `seed.py`
- `requirements.txt`
- `run.py`
- `static/index.html`
- `static/app.js`
- `static/styles.css`
- `data/.gitkeep`
- `scripts/workout_reminder_tick.py`
- `scripts/create_desktop_shortcut.ps1`
- `tests/test_api.py`
- `tests/test_workout_reminder_tick.py`
- `docs/reminder-scheduler.md`
- `docs/final-closure-report.md`

## 10. 当前结论

未来训练计划 seed、API 测试覆盖、文档说明和桌面快捷方式脚本已补齐。当前改动不包含真实运行日志，不提交、不 push。
