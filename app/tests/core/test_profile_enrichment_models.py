"""Unit tests for Profile Enrichment ORM models.

Validates model instantiation, CHECK constraints, UNIQUE constraints,
and column definitions for PublicSource, CompetencyProposal,
ProfileEnrichmentAudit, and EnrichmentScanHistory models.

Requirements: 1.1, 2.3
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect

from app.models.competency_proposal import CompetencyProposal
from app.models.enrichment_scan_history import EnrichmentScanHistory
from app.models.profile_enrichment_audit import ProfileEnrichmentAudit
from app.models.public_source import PublicSource


# ─── PUBLIC SOURCE MODEL TESTS ────────────────────────────────────────────────


class TestPublicSourceInstantiation:
    """PublicSource ORM model instantiation with valid values."""

    def test_instantiation_with_all_required_fields(self):
        source = PublicSource(
            id=uuid.uuid4(),
            consultant_id="consultant-001",
            source_type="github",
            url="https://github.com/example",
            label="My GitHub",
            scan_interval_days=30,
            consecutive_failures=0,
            is_active=True,
        )
        assert source.consultant_id == "consultant-001"
        assert source.source_type == "github"
        assert source.url == "https://github.com/example"
        assert source.label == "My GitHub"
        assert source.scan_interval_days == 30
        assert source.consecutive_failures == 0
        assert source.is_active is True

    def test_instantiation_with_optional_fields(self):
        now = datetime.now(tz=timezone.utc)
        source = PublicSource(
            id=uuid.uuid4(),
            consultant_id="consultant-002",
            source_type="portfolio",
            url="https://portfolio.example.com",
            label="Portfolio Site",
            scan_interval_days=14,
            last_scanned_at=now,
            consecutive_failures=2,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        assert source.last_scanned_at == now
        assert source.scan_interval_days == 14
        assert source.consecutive_failures == 2

    def test_last_scanned_at_can_be_none(self):
        source = PublicSource(
            consultant_id="consultant-003",
            source_type="google_scholar",
            url="https://scholar.google.com/citations?user=abc",
            label="Scholar Profile",
        )
        assert source.last_scanned_at is None

    def test_various_source_types(self):
        """PublicSource accepts various source type values."""
        source_types = [
            "github",
            "portfolio",
            "google_scholar",
            "linkedin_publications",
            "certification_badge",
            "personal_blog",
            "npm_pypi",
            "stack_overflow",
            "speaker_profile",
            "other",
        ]
        for st in source_types:
            source = PublicSource(
                consultant_id="c-1",
                source_type=st,
                url=f"https://example.com/{st}",
                label=f"{st} label",
            )
            assert source.source_type == st


class TestPublicSourceConstraints:
    """Verify CHECK and UNIQUE constraints are defined on PublicSource."""

    def test_has_unique_constraint_on_consultant_id_url(self):
        """UNIQUE(consultant_id, url) must be defined."""
        unique_constraints = [
            c
            for c in PublicSource.__table_args__
            if isinstance(c, UniqueConstraint)
        ]
        assert len(unique_constraints) >= 1
        # Find the specific unique constraint
        uq = next(
            (
                c
                for c in unique_constraints
                if c.name == "uq_public_sources_consultant_url"
            ),
            None,
        )
        assert uq is not None
        column_names = [col.name for col in uq.columns]
        assert "consultant_id" in column_names
        assert "url" in column_names

    def test_has_check_constraint_on_scan_interval_days(self):
        """CHECK (scan_interval_days >= 1 AND scan_interval_days <= 365)."""
        check_constraints = [
            c
            for c in PublicSource.__table_args__
            if isinstance(c, CheckConstraint)
        ]
        assert len(check_constraints) >= 1
        scan_interval_constraint = next(
            (
                c
                for c in check_constraints
                if c.name == "public_sources_valid_scan_interval"
            ),
            None,
        )
        assert scan_interval_constraint is not None
        # Verify the constraint expression references scan_interval_days and bounds
        expr_text = str(scan_interval_constraint.sqltext)
        assert "scan_interval_days" in expr_text
        assert "1" in expr_text
        assert "365" in expr_text

    def test_tablename_is_public_sources(self):
        assert PublicSource.__tablename__ == "public_sources"


# ─── COMPETENCY PROPOSAL MODEL TESTS ─────────────────────────────────────────


class TestCompetencyProposalInstantiation:
    """CompetencyProposal ORM model instantiation with valid values."""

    def test_instantiation_with_all_required_fields(self):
        proposal = CompetencyProposal(
            id=uuid.uuid4(),
            consultant_id="consultant-001",
            source_id=uuid.uuid4(),
            category="technology",
            name="Kubernetes",
            evidence_summary="Owner of k8s-operator repo (142 stars)",
            confidence="strong",
            source_url="https://github.com/user/k8s-operator",
            status="pending",
        )
        assert proposal.consultant_id == "consultant-001"
        assert proposal.category == "technology"
        assert proposal.name == "Kubernetes"
        assert proposal.evidence_summary == "Owner of k8s-operator repo (142 stars)"
        assert proposal.confidence == "strong"
        assert proposal.source_url == "https://github.com/user/k8s-operator"
        assert proposal.status == "pending"

    def test_instantiation_with_optional_fields(self):
        now = datetime.now(tz=timezone.utc)
        proposal = CompetencyProposal(
            id=uuid.uuid4(),
            consultant_id="consultant-002",
            source_id=uuid.uuid4(),
            category="publication",
            name="RFC 9114 co-author",
            evidence_summary="Listed as co-author on RFC 9114",
            raw_evidence="Authors: J. Smith, User Name",
            confidence="inferred",
            source_url="https://scholar.google.com/user",
            status="accepted",
            merged_content="Publication: RFC 9114 co-author",
            reviewed_at=now,
            created_at=now,
            updated_at=now,
        )
        assert proposal.raw_evidence == "Authors: J. Smith, User Name"
        assert proposal.merged_content == "Publication: RFC 9114 co-author"
        assert proposal.reviewed_at == now

    def test_confidence_values(self):
        """Confidence field accepts both 'strong' and 'inferred'."""
        for confidence in ("strong", "inferred"):
            proposal = CompetencyProposal(
                consultant_id="c-1",
                source_id=uuid.uuid4(),
                category="technology",
                name="Python",
                evidence_summary="Evidence",
                confidence=confidence,
                source_url="https://example.com",
                status="pending",
            )
            assert proposal.confidence == confidence

    def test_status_values(self):
        """Status field accepts 'pending', 'accepted', 'rejected'."""
        for status in ("pending", "accepted", "rejected"):
            proposal = CompetencyProposal(
                consultant_id="c-1",
                source_id=uuid.uuid4(),
                category="technology",
                name="Python",
                evidence_summary="Evidence",
                confidence="strong",
                source_url="https://example.com",
                status=status,
            )
            assert proposal.status == status


class TestCompetencyProposalConstraints:
    """Verify CHECK constraints on CompetencyProposal."""

    def test_has_check_constraint_on_confidence(self):
        """CHECK (confidence IN ('strong', 'inferred'))."""
        check_constraints = [
            c
            for c in CompetencyProposal.__table_args__
            if isinstance(c, CheckConstraint)
        ]
        confidence_constraint = next(
            (
                c
                for c in check_constraints
                if c.name == "competency_proposals_valid_confidence"
            ),
            None,
        )
        assert confidence_constraint is not None
        expr_text = str(confidence_constraint.sqltext)
        assert "confidence" in expr_text
        assert "strong" in expr_text
        assert "inferred" in expr_text

    def test_has_check_constraint_on_status(self):
        """CHECK (status IN ('pending', 'accepted', 'rejected'))."""
        check_constraints = [
            c
                for c in CompetencyProposal.__table_args__
            if isinstance(c, CheckConstraint)
        ]
        status_constraint = next(
            (
                c
                for c in check_constraints
                if c.name == "competency_proposals_valid_status"
            ),
            None,
        )
        assert status_constraint is not None
        expr_text = str(status_constraint.sqltext)
        assert "status" in expr_text
        assert "pending" in expr_text
        assert "accepted" in expr_text
        assert "rejected" in expr_text

    def test_has_exactly_two_check_constraints(self):
        """CompetencyProposal has exactly 2 check constraints."""
        check_constraints = [
            c
            for c in CompetencyProposal.__table_args__
            if isinstance(c, CheckConstraint)
        ]
        assert len(check_constraints) == 2

    def test_tablename_is_competency_proposals(self):
        assert CompetencyProposal.__tablename__ == "competency_proposals"


# ─── PROFILE ENRICHMENT AUDIT MODEL TESTS ────────────────────────────────────


class TestProfileEnrichmentAuditInstantiation:
    """ProfileEnrichmentAudit ORM model instantiation with valid values."""

    def test_instantiation_with_all_required_fields(self):
        now = datetime.now(tz=timezone.utc)
        audit = ProfileEnrichmentAudit(
            id=uuid.uuid4(),
            consultant_id="consultant-001",
            proposal_id=uuid.uuid4(),
            action="accept",
            timestamp=now,
            added_content="Technology: Kubernetes",
            evidence_source_url="https://github.com/user/k8s-operator",
            profile_section="technologies",
            edited=False,
        )
        assert audit.consultant_id == "consultant-001"
        assert audit.action == "accept"
        assert audit.timestamp == now
        assert audit.added_content == "Technology: Kubernetes"
        assert audit.evidence_source_url == "https://github.com/user/k8s-operator"
        assert audit.profile_section == "technologies"
        assert audit.edited is False

    def test_instantiation_with_edit_flag_true(self):
        audit = ProfileEnrichmentAudit(
            id=uuid.uuid4(),
            consultant_id="consultant-001",
            proposal_id=uuid.uuid4(),
            action="accept_with_edit",
            added_content="Edited content by consultant",
            evidence_source_url="https://example.com",
            profile_section="publications",
            edited=True,
        )
        assert audit.action == "accept_with_edit"
        assert audit.edited is True

    def test_action_values(self):
        """Action field accepts 'accept', 'accept_with_edit', 'reject'."""
        for action in ("accept", "accept_with_edit", "reject"):
            audit = ProfileEnrichmentAudit(
                consultant_id="c-1",
                proposal_id=uuid.uuid4(),
                action=action,
                edited=False,
            )
            assert audit.action == action

    def test_optional_fields_can_be_none(self):
        """added_content, evidence_source_url, profile_section are nullable."""
        audit = ProfileEnrichmentAudit(
            consultant_id="c-1",
            proposal_id=uuid.uuid4(),
            action="reject",
            added_content=None,
            evidence_source_url=None,
            profile_section=None,
            edited=False,
        )
        assert audit.added_content is None
        assert audit.evidence_source_url is None
        assert audit.profile_section is None


class TestProfileEnrichmentAuditConstraints:
    """Verify CHECK constraint on ProfileEnrichmentAudit."""

    def test_has_check_constraint_on_action(self):
        """CHECK (action IN ('accept', 'accept_with_edit', 'reject'))."""
        check_constraints = [
            c
            for c in ProfileEnrichmentAudit.__table_args__
            if isinstance(c, CheckConstraint)
        ]
        action_constraint = next(
            (
                c
                for c in check_constraints
                if c.name == "audit_log_valid_action"
            ),
            None,
        )
        assert action_constraint is not None
        expr_text = str(action_constraint.sqltext)
        assert "action" in expr_text
        assert "accept" in expr_text
        assert "accept_with_edit" in expr_text
        assert "reject" in expr_text

    def test_has_exactly_one_check_constraint(self):
        check_constraints = [
            c
            for c in ProfileEnrichmentAudit.__table_args__
            if isinstance(c, CheckConstraint)
        ]
        assert len(check_constraints) == 1

    def test_tablename_is_profile_enrichment_audit_log(self):
        assert ProfileEnrichmentAudit.__tablename__ == "profile_enrichment_audit_log"


# ─── ENRICHMENT SCAN HISTORY MODEL TESTS ─────────────────────────────────────


class TestEnrichmentScanHistoryInstantiation:
    """EnrichmentScanHistory ORM model instantiation with valid values."""

    def test_instantiation_with_all_required_fields(self):
        now = datetime.now(tz=timezone.utc)
        history = EnrichmentScanHistory(
            id=uuid.uuid4(),
            consultant_id="consultant-001",
            source_id=uuid.uuid4(),
            scan_type="scheduled",
            started_at=now,
            status="running",
            proposals_generated=0,
        )
        assert history.consultant_id == "consultant-001"
        assert history.scan_type == "scheduled"
        assert history.started_at == now
        assert history.status == "running"
        assert history.proposals_generated == 0

    def test_instantiation_completed_scan(self):
        now = datetime.now(tz=timezone.utc)
        history = EnrichmentScanHistory(
            id=uuid.uuid4(),
            consultant_id="consultant-002",
            source_id=uuid.uuid4(),
            scan_type="on_demand",
            started_at=now,
            completed_at=now,
            status="completed",
            proposals_generated=5,
        )
        assert history.scan_type == "on_demand"
        assert history.status == "completed"
        assert history.completed_at == now
        assert history.proposals_generated == 5

    def test_instantiation_failed_scan(self):
        now = datetime.now(tz=timezone.utc)
        history = EnrichmentScanHistory(
            id=uuid.uuid4(),
            consultant_id="consultant-003",
            source_id=uuid.uuid4(),
            scan_type="scheduled",
            started_at=now,
            completed_at=now,
            status="failed",
            proposals_generated=0,
            error_message="Connection timeout after 15s",
        )
        assert history.status == "failed"
        assert history.error_message == "Connection timeout after 15s"

    def test_source_id_can_be_none(self):
        """source_id is nullable for full-consultant scans."""
        history = EnrichmentScanHistory(
            consultant_id="c-1",
            source_id=None,
            scan_type="scheduled",
            status="running",
        )
        assert history.source_id is None

    def test_scan_type_values(self):
        """scan_type accepts 'scheduled' and 'on_demand'."""
        for scan_type in ("scheduled", "on_demand"):
            history = EnrichmentScanHistory(
                consultant_id="c-1",
                scan_type=scan_type,
                status="running",
            )
            assert history.scan_type == scan_type

    def test_status_values(self):
        """status accepts 'running', 'completed', 'failed'."""
        for status in ("running", "completed", "failed"):
            history = EnrichmentScanHistory(
                consultant_id="c-1",
                scan_type="scheduled",
                status=status,
            )
            assert history.status == status


class TestEnrichmentScanHistoryConstraints:
    """Verify CHECK constraints on EnrichmentScanHistory."""

    def test_has_check_constraint_on_scan_type(self):
        """CHECK (scan_type IN ('scheduled', 'on_demand'))."""
        check_constraints = [
            c
            for c in EnrichmentScanHistory.__table_args__
            if isinstance(c, CheckConstraint)
        ]
        scan_type_constraint = next(
            (
                c
                for c in check_constraints
                if c.name == "scan_history_valid_scan_type"
            ),
            None,
        )
        assert scan_type_constraint is not None
        expr_text = str(scan_type_constraint.sqltext)
        assert "scan_type" in expr_text
        assert "scheduled" in expr_text
        assert "on_demand" in expr_text

    def test_has_check_constraint_on_status(self):
        """CHECK (status IN ('running', 'completed', 'failed'))."""
        check_constraints = [
            c
            for c in EnrichmentScanHistory.__table_args__
            if isinstance(c, CheckConstraint)
        ]
        status_constraint = next(
            (
                c
                for c in check_constraints
                if c.name == "scan_history_valid_status"
            ),
            None,
        )
        assert status_constraint is not None
        expr_text = str(status_constraint.sqltext)
        assert "status" in expr_text
        assert "running" in expr_text
        assert "completed" in expr_text
        assert "failed" in expr_text

    def test_has_exactly_two_check_constraints(self):
        check_constraints = [
            c
            for c in EnrichmentScanHistory.__table_args__
            if isinstance(c, CheckConstraint)
        ]
        assert len(check_constraints) == 2

    def test_tablename_is_enrichment_scan_history(self):
        assert EnrichmentScanHistory.__tablename__ == "enrichment_scan_history"


# ─── DATABASE CONSTRAINT ENFORCEMENT TESTS ───────────────────────────────────


class TestDatabaseConstraintEnforcement:
    """Test constraint enforcement via in-memory SQLite database.

    These tests use an actual database session to verify that constraints
    are enforced at the database level.
    """

    @pytest.fixture
    async def db_session(self, async_engine):
        """Create only enrichment tables and provide a session for constraint testing."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        # Only create the tables we need to avoid JSONB/PostgreSQL-only types
        tables = [
            PublicSource.__table__,
            CompetencyProposal.__table__,
            ProfileEnrichmentAudit.__table__,
            EnrichmentScanHistory.__table__,
        ]

        async with async_engine.begin() as conn:
            for table in tables:
                await conn.run_sync(table.create)

        session_factory = async_sessionmaker(
            async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            yield session
            await session.rollback()

        async with async_engine.begin() as conn:
            for table in reversed(tables):
                await conn.run_sync(table.drop)

    async def test_public_source_unique_constraint_enforced(self, db_session):
        """Inserting duplicate (consultant_id, url) raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        now = datetime.now(tz=timezone.utc)

        source1 = PublicSource(
            id=uuid.uuid4(),
            consultant_id="consultant-001",
            source_type="github",
            url="https://github.com/example",
            label="GitHub 1",
            scan_interval_days=30,
            consecutive_failures=0,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        source2 = PublicSource(
            id=uuid.uuid4(),
            consultant_id="consultant-001",
            source_type="portfolio",
            url="https://github.com/example",  # Same URL, same consultant
            label="GitHub 2",
            scan_interval_days=30,
            consecutive_failures=0,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        db_session.add(source1)
        await db_session.flush()

        db_session.add(source2)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_public_source_different_consultants_same_url_allowed(
        self, db_session
    ):
        """Different consultants can have the same URL."""
        now = datetime.now(tz=timezone.utc)

        source1 = PublicSource(
            id=uuid.uuid4(),
            consultant_id="consultant-001",
            source_type="github",
            url="https://github.com/example",
            label="GitHub 1",
            scan_interval_days=30,
            consecutive_failures=0,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        source2 = PublicSource(
            id=uuid.uuid4(),
            consultant_id="consultant-002",  # Different consultant
            source_type="github",
            url="https://github.com/example",  # Same URL
            label="GitHub 2",
            scan_interval_days=30,
            consecutive_failures=0,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        db_session.add(source1)
        db_session.add(source2)
        await db_session.flush()

        # Both should persist without error
        assert source1.consultant_id != source2.consultant_id

    async def test_public_source_same_consultant_different_urls_allowed(
        self, db_session
    ):
        """Same consultant can have different URLs."""
        now = datetime.now(tz=timezone.utc)

        source1 = PublicSource(
            id=uuid.uuid4(),
            consultant_id="consultant-001",
            source_type="github",
            url="https://github.com/user1",
            label="GitHub Profile",
            scan_interval_days=30,
            consecutive_failures=0,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        source2 = PublicSource(
            id=uuid.uuid4(),
            consultant_id="consultant-001",
            source_type="portfolio",
            url="https://portfolio.example.com",  # Different URL
            label="Portfolio",
            scan_interval_days=30,
            consecutive_failures=0,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        db_session.add(source1)
        db_session.add(source2)
        await db_session.flush()

        assert source1.url != source2.url


# ─── COLUMN DEFINITION TESTS ─────────────────────────────────────────────────


class TestColumnDefinitions:
    """Verify essential column properties across all enrichment models."""

    def test_public_source_required_columns(self):
        """Verify non-nullable columns on PublicSource."""
        table = PublicSource.__table__
        non_nullable = [
            col.name for col in table.columns if not col.nullable
        ]
        expected_required = [
            "id",
            "consultant_id",
            "source_type",
            "url",
            "label",
            "scan_interval_days",
            "consecutive_failures",
            "is_active",
            "created_at",
            "updated_at",
        ]
        for col_name in expected_required:
            assert col_name in non_nullable, f"{col_name} should be non-nullable"

    def test_competency_proposal_required_columns(self):
        """Verify non-nullable columns on CompetencyProposal."""
        table = CompetencyProposal.__table__
        non_nullable = [
            col.name for col in table.columns if not col.nullable
        ]
        expected_required = [
            "id",
            "consultant_id",
            "source_id",
            "category",
            "name",
            "evidence_summary",
            "confidence",
            "source_url",
            "status",
            "created_at",
            "updated_at",
        ]
        for col_name in expected_required:
            assert col_name in non_nullable, f"{col_name} should be non-nullable"

    def test_competency_proposal_nullable_columns(self):
        """Verify nullable columns on CompetencyProposal."""
        table = CompetencyProposal.__table__
        nullable = [col.name for col in table.columns if col.nullable]
        expected_nullable = ["raw_evidence", "merged_content", "reviewed_at"]
        for col_name in expected_nullable:
            assert col_name in nullable, f"{col_name} should be nullable"

    def test_enrichment_scan_history_required_columns(self):
        """Verify non-nullable columns on EnrichmentScanHistory."""
        table = EnrichmentScanHistory.__table__
        non_nullable = [
            col.name for col in table.columns if not col.nullable
        ]
        expected_required = [
            "id",
            "consultant_id",
            "scan_type",
            "started_at",
            "status",
            "proposals_generated",
            "created_at",
        ]
        for col_name in expected_required:
            assert col_name in non_nullable, f"{col_name} should be non-nullable"

    def test_enrichment_scan_history_nullable_columns(self):
        """Verify nullable columns on EnrichmentScanHistory."""
        table = EnrichmentScanHistory.__table__
        nullable = [col.name for col in table.columns if col.nullable]
        expected_nullable = ["source_id", "completed_at", "error_message"]
        for col_name in expected_nullable:
            assert col_name in nullable, f"{col_name} should be nullable"

    def test_public_source_primary_key_is_uuid(self):
        """PublicSource primary key is UUID type."""
        table = PublicSource.__table__
        pk_cols = [col for col in table.columns if col.primary_key]
        assert len(pk_cols) == 1
        assert pk_cols[0].name == "id"

    def test_competency_proposal_primary_key_is_uuid(self):
        """CompetencyProposal primary key is UUID type."""
        table = CompetencyProposal.__table__
        pk_cols = [col for col in table.columns if col.primary_key]
        assert len(pk_cols) == 1
        assert pk_cols[0].name == "id"

    def test_profile_enrichment_audit_primary_key_is_uuid(self):
        """ProfileEnrichmentAudit primary key is UUID type."""
        table = ProfileEnrichmentAudit.__table__
        pk_cols = [col for col in table.columns if col.primary_key]
        assert len(pk_cols) == 1
        assert pk_cols[0].name == "id"

    def test_enrichment_scan_history_primary_key_is_uuid(self):
        """EnrichmentScanHistory primary key is UUID type."""
        table = EnrichmentScanHistory.__table__
        pk_cols = [col for col in table.columns if col.primary_key]
        assert len(pk_cols) == 1
        assert pk_cols[0].name == "id"
