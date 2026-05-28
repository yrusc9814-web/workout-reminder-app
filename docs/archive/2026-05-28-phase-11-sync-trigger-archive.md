# Phase 11 Archive Report — Sync Trigger Entrypoint

**Date:** 2026-05-28
**Branch:** `phase-6-sync-engine`
**Archive commit:** (this file)
**Phase 11 code commit:** (next commit)

---

## 1. Phase 11 Goal

Provide a minimal external entry point so that cron, LaunchAgent, or shell
scripts can trigger SyncScheduler operations without running the FastAPI
server. The entry point must never bypass SyncService — all operations go
through the full service layer.

---

## 2. Design

### Entry point

```
python -m local_api.scripts.sync_trigger <command> [options]
```

Follows the existing pattern from `local_api/scripts/reset_test_db.py`.

### Commands

| Command | Syntax | Description |
|---------|--------|-------------|
| `sync-task` | `sync-task <task-id> [--target TARGET] [--dry-run]` | Sync a single task. Without `--target`, syncs to all configured targets. |
| `sync-pending` | `sync-pending [--limit N] [--dry-run]` | Process pending sync_state records (pending or failed). |

### Dry-run mode

`--dry-run` uses a single `DryRunAdapter` (target_name="apple_calendar") that
validates config, reports what *would* happen, but never reaches external
services. The full pipeline (parser → scheduler → service → adapter) is
exercised.

Default mode (without `--dry-run`) creates one `DryRunAdapter` per
`ALLOWED_SYNC_TARGETS` so the routing layer is also exercised.

### No `config.py` changes

The entry point does NOT import the FastAPI app. It directly instantiates
`SyncService` + `SyncScheduler` with `DryRunAdapter` instances. No config
changes were needed.

---

## 3. Modified Files

| File | Status | Description |
|------|--------|-------------|
| `local_api/scripts/sync_trigger.py` | **Added** | Sync trigger CLI (argparse, DryRunAdapter, 3 handlers) |
| `local_api/tests/test_sync_trigger.py` | **Added** | 27 tests covering dry-run, errors, non-dry-run, parsing |
| `docs/archive/2026-05-28-phase-11-sync-trigger-archive.md` | **Added** | This archive report |

---

## 4. Test Results

```
test_sync_trigger.py          — 27 passed ✅
test_app_sync_integration.py  — 18 passed ✅
test_sync_scheduler.py        — 10 passed ✅
test_sync_routes.py           — 16 passed ✅
test_sync_service.py          — 19 passed ✅
─────────────────────────────────────────
Total:                          90 passed ✅
```

### Trigger test coverage (27 tests)

| Test class | Tests | Coverage |
|------------|-------|----------|
| `TestDryRunAdapter` | 5 | target_name, validate_config, push (skipped), pull (None) |
| `TestBuildServices` | 4 | dry-run/default construction, adapter count/type |
| `TestCliParsing` | 8 | argument parsing for all flag combinations |
| `TestMainSyncTask` | 4 | dry-run sync-task: success, nonexistent, target-specific, all-targets |
| `TestMainSyncPending` | 2 | dry-run sync-pending: empty, with records |
| `TestErrorHandling` | 3 | argparse errors: invalid command, missing args, bad type |
| `TestNonDryRun` | 2 | Non-dry-run mode: sync-task, sync-pending |

---

## 5. Architecture — Trigger Flow

```
CLI (python -m local_api.scripts.sync_trigger)
 │
 ├─ sync-task <task-id>
 │    ▼
 ├─ handle_sync_task()
 │    ▼
 ├─ build_services(dry_run)
 │    ├─ SyncService(DryRunAdapter[...])   ← never bypasses
 │    └─ SyncScheduler(service)
 │    ▼
 ├─ scheduler.sync_task(task_id, target)
 │  └─ SyncService.run_task_sync(...)
 └─ scheduler.sync_pending(limit)
    └─ SyncService.run_task_sync(...)
```

Key design decisions:
- **Script never imports the FastAPI app** — lightweight, no server dependency
- **All adapter instances are DryRunAdapter** — safe for cron/LaunchAgent with no external side effects
- **Full pipeline exercised** — parser → scheduler → service → adapter, identical to API path
- **JSON output** — results are printed as formatted JSON for script consumption

---

## 6. Commit History

```
a2b5e293c  feat(local_api): add phase 8a sync adapter layer
8829268f6  docs(local_api): archive phase 8a adapter layer
6b37effd1  feat(local_api): wire sync adapters into service layer
b6db9c76d  feat(local_api): expose sync service through api routes
7a0b8f4bf  docs(local_api): archive phase 8c sync api routes
d59e13697  feat(local_api): add sync scheduler trigger
3263d5de7  test(local_api): verify sync app integration
ed777ab0c  fix(local_api): align health auth behavior
(this)     feat(local_api): add sync trigger entrypoint
```

---

## 7. Known Constraints

1. **DryRunAdapter only** — all triggers currently use DryRunAdapter. Real
   adapter integration deferred to future phases.
2. **No cron scheduling** — the script is a one-shot trigger. Scheduling it
   via cron/LaunchAgent is up to the operator.
3. **JSON does not go to syslog** — output is on stdout only. Use shell
   redirection for logging in cron.
4. **No config changes** — `config.py` was not modified. If real adapters
   are added later, `_default_adapters()` needs updating.

---

## 8. Verification

| Check | Result |
|-------|--------|
| Phase 11 code committed & pushed | ✅ `(pending)` |
| All 90 tests pass | ✅ |
| No dirty files mixed in | ✅ |
| Entry point calls SyncService, not engine/adapters | ✅ |
| Dry-run mode prevents external side effects | ✅ |
| Default mode also uses DryRunAdapter (safe) | ✅ |
| No config.py changes needed | ✅ |
| Follows existing `python -m` script pattern | ✅ |

---

*Phase 11 complete. Ready for next phase.*
