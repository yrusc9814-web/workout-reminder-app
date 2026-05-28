# Phase 13 — Sync Trigger Safety Layer

**Date:** 2026-05-28
**Branch:** `phase-6-sync-engine`
**Predecessor:** Phase 12 (commit `bab48b731`)
**Build:** 355 passed (full local_api suite)

---

## Objective

补齐 sync 执行安全验收层，确保 CLI sync trigger 在接真实 Apple Calendar / Reminders 和微信提醒前，具备可辨识、可验证、可防御的安全输出格式和退出行为。

## Scope

### In scope

- dry-run 输出的明确标识（stderr banner + JSON mode 字段）
- 真实执行前 target 必须明确（无 target 时输出安全警告）
- 命令失败返回非 0 exit code
- 输出包含 task_id、target、status、error
- 跳过重复同步时输出明确
- 测试覆盖 CLI 输出结构和 exit code

### Out of scope

- 不接真实 Apple Calendar / Reminders
- 不启用真实微信推送
- 不安装 LaunchAgent / cron / schtasks
- 不改 adapters/、sync_engine.py、config.py
- 不做前端
- 不提交历史 dirty 文件
- 不引入 DingTalk / Boss / 其他外部平台

---

## Deliverables

| 文件 | 状态 | 说明 |
|------|------|------|
| `local_api/scripts/sync_trigger.py` | **修改** | 新增 mode 字段、safety banner、_ensure_fields、exit code 增强 |
| `local_api/tests/test_sync_trigger.py` | **修改** | 新增 18 个 Phase 13 测试（45 总） |
| `docs/archive/2026-05-28-phase-13-sync-trigger-safety.md` | **新增** | 本归档文档 |

---

## Design Decisions

### 1. Dry-run 标识方式

选择 **stderr banner + JSON mode 字段** 而非修改 AdapterResult.sync_result：

- stderr banner `[DRY-RUN]` / `[LIVE]` 提供即时视觉反馈
- JSON 顶层 `"mode": "dry-run"` / `"mode": "live"` 提供脚本消费标识
- DryRunAdapter 内部保持 `sync_result="skipped"`（受 AdapterResult 验证器约束）
- dry-run 和 real-skip 通过 mode 字段区分，而非侵入 adapter 层

### 2. 无 target 时的安全行为

- 无 `--target` 且非 dry-run：使用 _default_adapters()（全部 DryRunAdapter — 安全默认值）
- 输出 stderr 警告，明确告知用户正在使用 safe default
- 不阻塞执行（保持向后兼容性）

### 3. Exit code 策略

| 场景 | Exit code |
|------|-----------|
| 成功 | 0 |
| 无效 target | 1 |
| 任务不存在 | 1 |
| argparse 错误 | 2（由 argparse 控制） |
| sync-pending 全部失败 | 1 |
| sync-task all-targets 零成功 | 1 |

### 4. 输出结构保证

所有 result dict 通过 `_ensure_fields()` 确保包含 task_id、target、status、error 四个字段。嵌套的 results 数组也递归补齐。

---

## Test Coverage

### Phase 13 新增测试（18 个）

| 测试类 | 测试数 | 关键验证点 |
|--------|--------|-----------|
| `TestOutputStructure` | 5 | mode/dry-run/live、必填字段（task_id, target, status, error） |
| `TestDryRunLabel` | 5 | stderr [DRY-RUN]/[LIVE] banner、target 信息、安全警告 |
| `TestExitCodes` | 4 | 任务不存在 exit 1、无效 target exit 1、live 模式 exit 1 |
| `TestSkipVisibility` | 2 | results 数组含 status、skip_count 为 int |
| `TestBuildServices` (新增) | 2 | explicit_target 创建单 adapter、dry-run 忽略 explicit_target |

### 总覆盖率

```
Phase 1-13 累计：355 passed  ✅
```

---

## Architecture — Safety Flow

```
CLI (python -m local_api.scripts.sync_trigger)
 │
 ├─ main() → argparse
 │    ├─ --dry-run  → build_services(dry_run=True)  → [DRY-RUN] banner
 │    └─ --target   → build_services(explicit_target=target) → [LIVE] banner with target
 │    └─ neither    → build_services(dry_run=False)  → [LIVE] ALL targets + safety warning
 │
 ├─ handler → _emit_banner(mode, task_id, target)
 │    ├─ "dry-run"  → stderr: [DRY-RUN] Dry-run mode — no external sync
 │    ├─ "live" + target → stderr: [LIVE] Syncing task X to target: Y
 │    └─ "live" -target → stderr: [LIVE] Syncing task X to ALL targets (safe default)
 │
 ├─ scheduler call → result dict
 │
 └─ _print_result(command, result, mode)
      └─ JSON output:
           {"command": "...", "mode": "dry-run|live",
            "result": {..., "results": [{task_id, target, status, error}, ...]}}
```

---

## Key Safety Properties

| 属性 | 状态 |
|------|------|
| Dry-run 输出明确标识 (stderr + JSON) | ✅ `[DRY-RUN]` + `"mode":"dry-run"` |
| 真实执行前 target 必须明确或使用安全默认 | ✅ 无 target 输出安全警告 + DryRunAdapter |
| 命令失败返回非 0 exit code | ✅ 已验证 4 种失败路径 |
| 输出包含 task_id、target、status、error | ✅ `_ensure_fields()` 递归补齐 |
| 跳过重复同步有明确输出 | ✅ `status: "skipped"` + `skip_count` + `reason` |
| 无回归（全量 355 passed） | ✅ |

---

## Commit

```
bab48b731 .. (this)
  test(local_api): harden sync trigger safety checks
```

## Phase 14 readiness

Phase 13 完成后可进入真实 Apple Calendar / Reminders 和微信提醒集成：
- CLI 入口输出格式已标准化（mode、task_id、target、status、error）
- 安全 banner 和 exit code 策略已就位
- 跳过检测和错误传播可被外部脚本消费
- 下一步：替换 DryRunAdapter 为真实 adapter
