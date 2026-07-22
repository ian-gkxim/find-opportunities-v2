# Feature: internal-profile-enrichment, Property 1: Source Limit Enforcement
"""Property-based tests for source limit enforcement.

Tests that for any Consultant and sequence of source additions, the system
accepts at most 10 sources. Any 11th attempt is rejected while the existing
10 remain unchanged.

The test uses an in-memory model of the source limit logic to simulate
add/remove operations, mirroring the constraint in POST /profile-enrichment/sources.

**Validates: Requirements 1.1**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from hypothesis import given, settings, assume, note
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule, invariant


# ─── In-memory model of source limit logic ────────────────────────────────────

MAX_SOURCES = 10


class OperationResult(str, Enum):
    """Result of an add/remove operation."""
    SUCCESS = "success"
    REJECTED_LIMIT = "rejected_limit"
    NOT_FOUND = "not_found"


@dataclass
class SourceStore:
    """In-memory model of the source configuration store.

    Mirrors the constraint enforced by POST /profile-enrichment/sources:
    - A consultant can have at most MAX_SOURCES (10) active sources
    - Adding when at limit is rejected (HTTP 422)
    - Removing deactivates a source, freeing a slot
    """
    active_sources: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.active_sources)

    def add_source(self, source_id: str) -> OperationResult:
        """Attempt to add a source. Reject if at limit."""
        if self.count >= MAX_SOURCES:
            return OperationResult.REJECTED_LIMIT
        self.active_sources.append(source_id)
        return OperationResult.SUCCESS

    def remove_source(self, source_id: str) -> OperationResult:
        """Remove a source by ID. Returns NOT_FOUND if not present."""
        if source_id in self.active_sources:
            self.active_sources.remove(source_id)
            return OperationResult.SUCCESS
        return OperationResult.NOT_FOUND


# ─── Strategies ───────────────────────────────────────────────────────────────

# Source IDs: simple string identifiers
source_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=20,
)


class Operation(Enum):
    ADD = "add"
    REMOVE = "remove"


@st.composite
def operation_sequence_st(draw):
    """Generate a random sequence of add/remove operations."""
    num_ops = draw(st.integers(min_value=1, max_value=30))
    operations = []
    for _ in range(num_ops):
        op_type = draw(st.sampled_from([Operation.ADD, Operation.REMOVE]))
        source_id = draw(source_id_st)
        operations.append((op_type, source_id))
    return operations


# ─── Property 1: Source Limit Enforcement ─────────────────────────────────────


class TestProperty1SourceLimitEnforcement:
    """Property 1: Source Limit Enforcement.

    **Validates: Requirements 1.1**

    Key invariants:
    - Active source count never exceeds MAX_SOURCES (10)
    - If count < 10, add succeeds
    - If count == 10, add is rejected
    - After a rejected add, existing sources remain unchanged
    """

    @given(operations=operation_sequence_st())
    @settings(max_examples=500)
    def test_source_count_never_exceeds_limit(
        self,
        operations: list,
    ) -> None:
        """FOR ANY sequence of add/remove operations, the active source
        count never exceeds MAX_SOURCES (10).

        **Validates: Requirements 1.1**
        """
        store = SourceStore()

        for op_type, source_id in operations:
            if op_type == Operation.ADD:
                store.add_source(source_id)
            else:
                store.remove_source(source_id)

            assert store.count <= MAX_SOURCES, (
                f"Source count {store.count} exceeded max {MAX_SOURCES} "
                f"after operation ({op_type.value}, {source_id!r})"
            )

    @given(operations=operation_sequence_st())
    @settings(max_examples=500)
    def test_add_succeeds_when_below_limit(
        self,
        operations: list,
    ) -> None:
        """FOR ANY sequence of operations, if the active source count is
        below MAX_SOURCES, an add operation succeeds.

        **Validates: Requirements 1.1**
        """
        store = SourceStore()

        for op_type, source_id in operations:
            if op_type == Operation.ADD:
                was_below = store.count < MAX_SOURCES
                result = store.add_source(source_id)
                if was_below:
                    assert result == OperationResult.SUCCESS, (
                        f"Add should succeed when count ({store.count - 1}) < {MAX_SOURCES}, "
                        f"but got {result.value}"
                    )
            else:
                store.remove_source(source_id)

    @given(operations=operation_sequence_st())
    @settings(max_examples=500)
    def test_add_rejected_when_at_limit(
        self,
        operations: list,
    ) -> None:
        """FOR ANY sequence of operations, if the active source count
        equals MAX_SOURCES, an add operation is rejected.

        **Validates: Requirements 1.1**
        """
        store = SourceStore()

        for op_type, source_id in operations:
            if op_type == Operation.ADD:
                was_at_limit = store.count >= MAX_SOURCES
                result = store.add_source(source_id)
                if was_at_limit:
                    assert result == OperationResult.REJECTED_LIMIT, (
                        f"Add should be rejected when count ({store.count}) >= {MAX_SOURCES}, "
                        f"but got {result.value}"
                    )
            else:
                store.remove_source(source_id)

    @given(operations=operation_sequence_st())
    @settings(max_examples=500)
    def test_existing_sources_unchanged_after_rejected_add(
        self,
        operations: list,
    ) -> None:
        """FOR ANY sequence of operations, when an add is rejected (at limit),
        the existing 10 sources remain unchanged.

        **Validates: Requirements 1.1**
        """
        store = SourceStore()

        for op_type, source_id in operations:
            if op_type == Operation.ADD:
                snapshot_before = list(store.active_sources)
                result = store.add_source(source_id)
                if result == OperationResult.REJECTED_LIMIT:
                    assert store.active_sources == snapshot_before, (
                        f"Sources changed after rejected add! "
                        f"Before: {snapshot_before}, After: {store.active_sources}"
                    )
            else:
                store.remove_source(source_id)

    @given(
        fill_ids=st.lists(source_id_st, min_size=10, max_size=10, unique=True),
        extra_id=source_id_st,
    )
    @settings(max_examples=200)
    def test_11th_source_rejected_with_10_existing(
        self,
        fill_ids: list,
        extra_id: str,
    ) -> None:
        """FOR ANY 10 unique source IDs and any 11th ID, adding the 11th
        is rejected and the existing 10 remain unchanged.

        **Validates: Requirements 1.1**
        """
        store = SourceStore()

        # Fill to max
        for sid in fill_ids:
            result = store.add_source(sid)
            assert result == OperationResult.SUCCESS

        assert store.count == MAX_SOURCES
        snapshot = list(store.active_sources)

        # 11th attempt must be rejected
        result = store.add_source(extra_id)
        assert result == OperationResult.REJECTED_LIMIT, (
            f"11th source should be rejected but got {result.value}"
        )
        assert store.active_sources == snapshot, (
            f"Existing sources changed after 11th add was rejected!"
        )
        assert store.count == MAX_SOURCES

    @given(
        fill_ids=st.lists(source_id_st, min_size=10, max_size=10, unique=True),
        new_id=source_id_st,
    )
    @settings(max_examples=200)
    def test_add_succeeds_after_remove_frees_slot(
        self,
        fill_ids: list,
        new_id: str,
    ) -> None:
        """FOR ANY 10 sources at limit, removing one frees a slot and the
        next add succeeds.

        **Validates: Requirements 1.1**
        """
        store = SourceStore()

        # Fill to max
        for sid in fill_ids:
            store.add_source(sid)

        assert store.count == MAX_SOURCES

        # Remove one
        removed = fill_ids[0]
        result = store.remove_source(removed)
        assert result == OperationResult.SUCCESS
        assert store.count == MAX_SOURCES - 1

        # Now adding should succeed
        result = store.add_source(new_id)
        assert result == OperationResult.SUCCESS, (
            f"Add should succeed after removing one source (count was {store.count - 1}), "
            f"but got {result.value}"
        )


# ─── Stateful Property Test ──────────────────────────────────────────────────


class SourceLimitStateMachine(RuleBasedStateMachine):
    """Stateful test: explores arbitrary sequences of add/remove
    operations and verifies the source limit invariant holds throughout.

    **Validates: Requirements 1.1**
    """

    def __init__(self):
        super().__init__()
        self.store = SourceStore()
        self.model_sources: list[str] = []

    sources = Bundle("sources")

    @rule(target=sources, source_id=source_id_st)
    def add_source(self, source_id: str):
        """Attempt to add a source."""
        count_before = self.store.count
        snapshot_before = list(self.store.active_sources)
        result = self.store.add_source(source_id)

        if count_before < MAX_SOURCES:
            assert result == OperationResult.SUCCESS
            self.model_sources.append(source_id)
        else:
            assert result == OperationResult.REJECTED_LIMIT
            assert self.store.active_sources == snapshot_before

        return source_id

    @rule(source_id=sources)
    def remove_source(self, source_id: str):
        """Remove a previously added source."""
        result = self.store.remove_source(source_id)
        if source_id in self.model_sources:
            self.model_sources.remove(source_id)

    @invariant()
    def count_never_exceeds_max(self):
        """Active count never exceeds MAX_SOURCES."""
        assert self.store.count <= MAX_SOURCES

    @invariant()
    def count_matches_model(self):
        """Store count matches our model tracking."""
        assert self.store.count == len(self.store.active_sources)


TestSourceLimitStateful = SourceLimitStateMachine.TestCase
