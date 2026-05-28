# Phase 14 — Apple Sync Adapter Safety Layer

**Date:** 2026-05-28
**Branch:** `phase-6-sync-engine`
**Predecessor:** Phase 13 (commit `538cad7ee`)
**Build:** 382 passed (full local_api suite)

---

## Objective

接入 Apple Calendar / Reminders adapter 的最小真实实现前置层：为真实 EventKit 集成提供安全栅栏、错误检查、dry-run 和 test-mode，确保非 macOS 平台无法误用，真实写入有测试标记保护。

---

## Scope

### In scope

- `AppleSyncAdapter` 类实现（`apple_adapter.py` 新增）
- dry-run 模式：跳过所有外部操作，返回 `skipped`
- test mode：模拟推送，external_id 以 `test_` 开头
- 平台检查：非 macOS 返回 `platform_unsupported` 错误
- 权限不足 / 平台不支持 / 依赖缺失：返回明确错误，不允许静默成功
- 测试覆盖：27 个新测试覆盖所有模式

### Out of scope

- 不启用真实微信推送
- 不安装 LaunchAgent / cron / schtasks
- 不做前端
- 不引入 DingTalk / Boss / 其他外部平台
- 不提交历史 dirty 文件
- 不直接污染真实 Apple 日历/提醒事项
- 不替换 main.py 中的 MockAppleAdapter（保持向后兼容）

---

## Deliverables

| 文件 | 状态 | 说明 |
|------|------|------|
| `local_api/adapters/apple_adapter.py` | **修改** | 新增 `AppleSyncAdapter`（~160 行），保留 `MockAppleAdapter`（向后兼容） |
| `local_api/tests/test_adapters.py` | **重写** | 新增 8 个测试类、27 个测试（原 6 → 33） |
| `docs/archive/2026-05-28-phase-14-apple-adapter-safety.md` | **新增** | 本归档文档 |

---

## Design

### AppleSyncAdapter 优先级

```
push():
├─ dry_run=True  → 返回 skipped (external_id="dry_run_noop")
│                   [跳过平台检查 — 纯配置验证]
├─ test_mode=True → 模拟推送 (external_id="test_...")
│                   [跳过平台检查 — 不调 EventKit]
├─ !_is_macos()   → 返回 platform_unsupported 错误
│                   [明确错误 — 不允许静默成功]
└─ macOS(real)    → 返回 not_implemented (EventKit 集成推迟)
```

### 安全属性

| 属性 | 实现 |
|------|------|
| dry-run 跳过所有外部调用 | ✅ `dry_run=True` → 直接返回 `skipped` |
| test mode 加测试标记 | ✅ external_id 以 `test_` 开头 |
| 平台不支持返回明确错误 | ✅ `error_code="platform_unsupported"` + 当前平台名 |
| 无效 target 抛出 ValueError | ✅ 构造时检查 |
| Pull 不支持返回 None | ✅ `pull()` → `None` |
| 不污染真实数据 | ✅ 非 macOS 强制阻断；test mode 模拟不碰外部 |

### 错误码约定

| error_code | 触发条件 | 后续处理 |
|-----------|---------|---------|
| `platform_unsupported` | 非 macOS | SyncService 记录 `failed_permanent` |
| `not_implemented` | macOS but no EventKit impl | SyncService 记录 `failed_permanent` |
| (none) | dry_run / test_mode | SyncService 记录 `synced` / `skipped` |

---

## Test Coverage

### Phase 14 新增测试（27 个）

| 测试类 | 测试数 | 关键验证点 |
|--------|--------|-----------|
| `TestAppleSyncAdapterConstruction` | 7 | 默认 target、apple_calendar/reminder、无效 target 抛 ValueError、dry_run/test_mode 标志 |
| `TestAppleSyncAdapterValidateConfig` | 2 | 非 macOS 返回 error、错误包含 EventKit |
| `TestAppleSyncAdapterDryRun` | 3 | 返回 skipped、external_id="dry_run_noop"、dry_run 优先于 test_mode |
| `TestAppleSyncAdapterPlatformCheck` | 4 | platform_unsupported 错误码、含当前平台名、apple_reminder 同样返回、external_id=None |
| `TestAppleSyncAdapterTestMode` | 5 | success=True、external_id 以 test_ 开头、相同 sync_id 确定性、不同 target 不同 ID |
| `TestAppleSyncAdapterRealMode` | 2 | 非 macOS 返回 platform_unsupported、apple_reminder 同样 |
| `TestAppleSyncAdapterPull` | 4 | pull() 返回 None、与 dry_run/test_mode 无关 |

### 总覆盖率

```
Phase 1-14 累计：382 passed  ✅
```

---

## Verification

```bash
pytest local_api/tests/test_adapters.py -v           # 33 passed
pytest local_api/tests/test_sync_service.py -v       # 19 passed (no regressions)
pytest local_api/tests/test_sync_trigger.py -v       # 45 passed (no regressions)
pytest local_api/tests/ -q                           # 382 passed
```

---

## Key Safety Properties

| 属性 | 状态 |
|------|------|
| dry-run 模式不触碰外部系统 | ✅ |
| test mode 加 test_ 前缀标记 | ✅ |
| 非 macOS 平台返回明确错误 | ✅ `error_code="platform_unsupported"` |
| 无效 target 禁止构造实例 | ✅ 构造时 ValueError |
| 错误包含可读消息和当前平台 | ✅ |
| 不替换 MockAppleAdapter（向后兼容） | ✅ |
| 无回归（全量 382 passed） | ✅ |
| 不混入 dirty 文件 | ✅ |

---

## Commit

```
538cad7ee .. (this)
  feat(local_api): add apple sync adapter safety layer
```

## Phase 15 readiness

Phase 14 完成后可进入微信提醒 adapter 阶段：
- `AppleSyncAdapter` 已具备完整安全层
- 后续：微信提醒 adapter（`wechat_adapter.py`）
- 再后续：用 `AppleSyncAdapter` 替换 `main.py` 中的 `MockAppleAdapter`
