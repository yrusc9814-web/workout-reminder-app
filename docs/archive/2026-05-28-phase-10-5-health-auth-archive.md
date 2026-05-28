# Phase 10.5 Archive Report — Health Auth Alignment

**Date:** 2026-05-28
**Branch:** `phase-6-sync-engine`
**Archive commit:** (this file)
**Phase 10.5 code commit:** (next commit)

---

## 1. Phase 10.5 Goal

Resolve a design inconsistency found in Phase 10: the `/health` endpoint's
docstring and comment header claimed it was a public endpoint ("Quick liveness
probe without auth"), but `AuthAndValidationMiddleware` applied globally
and blocked unauthenticated requests with 401.

## 2. Decision: A — Make /health truly public

**Evidence for A (public health check):**

| Source | Evidence |
|--------|----------|
| `main.py` line 103 | `# ── Health check without auth (for convenience during dev) ─────────────────` |
| `main.py` line 108 | Docstring: `"""Quick liveness probe without auth."""` |
| Router placement | `/health` defined via `@app.get(...)` outside `include_router()` calls |
| Standard practice | Health probes (K8s, load balancers, monitoring tools) cannot carry Bearer tokens |
| No competing policy | No document or comment says "all endpoints must be authenticated" |

The docstring and code structure clearly express the **design intent** for
`/health` to be public. The middleware simply didn't have a whitelist mechanism.

## 3. Modified Files

| File | Status | Description |
|------|--------|-------------|
| `local_api/middleware.py` | **Modified** | Added `PUBLIC_PATHS` frozenset + bypass check in `dispatch()` |
| `local_api/tests/test_app_sync_integration.py` | **Modified** | Updated health tests to expect 200 without auth |
| `docs/archive/2026-05-28-phase-10-5-health-auth-archive.md` | **Added** | This archive report |

### Middleware change detail

```python
# ── 0. Public path bypass ────────────────────────────────────────
if request.url.path in PUBLIC_PATHS:
    return await call_next(request)
```

The bypass runs **before** auth validation, Content-Type check, and body
injection scanning. Only the path `/health` is in the set — minimal, targeted,
extensible for future public endpoints.

## 4. Test Results

```
test_app_sync_integration.py — 18 passed ✅
test_sync_scheduler.py        — 10 passed ✅
test_sync_routes.py           — 16 passed ✅
test_sync_service.py          — 19 passed ✅
Full suite                    — 63 passed ✅
```

## 5. Verification

| Check | Result |
|-------|--------|
| `/health` returns 200 without auth | ✅ |
| `/health` with auth also works | ✅ |
| Other routes still require auth | ✅ (existing test_sync_routes auth tests) |
| No production code beyond middleware/main modified | ✅ |
| No dirty files mixed in | ✅ |

---

*Phase 10.5 complete. Ready for Phase 11.*
