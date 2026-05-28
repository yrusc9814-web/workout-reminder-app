# Phase 12 — Sync Trigger Launch Template

**Date:** 2026-05-28
**Branch:** phase-6-sync-engine
**Predecessor:** Phase 11 (commit `2abab197c0f4`)

---

## Objective

为 Phase 11 的 sync trigger CLI 入口提供最小定时运行方案：生成 LaunchAgent/cron/Windows 定时任务模板与验收说明。不实际安装。

## Scope

### In scope

- LaunchAgent plist 模板（macOS）
- crontab 模板（Linux）
- Windows schtasks 模板
- 统一运行说明文档（`local_api/docs/sync-trigger-scheduling.md`）
- 测试文件验证模板完整性和命令正确性

### Out of scope

- 不执行 `launchctl load` 或其他实际安装命令
- 不修改系统 plist 文件
- 不创建定时任务
- 不修改 adapters/、sync_engine.py、config.py

---

## Deliverables

| 文件 | 类型 | 说明 |
|------|------|------|
| `local_api/scripts/sync_trigger.plist.template` | 新增 | macOS LaunchAgent 模板 |
| `local_api/scripts/sync_trigger.crontab.template` | 新增 | Linux cron 模板（含多套调度方案） |
| `local_api/scripts/sync_trigger_schtask.bat.template` | 新增 | Windows 任务计划模板 |
| `local_api/docs/sync-trigger-scheduling.md` | 新增 | 统一运行说明（三平台） |
| `local_api/tests/test_sync_launch_template.py` | 新增 | 模板验证测试 |
| `docs/archive/2026-05-28-phase-12-sync-trigger-launch-template.md` | 新增 | 本归档文档 |

## Decisions

### Template vs generated script

选择「模板文件 + 占位符」而非「生成脚本」：
- 模板直观可读，运维人员可直接编辑
- 无额外代码依赖，不会引入脚本生成 bug
- 三平台模板风格独立，各平台运维习惯不同

### 占位符设计

统一使用 `<PROJECT_ROOT>` 和 `<PYTHON>` 占位符：
- 明确标识需替换内容
- 模板不可执行（未替换前命令无效），防止误操作

### 调度间隔默认值

默认 5 分钟间隔（300s）：
- 同步引擎设计为高频轮询
- 模板注释中提供了 15 分钟和 daily 备选方案
- Dry-run 示例为 30 分钟（降低噪声）

### Dry-run 仅文档说明

Dry-run 命令仅在模板注释和文档中展示：
- 模板的默认命令是实际运行（非 dry-run）
- Dry-run 作为验证步骤单独列出
- 运维人员明确知道何时用 dry-run 验证

## Test Coverage

测试覆盖：

| 类别 | 关键验证点 |
|------|-----------|
| 文件存在性 | 三个模板文件存在 |
| Plist 结构 | Label, ProgramArguments, WorkingDirectory, StartInterval, KeepAlive, ExitTimeOut |
| crontab 结构 | 命令调用、间隔、dry-run、无实际安装命令 |
| schtasks 结构 | 命令调用、间隔、占位符、创建/删除命令 |
| 跨模板一致性 | 统一使用 `python -m`, `--limit 10` |

## Verification

```bash
pytest local_api/tests/test_sync_trigger.py -v          # Phase 11
pytest local_api/tests/test_sync_launch_template.py -v   # Phase 12
pytest local_api/tests/ -q                               # full suite
```

## Phase 13 readiness

Phase 12 完成后可进入 Phase 13：
- CLI 入口（Phase 11）
- 定时模板（Phase 12）
- Phase 13: 可考虑真实 adapter 对接或端到端集成测试
