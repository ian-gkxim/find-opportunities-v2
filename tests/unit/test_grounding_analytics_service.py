"""Unit tests for app.core.grounding_analytics_service.GroundingAnalyticsService.

Verifies computation of weekly ungrounded-claim rates and trend retrieval
with zero-fill. Uses mocked async sessions since we cannot connect to
a real PostgreSQL database in unit tests.

Requirements: 4.2
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.core.grounding_analytics_service import (
    GroundingAnalyticsService,
    UngroundedClaimRate,
)


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_session():
    """Create a mock async session with execute and commit methods."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    """Create a mock session factory that returns the mock session as an async context manager."""
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


@pytest.fixture
def service(mock_session_factory):
    """Create a GroundingAnalyticsService instance with the mocked session factory."""
    return GroundingAnalyticsService(session_factory=mock_session_factory)


# ─── compute_ungrounded_claim_rates ──────────────────────────────────────────


class TestComputeUngroundedClaimRates:
    @pytest.mark.asyncio
    async def test_computes_rate_from_grouped_reports(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """Rate is correctly computed as ungrounded / total for each group."""
        week_start = date(2024, 6, 10)  # A Monday

        # Mock the aggregation query result
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            # (technique_id, week_start, total, grounded, partial, ungrounded, verified, blocked)
            ("cv_and_cover_letter", week_start, 20, 15, 3, 2, 8, 2),
        ]
        mock_session.execute.return_value = mock_result

        rates = await service.compute_ungrounded_claim_rates(period_weeks=1)

        assert len(rates) == 1
        assert rates[0].prepare_technique_id == "cv_and_cover_letter"
        assert rates[0].week_start == week_start
        assert rates[0].week_end == week_start + timedelta(days=6)
        assert rates[0].total_claims_extracted == 20
        assert rates[0].ungrounded_claims == 2
        assert rates[0].partially_grounded_claims == 3
        assert rates[0].ungrounded_rate == 0.1  # 2/20
        assert rates[0].partially_grounded_rate == 0.15  # 3/20

    @pytest.mark.asyncio
    async def test_zero_total_claims_gives_zero_rate(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """Rate is 0 when total_claims_extracted is 0 (division by zero avoided)."""
        week_start = date(2024, 6, 10)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("cold_email_composition", week_start, 0, 0, 0, 0, 0, 0),
        ]
        mock_session.execute.return_value = mock_result

        rates = await service.compute_ungrounded_claim_rates(period_weeks=1)

        assert len(rates) == 1
        assert rates[0].ungrounded_rate == 0.0
        assert rates[0].partially_grounded_rate == 0.0
        assert rates[0].total_claims_extracted == 0

    @pytest.mark.asyncio
    async def test_multiple_techniques_and_weeks(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """Multiple techniques and weeks are returned correctly."""
        week1 = date(2024, 6, 3)
        week2 = date(2024, 6, 10)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("cv_and_cover_letter", week1, 10, 8, 1, 1, 5, 1),
            ("cv_and_cover_letter", week2, 30, 20, 5, 5, 12, 3),
            ("cold_email_composition", week1, 5, 4, 1, 0, 3, 0),
        ]
        mock_session.execute.return_value = mock_result

        rates = await service.compute_ungrounded_claim_rates(period_weeks=2)

        assert len(rates) == 3
        # First entry: 1/10 = 0.1
        assert rates[0].ungrounded_rate == 0.1
        # Second entry: 5/30 = 0.1667
        assert rates[1].ungrounded_rate == 0.1667
        # Third entry: 0/5 = 0.0
        assert rates[2].ungrounded_rate == 0.0

    @pytest.mark.asyncio
    async def test_upserts_to_analytics_table(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """Results are upserted into grounding_analytics_weekly via ON CONFLICT."""
        week_start = date(2024, 6, 10)

        # First call returns the aggregation result, second call is the upsert
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("cv_and_cover_letter", week_start, 10, 7, 2, 1, 5, 1),
        ]
        mock_session.execute.return_value = mock_result

        await service.compute_ungrounded_claim_rates(period_weeks=1)

        # session.execute called: once for SELECT, once for upsert
        assert mock_session.execute.call_count >= 2
        # session.commit called for the upsert
        assert mock_session.commit.call_count >= 1

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """No reports → empty list returned."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        rates = await service.compute_ungrounded_claim_rates(period_weeks=4)

        assert rates == []


# ─── get_grounding_trend ─────────────────────────────────────────────────────


class TestGetGroundingTrend:
    @pytest.mark.asyncio
    async def test_returns_correct_number_of_weeks(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """Always returns exactly N weeks of data."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        trend = await service.get_grounding_trend("cv_and_cover_letter", weeks=12)

        assert len(trend) == 12

    @pytest.mark.asyncio
    async def test_zero_fills_weeks_with_no_data(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """Weeks without data get zero-filled entries."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        trend = await service.get_grounding_trend("cv_and_cover_letter", weeks=4)

        assert len(trend) == 4
        for entry in trend:
            assert entry.prepare_technique_id == "cv_and_cover_letter"
            assert entry.total_claims_extracted == 0
            assert entry.ungrounded_claims == 0
            assert entry.ungrounded_rate == 0.0
            assert entry.partially_grounded_rate == 0.0

    @pytest.mark.asyncio
    async def test_merges_existing_data_with_zero_fill(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """Existing data rows are merged, missing weeks are zero-filled."""
        today = date.today()
        days_since_monday = today.weekday()
        current_week_start = today - timedelta(days=days_since_monday)
        # Data for only the current week
        existing_week = current_week_start

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            # (week_start, week_end, total, grounded, partial, ungrounded, rate)
            (
                existing_week,
                existing_week + timedelta(days=6),
                20,
                15,
                3,
                2,
                Decimal("0.1000"),
            ),
        ]
        mock_session.execute.return_value = mock_result

        trend = await service.get_grounding_trend("cv_and_cover_letter", weeks=4)

        assert len(trend) == 4
        # The last entry should be the current week with real data
        last_entry = trend[-1]
        assert last_entry.week_start == existing_week
        assert last_entry.total_claims_extracted == 20
        assert last_entry.ungrounded_claims == 2
        assert last_entry.ungrounded_rate == 0.1

        # Other entries should be zero-filled
        zero_entries = [e for e in trend if e.week_start != existing_week]
        assert all(e.total_claims_extracted == 0 for e in zero_entries)
        assert all(e.ungrounded_rate == 0.0 for e in zero_entries)

    @pytest.mark.asyncio
    async def test_weeks_are_chronologically_ordered(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """Returned entries are ordered from oldest to newest."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        trend = await service.get_grounding_trend("cv_and_cover_letter", weeks=6)

        week_starts = [entry.week_start for entry in trend]
        assert week_starts == sorted(week_starts)

    @pytest.mark.asyncio
    async def test_each_entry_has_correct_technique_id(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """All entries have the requested technique_id."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        trend = await service.get_grounding_trend("proposal_composition", weeks=4)

        assert all(
            entry.prepare_technique_id == "proposal_composition"
            for entry in trend
        )

    @pytest.mark.asyncio
    async def test_week_end_is_six_days_after_start(
        self, service: GroundingAnalyticsService, mock_session
    ):
        """week_end is always week_start + 6 days (Mon-Sun)."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        trend = await service.get_grounding_trend("cv_and_cover_letter", weeks=4)

        for entry in trend:
            assert entry.week_end == entry.week_start + timedelta(days=6)
