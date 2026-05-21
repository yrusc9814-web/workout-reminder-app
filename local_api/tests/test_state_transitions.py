"""Phase 6 tests for the M2 v4 sync transition validator."""

import pytest

from local_api.services.state_transition_validator import (
    get_allowed_transitions,
    get_engine_locked_states,
    is_idempotent,
    is_terminal,
    is_valid_transition,
    validate_transition_or_raise,
)


STATES = [
    "pending",
    "in_progress",
    "synced",
    "failed",
    "failed_permanent",
    "skipped",
    "stale",
    "orphaned",
    "disabled",
    "deleted",
]

ENGINE_PATHS = [
    ("pending", "in_progress"),
    ("in_progress", "synced"),
    ("in_progress", "failed"),
    ("in_progress", "failed_permanent"),
    ("failed", "in_progress"),
    ("failed", "failed_permanent"),
    ("stale", "pending"),
]

MANUAL_PATHS = [
    ("pending", "skipped"),
    ("pending", "orphaned"),
    ("pending", "disabled"),
    ("pending", "deleted"),
    ("in_progress", "orphaned"),
    ("in_progress", "disabled"),
    ("in_progress", "deleted"),
    ("synced", "orphaned"),
    ("synced", "disabled"),
    ("synced", "deleted"),
    ("failed", "orphaned"),
    ("failed", "disabled"),
    ("failed", "deleted"),
    ("failed_permanent", "pending"),
    ("failed_permanent", "orphaned"),
    ("failed_permanent", "disabled"),
    ("failed_permanent", "deleted"),
    ("skipped", "pending"),
    ("skipped", "orphaned"),
    ("skipped", "disabled"),
    ("skipped", "deleted"),
    ("stale", "orphaned"),
    ("stale", "disabled"),
    ("stale", "deleted"),
    ("orphaned", "disabled"),
    ("orphaned", "deleted"),
    ("disabled", "pending"),
    ("disabled", "orphaned"),
    ("disabled", "deleted"),
]


@pytest.mark.parametrize(("from_status", "to_status"), ENGINE_PATHS)
def test_engine_paths(from_status, to_status):
    assert is_valid_transition(from_status, to_status, trigger="engine")


@pytest.mark.parametrize(("from_status", "to_status"), MANUAL_PATHS)
def test_manual_paths(from_status, to_status):
    assert is_valid_transition(
        from_status,
        to_status,
        trigger="manual",
        has_external_id=True,
    )


def test_trigger_synced_to_stale():
    assert is_valid_transition("synced", "stale", trigger="trigger")


@pytest.mark.parametrize("status", STATES)
def test_idempotent_paths(status):
    assert is_idempotent(status, status)
    assert is_valid_transition(status, status, trigger="engine")
    assert is_valid_transition(status, status, trigger="manual")
    assert is_valid_transition(status, status, trigger="trigger")


@pytest.mark.parametrize(
    ("from_status", "to_status", "trigger"),
    [
        ("deleted", "pending", "manual"),
        ("deleted", "disabled", "manual"),
        ("pending", "synced", "engine"),
        ("pending", "failed", "engine"),
        ("in_progress", "pending", "manual"),
        ("in_progress", "stale", "engine"),
        ("synced", "pending", "trigger"),
        ("failed_permanent", "in_progress", "engine"),
        ("skipped", "in_progress", "engine"),
        ("stale", "in_progress", "engine"),
        ("orphaned", "pending", "manual"),
        ("orphaned", "deleted", "engine"),
        ("disabled", "failed", "manual"),
    ],
)
def test_illegal_transitions_grouped(from_status, to_status, trigger):
    assert not is_valid_transition(from_status, to_status, trigger=trigger)
    with pytest.raises(
        ValueError,
        match=f"Cannot transition from '{from_status}' to '{to_status}' via '{trigger}' trigger",
    ):
        validate_transition_or_raise(from_status, to_status, trigger=trigger)


def test_pending_to_orphaned_requires_external_id():
    assert not is_valid_transition("pending", "orphaned", trigger="manual")
    assert is_valid_transition(
        "pending",
        "orphaned",
        trigger="manual",
        has_external_id=True,
    )


def test_public_transition_sets_are_copies():
    engine = get_allowed_transitions("engine")
    manual = get_allowed_transitions("manual")
    trigger = get_allowed_transitions("trigger")

    assert engine["pending"] == {"in_progress"}
    assert manual["disabled"] == {"pending", "orphaned", "deleted"}
    assert trigger["synced"] == {"stale"}

    engine["pending"].add("deleted")
    assert get_allowed_transitions("engine")["pending"] == {"in_progress"}


def test_terminal_and_locked_sets():
    assert get_engine_locked_states() == frozenset({
        "in_progress",
        "failed_permanent",
        "orphaned",
        "disabled",
        "deleted",
    })
    assert is_terminal("failed_permanent")
    assert is_terminal("orphaned")
    assert not is_terminal("synced")
    assert not is_terminal("skipped")
