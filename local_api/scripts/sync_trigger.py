"""Phase 11 — CLI sync trigger for SyncScheduler.

Minimal external entry point that allows cron, LaunchAgent, or shell scripts
to trigger sync operations through SyncScheduler without running the FastAPI
server. Never bypasses SyncService — always routes through the full service
layer.

Usage:
    python -m local_api.scripts.sync_trigger sync-task <task-id> [--target TARGET] [--dry-run]
    python -m local_api.scripts.sync_trigger sync-pending [--limit N] [--dry-run]

Examples:
    # Sync a task to all targets
    python -m local_api.scripts.sync_trigger sync-task task_abc123

    # Sync a task to a specific target
    python -m local_api.scripts.sync_trigger sync-task task_abc123 --target apple_calendar

    # Process up to 5 pending sync records
    python -m local_api.scripts.sync_trigger sync-pending --limit 5

    # Dry run — validates the pipeline without external sync
    python -m local_api.scripts.sync_trigger sync-task task_abc123 --dry-run
"""

from __future__ import annotations

import argparse
import sys
import os
import json
from typing import Optional

# Ensure project root is on the path (same pattern as scripts/reset_test_db.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from local_api.adapters import AdapterResult, SyncAdapter
from local_api.config import ALLOWED_SYNC_TARGETS
from local_api.services.sync_service import SyncService
from local_api.scheduler.sync_scheduler import SyncScheduler


# ── Dry-run adapter ──────────────────────────────────────────────────────


class DryRunAdapter(SyncAdapter):
    """Adapter that records sync intent without external side effects.

    Used for --dry-run mode and as default adapter. Matches any sync target
    via prefix (apple_* → apple_calendar) so the routing layer is exercised.
    """

    def __init__(self, target: str = "apple_calendar"):
        self._target = target

    @property
    def target_name(self) -> str:
        return self._target

    def validate_config(self) -> tuple[bool, Optional[str]]:
        return (True, None)

    def push(self, task_data: dict, sync_state: dict) -> AdapterResult:
        return AdapterResult(
            success=True,
            external_id="dry_run_noop",
            sync_result="skipped",
            sync_attempt=1,
        )

    def pull(self, external_id: str) -> Optional[dict]:
        return None


# ── Factory ──────────────────────────────────────────────────────────────


def build_services(dry_run: bool = False) -> tuple[SyncService, SyncScheduler]:
    """Build SyncService and SyncScheduler for CLI use.

    Args:
        dry_run: If True, use DryRunAdapter instead of configured adapters.
                 The scheduler is still fully exercised — only adapter pushes
                 are no-ops.

    Returns:
        (sync_service, sync_scheduler) tuple ready for use.
    """
    adapters = [DryRunAdapter()] if dry_run else _default_adapters()
    service = SyncService(adapters=adapters)
    scheduler = SyncScheduler(sync_service=service)
    return service, scheduler


def _default_adapters():
    """Return configured adapters.

    Creates a DryRunAdapter for each configured sync target. This ensures
    the full SyncService → SyncScheduler pipeline works even without real
    external adapters, while preventing accidental external sync.
    """
    return [DryRunAdapter(target=t) for t in ALLOWED_SYNC_TARGETS]


# ── Command handlers ──────────────────────────────────────────────────────


def handle_sync_task(args: argparse.Namespace) -> int:
    """Execute sync-task command."""
    service, scheduler = build_services(dry_run=args.dry_run)

    task_id = args.task_id
    target = args.target

    # Initialize DB before accessing it
    from local_api.database import init_db, get_db

    init_db()

    if target:
        # Single target
        result = scheduler.sync_task(task_id, target)
        _print_result("sync_task", result)
        return 0 if result.get("success") else 1
    else:
        # All targets
        result = scheduler.sync_task_all_targets(task_id)
        _print_result("sync_task_all_targets", result)
        return 0 if result.get("success_count", 0) > 0 else 1


def handle_sync_pending(args: argparse.Namespace) -> int:
    """Execute sync-pending command."""
    service, scheduler = build_services(dry_run=args.dry_run)

    # Initialize DB
    from local_api.database import init_db

    init_db()

    result = scheduler.sync_pending(limit=args.limit)
    _print_result("sync_pending", result)
    return 0


# ── Output ────────────────────────────────────────────────────────────────


def _print_result(command: str, result: dict) -> None:
    """Print result as formatted JSON to stdout."""
    output = {"command": command, "result": result}
    print(json.dumps(output, indent=2, ensure_ascii=False))


# ── CLI entry point ──────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync trigger — call SyncScheduler from CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # sync-task
    task_parser = subparsers.add_parser(
        "sync-task",
        help="Sync a single task to one or all targets",
        description="Sync a task to one or all configured sync targets.",
    )
    task_parser.add_argument("task_id", help="ID of the task to sync")
    task_parser.add_argument(
        "--target",
        default=None,
        help="Specific sync target (default: all targets)",
    )
    task_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate pipeline without external sync",
    )

    # sync-pending
    pending_parser = subparsers.add_parser(
        "sync-pending",
        help="Process pending sync_state records",
        description="Find and process pending or failed sync_state records.",
    )
    pending_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max pending records to process (default: 10)",
    )
    pending_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate pipeline without external sync",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "sync-task": handle_sync_task,
        "sync-pending": handle_sync_pending,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
