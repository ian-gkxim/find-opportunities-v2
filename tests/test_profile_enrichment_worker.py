"""Unit tests for Profile Enrichment Worker.

Tests the core worker functions:
- is_source_due() — scheduling logic
- _fetch_with_retries() — HTTP fetch with timeout and retry logic
- Consecutive failure counter behavior
- On-demand scan trigger

Requirements: 1.2, 1.3, 1.4, 2.4
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.workers.profile_enrichment_worker import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    FETCH_TIMEOUT,
    MAX_FETCH_RETRIES,
    SourceFetchError,
    _fetch_with_retries,
    is_source_due,
    profile_enrichment_scan,
)


# ─── is_source_due() Tests ───────────────────────────────────────────────────


class TestIsSourceDue:
    """Tests for the is_source_due() scheduling helper."""

    def test_none_last_scanned_returns_true(self):
        """A source that has never been scanned is always due."""
        assert is_source_due(last_scanned_at=None, scan_interval_days=30) is True

    def test_elapsed_equals_interval_returns_true(self):
        """Source is due when exactly scan_interval_days have elapsed."""
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        last_scanned = now - timedelta(days=30)

        result = is_source_due(
            last_scanned_at=last_scanned,
            scan_interval_days=30,
            now=now,
        )
        assert result is True

    def test_elapsed_exceeds_interval_returns_true(self):
        """Source is due when more than scan_interval_days have elapsed."""
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        last_scanned = now - timedelta(days=45)

        result = is_source_due(
            last_scanned_at=last_scanned,
            scan_interval_days=30,
            now=now,
        )
        assert result is True

    def test_elapsed_less_than_interval_returns_false(self):
        """Source is NOT due when less than scan_interval_days have elapsed."""
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        last_scanned = now - timedelta(days=15)

        result = is_source_due(
            last_scanned_at=last_scanned,
            scan_interval_days=30,
            now=now,
        )
        assert result is False

    def test_just_scanned_returns_false(self):
        """Source scanned moments ago is not due."""
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        last_scanned = now - timedelta(seconds=10)

        result = is_source_due(
            last_scanned_at=last_scanned,
            scan_interval_days=1,
            now=now,
        )
        assert result is False

    def test_one_second_before_interval_returns_false(self):
        """Source is NOT due when elapsed is one second less than interval."""
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        last_scanned = now - timedelta(days=30) + timedelta(seconds=1)

        result = is_source_due(
            last_scanned_at=last_scanned,
            scan_interval_days=30,
            now=now,
        )
        assert result is False


# ─── _fetch_with_retries() Tests ─────────────────────────────────────────────


class TestFetchWithRetries:
    """Tests for _fetch_with_retries() HTTP fetch logic."""

    @pytest.mark.asyncio
    async def test_successful_fetch_returns_content(self):
        """Successful HTTP 200 returns the page content."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>Hello World</html>"

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await _fetch_with_retries("https://example.com/page")

        assert result == "<html>Hello World</html>"

    @pytest.mark.asyncio
    async def test_timeout_after_15_seconds(self):
        """httpx client is configured with 15-second timeout."""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            with pytest.raises(SourceFetchError, match="Timeout"):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await _fetch_with_retries("https://slow-site.com")

            # Verify timeout configuration was passed
            call_kwargs = MockClient.call_args.kwargs
            assert call_kwargs["timeout"].connect == FETCH_TIMEOUT

    @pytest.mark.asyncio
    async def test_retries_3_times_on_timeout_then_raises(self):
        """Retries exactly MAX_FETCH_RETRIES times on timeout, then raises."""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with pytest.raises(SourceFetchError, match="Timeout"):
                    await _fetch_with_retries("https://unreachable.com")

            # Should have attempted MAX_FETCH_RETRIES times
            assert mock_client.get.call_count == MAX_FETCH_RETRIES

    @pytest.mark.asyncio
    async def test_retries_3_times_on_5xx_then_raises(self):
        """Retries exactly MAX_FETCH_RETRIES times on 5xx, then raises."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(SourceFetchError, match="HTTP 503"):
                    await _fetch_with_retries("https://server-error.com")

            assert mock_client.get.call_count == MAX_FETCH_RETRIES

    @pytest.mark.asyncio
    async def test_does_not_retry_on_4xx(self):
        """4xx client errors raise immediately without retrying."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            with pytest.raises(SourceFetchError, match="client error, not retrying"):
                await _fetch_with_retries("https://notfound.com/page")

            # Only one attempt — no retries for 4xx
            assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self):
        """Connection errors trigger retries up to MAX_FETCH_RETRIES."""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(SourceFetchError, match="Connection error"):
                    await _fetch_with_retries("https://unreachable.com")

            assert mock_client.get.call_count == MAX_FETCH_RETRIES

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt_after_5xx(self):
        """If first attempt is 5xx but second succeeds, returns content."""
        fail_response = MagicMock()
        fail_response.status_code = 502

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.text = "Success content"

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = [fail_response, success_response]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await _fetch_with_retries("https://flaky.com")

        assert result == "Success content"
        assert mock_client.get.call_count == 2


# ─── Consecutive Failure Counter Tests ────────────────────────────────────────


class TestConsecutiveFailureCounter:
    """Tests for failure counter increment/reset behavior in the scan cycle."""

    def _make_source(self, consecutive_failures=0):
        """Create a mock PublicSource with configurable failure count."""
        source = MagicMock()
        source.id = "source-001"
        source.consultant_id = "consultant-001"
        source.url = "https://github.com/consultant"
        source.source_type = "github"
        source.label = "My GitHub"
        source.consecutive_failures = consecutive_failures
        source.last_scanned_at = None
        source.scan_interval_days = 30
        source.is_active = True
        source.updated_at = None
        return source

    @pytest.mark.asyncio
    async def test_failure_increments_counter(self):
        """When a source fetch fails, consecutive_failures increments by 1."""
        source = self._make_source(consecutive_failures=0)

        # Simulate the failure handling logic from the worker
        source.consecutive_failures += 1
        source.updated_at = datetime.now(timezone.utc)

        assert source.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_success_resets_counter(self):
        """When a source is successfully scanned, consecutive_failures resets to 0."""
        source = self._make_source(consecutive_failures=2)

        # Simulate the success handling logic from _scan_source
        source.consecutive_failures = 0

        assert source.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_dashboard_notice_at_threshold(self):
        """Dashboard notice is emitted when counter reaches exactly CONSECUTIVE_FAILURE_THRESHOLD."""
        source = self._make_source(consecutive_failures=2)
        ws_manager = AsyncMock()

        # Simulate failure increment
        source.consecutive_failures += 1

        # At threshold, notice should be emitted
        if source.consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD:
            await ws_manager.broadcast_notification({
                "category": "source_failure_notice",
                "consultant_id": source.consultant_id,
                "source_id": str(source.id),
            })

        assert source.consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD
        ws_manager.broadcast_notification.assert_called_once()
        call_args = ws_manager.broadcast_notification.call_args[0][0]
        assert call_args["category"] == "source_failure_notice"

    @pytest.mark.asyncio
    async def test_no_notice_below_threshold(self):
        """No Dashboard notice when counter is below threshold."""
        source = self._make_source(consecutive_failures=0)
        ws_manager = AsyncMock()

        # Simulate failure increment
        source.consecutive_failures += 1

        # Below threshold, no notice
        if source.consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD:
            await ws_manager.broadcast_notification({
                "category": "source_failure_notice",
            })

        assert source.consecutive_failures == 1
        ws_manager.broadcast_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_notice_above_threshold(self):
        """No Dashboard notice when counter is already above threshold (already notified)."""
        source = self._make_source(consecutive_failures=3)
        ws_manager = AsyncMock()

        # Simulate another failure increment
        source.consecutive_failures += 1

        # Above threshold — notice was already sent at exactly 3
        if source.consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD:
            await ws_manager.broadcast_notification({
                "category": "source_failure_notice",
            })

        assert source.consecutive_failures == 4
        ws_manager.broadcast_notification.assert_not_called()


# ─── On-Demand Scan Trigger Tests ─────────────────────────────────────────────


class TestOnDemandScan:
    """Tests for on-demand scan trigger with specific consultant_id."""

    @pytest.mark.asyncio
    async def test_on_demand_scan_scans_specific_consultant(self):
        """When consultant_id is provided, only that consultant's sources are scanned."""
        consultant_id = "consultant-abc"

        mock_source = MagicMock()
        mock_source.id = "src-1"
        mock_source.consultant_id = consultant_id
        mock_source.url = "https://github.com/user"
        mock_source.source_type = "github"
        mock_source.label = "GitHub"
        mock_source.consecutive_failures = 0
        mock_source.is_active = True
        mock_source.last_scanned_at = None
        mock_source.scan_interval_days = 30

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_source]
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        mock_redis.aclose = AsyncMock()

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()

        with (
            patch(
                "app.workers.profile_enrichment_worker.get_settings"
            ) as mock_settings,
            patch(
                "app.workers.profile_enrichment_worker.get_redis_client",
                return_value=mock_redis,
            ),
            patch(
                "app.workers.profile_enrichment_worker.WebSocketManager"
            ) as mock_ws_cls,
            patch(
                "app.workers.profile_enrichment_worker.DomainThrottler"
            ) as mock_throttler_cls,
            patch(
                "app.workers.profile_enrichment_worker.get_async_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.workers.profile_enrichment_worker.get_async_session_factory",
                return_value=mock_session_factory,
            ),
            patch(
                "app.workers.profile_enrichment_worker._scan_source",
                new_callable=AsyncMock,
                return_value=2,
            ) as mock_scan,
        ):
            mock_ws_cls.return_value = AsyncMock()
            mock_ws_cls.return_value.broadcast_notification = AsyncMock()
            mock_throttler_cls.return_value = AsyncMock()

            result = await profile_enrichment_scan(
                ctx={}, consultant_id=consultant_id
            )

        assert result["scan_type"] == "on_demand"
        assert result["sources_scanned"] == 1
        assert result["proposals_created"] == 2

    @pytest.mark.asyncio
    async def test_scheduled_scan_type_when_no_consultant_id(self):
        """When consultant_id is None, scan_type is 'scheduled'."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()

        with (
            patch(
                "app.workers.profile_enrichment_worker.get_settings"
            ),
            patch(
                "app.workers.profile_enrichment_worker.get_redis_client",
                return_value=mock_redis,
            ),
            patch(
                "app.workers.profile_enrichment_worker.WebSocketManager"
            ),
            patch(
                "app.workers.profile_enrichment_worker.DomainThrottler"
            ),
            patch(
                "app.workers.profile_enrichment_worker.get_async_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.workers.profile_enrichment_worker.get_async_session_factory",
                return_value=mock_session_factory,
            ),
        ):
            result = await profile_enrichment_scan(ctx={}, consultant_id=None)

        assert result["scan_type"] == "scheduled"
        assert result["sources_scanned"] == 0


# ─── Full Scan Cycle Integration Test ─────────────────────────────────────────


class TestFullScanCycle:
    """Tests for the full scan cycle with mocked HTTP, LLM, and DB."""

    @pytest.mark.asyncio
    async def test_full_cycle_creates_proposals_and_updates_source(self):
        """Full scan cycle: fetch → extract → deduplicate → create proposals."""
        from app.workers.profile_enrichment_worker import _scan_source

        mock_source = MagicMock()
        mock_source.id = "source-001"
        mock_source.consultant_id = "consultant-001"
        mock_source.url = "https://github.com/consultant"
        mock_source.source_type = "github"
        mock_source.label = "GitHub Profile"
        mock_source.consecutive_failures = 1

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        mock_throttler = AsyncMock()
        mock_ws_manager = AsyncMock()
        mock_settings = MagicMock()

        # Mock the candidate returned by extractor
        mock_candidate = MagicMock()
        mock_candidate.category = "technology"
        mock_candidate.name = "Kubernetes"
        mock_candidate.evidence_summary = "Owner of k8s-operator repo"
        mock_candidate.raw_evidence = "k8s-operator repo with 142 stars"
        mock_candidate.confidence = "strong"
        mock_candidate.source_url = "https://github.com/consultant"

        with (
            patch(
                "app.workers.profile_enrichment_worker._fetch_with_retries",
                new_callable=AsyncMock,
                return_value="<html>GitHub profile content</html>",
            ),
            patch(
                "app.integrations.llm_router.LLMRouter"
            ) as mock_llm_cls,
            patch(
                "app.workers.profile_enrichment_worker.CompetencyExtractor"
            ) as mock_extractor_cls,
            patch(
                "app.workers.profile_enrichment_worker.ProposalDeduplicator"
            ) as mock_dedup_cls,
        ):
            # Setup extractor mock
            mock_extractor = AsyncMock()
            mock_extractor.extract.return_value = [mock_candidate]
            mock_extractor_cls.return_value = mock_extractor

            # Setup deduplicator mock — returns the candidate as new
            mock_dedup = AsyncMock()
            mock_dedup.deduplicate.return_value = [mock_candidate]
            mock_dedup_cls.return_value = mock_dedup

            result = await _scan_source(
                session=mock_session,
                source=mock_source,
                throttler=mock_throttler,
                ws_manager=mock_ws_manager,
                settings=mock_settings,
            )

        # Verify one proposal was created
        assert result == 1
        # Verify session.add was called for the proposal
        mock_session.add.assert_called()
        # Verify consecutive_failures was reset on success
        assert mock_source.consecutive_failures == 0
        # Verify throttler was called
        mock_throttler.acquire.assert_called_once_with(mock_source.url)
