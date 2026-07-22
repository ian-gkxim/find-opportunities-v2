"""Unit tests for app.workers.gap_worker.

Validates worker instantiation, GapAnalyzer delegation, error handling,
and correct summary dict structure.

Requirements: 1.1, 1.3
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.gap_worker import run_gap_analysis_cycle


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_context(
    llm_router=None, schema_registry=None, redis_client=None, ws_manager=None
) -> dict:
    """Build an ARQ-style context dict with the expected shared resource keys."""
    return {
        "llm_router": llm_router or MagicMock(),
        "schema_registry": schema_registry or MagicMock(),
        "redis_client": redis_client or MagicMock(),
        "ws_manager": ws_manager or MagicMock(),
    }


# ─── TEST: SUCCESSFUL CYCLE ──────────────────────────────────────────────────


class TestSuccessfulCycle:
    """run_gap_analysis_cycle creates a GapAnalyzer and delegates to run_nightly_cycle."""

    @pytest.mark.asyncio
    @patch("app.workers.gap_worker.get_async_engine")
    @patch("app.workers.gap_worker.get_async_session_factory")
    @patch("app.workers.gap_worker.load_normalizer_from_db", new_callable=AsyncMock)
    @patch("app.workers.gap_worker.GapAnalyzer")
    async def test_creates_gap_analyzer_and_calls_nightly_cycle(
        self, mock_analyzer_cls, mock_load_normalizer, mock_session_factory, mock_engine
    ):
        """Worker creates a GapAnalyzer with correct deps and calls run_nightly_cycle."""
        # Arrange
        mock_normalizer = MagicMock()
        mock_load_normalizer.return_value = mock_normalizer

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session)

        mock_engine_instance = MagicMock()
        mock_engine_instance.dispose = AsyncMock()
        mock_engine.return_value = mock_engine_instance

        nightly_summary = {
            "extracted": 15,
            "carried_forward": 5,
            "heatmaps_generated": 3,
        }
        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.run_nightly_cycle = AsyncMock(return_value=nightly_summary)
        mock_analyzer_cls.return_value = mock_analyzer_instance

        ctx = _make_context()

        # Act
        result = await run_gap_analysis_cycle(ctx)

        # Assert - GapAnalyzer was instantiated with the expected dependencies
        mock_analyzer_cls.assert_called_once()
        call_kwargs = mock_analyzer_cls.call_args.kwargs
        assert call_kwargs["llm_router"] is ctx["llm_router"]
        assert call_kwargs["schema_registry"] is ctx["schema_registry"]
        assert call_kwargs["redis_client"] is ctx["redis_client"]
        assert call_kwargs["ws_manager"] is ctx["ws_manager"]
        assert call_kwargs["normalizer"] is mock_normalizer

        # Assert - run_nightly_cycle was called
        mock_analyzer_instance.run_nightly_cycle.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.workers.gap_worker.get_async_engine")
    @patch("app.workers.gap_worker.get_async_session_factory")
    @patch("app.workers.gap_worker.load_normalizer_from_db", new_callable=AsyncMock)
    @patch("app.workers.gap_worker.GapAnalyzer")
    async def test_success_returns_summary_with_correct_keys(
        self, mock_analyzer_cls, mock_load_normalizer, mock_session_factory, mock_engine
    ):
        """Successful cycle returns summary dict with expected keys."""
        # Arrange
        mock_load_normalizer.return_value = MagicMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session)

        mock_engine_instance = MagicMock()
        mock_engine_instance.dispose = AsyncMock()
        mock_engine.return_value = mock_engine_instance

        nightly_summary = {
            "extracted": 42,
            "carried_forward": 10,
            "heatmaps_generated": 7,
        }
        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.run_nightly_cycle = AsyncMock(return_value=nightly_summary)
        mock_analyzer_cls.return_value = mock_analyzer_instance

        ctx = _make_context()

        # Act
        result = await run_gap_analysis_cycle(ctx)

        # Assert - result contains all expected keys
        assert "extracted" in result
        assert "carried_forward" in result
        assert "heatmaps_generated" in result
        assert "duration_seconds" in result
        assert "timestamp" in result

        # Assert - values from nightly_cycle are preserved
        assert result["extracted"] == 42
        assert result["carried_forward"] == 10
        assert result["heatmaps_generated"] == 7
        assert isinstance(result["duration_seconds"], float)
        assert isinstance(result["timestamp"], str)

    @pytest.mark.asyncio
    @patch("app.workers.gap_worker.get_async_engine")
    @patch("app.workers.gap_worker.get_async_session_factory")
    @patch("app.workers.gap_worker.load_normalizer_from_db", new_callable=AsyncMock)
    @patch("app.workers.gap_worker.GapAnalyzer")
    async def test_loads_normalizer_from_db(
        self, mock_analyzer_cls, mock_load_normalizer, mock_session_factory, mock_engine
    ):
        """Worker loads capability normalizer from DB before creating GapAnalyzer."""
        # Arrange
        mock_normalizer = MagicMock()
        mock_load_normalizer.return_value = mock_normalizer

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session)

        mock_engine_instance = MagicMock()
        mock_engine_instance.dispose = AsyncMock()
        mock_engine.return_value = mock_engine_instance

        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.run_nightly_cycle = AsyncMock(
            return_value={"extracted": 0, "carried_forward": 0, "heatmaps_generated": 0}
        )
        mock_analyzer_cls.return_value = mock_analyzer_instance

        ctx = _make_context()

        # Act
        await run_gap_analysis_cycle(ctx)

        # Assert - normalizer was loaded from DB
        mock_load_normalizer.assert_called_once_with(mock_session)


# ─── TEST: ERROR HANDLING ─────────────────────────────────────────────────────


class TestErrorHandling:
    """Worker handles exceptions gracefully without crashing."""

    @pytest.mark.asyncio
    @patch("app.workers.gap_worker.get_async_engine")
    @patch("app.workers.gap_worker.get_async_session_factory")
    @patch("app.workers.gap_worker.load_normalizer_from_db", new_callable=AsyncMock)
    @patch("app.workers.gap_worker.GapAnalyzer")
    async def test_exception_returns_error_dict(
        self, mock_analyzer_cls, mock_load_normalizer, mock_session_factory, mock_engine
    ):
        """When run_nightly_cycle raises, worker returns error dict without crashing."""
        # Arrange
        mock_load_normalizer.return_value = MagicMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session)

        mock_engine_instance = MagicMock()
        mock_engine_instance.dispose = AsyncMock()
        mock_engine.return_value = mock_engine_instance

        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.run_nightly_cycle = AsyncMock(
            side_effect=RuntimeError("LLM service unavailable")
        )
        mock_analyzer_cls.return_value = mock_analyzer_instance

        ctx = _make_context()

        # Act
        result = await run_gap_analysis_cycle(ctx)

        # Assert - error dict returned (not exception raised)
        assert "error" in result
        assert "LLM service unavailable" in result["error"]
        assert result["extracted"] == 0
        assert result["carried_forward"] == 0
        assert result["heatmaps_generated"] == 0
        assert "duration_seconds" in result
        assert "timestamp" in result

    @pytest.mark.asyncio
    @patch("app.workers.gap_worker.get_async_engine")
    @patch("app.workers.gap_worker.get_async_session_factory")
    @patch("app.workers.gap_worker.load_normalizer_from_db", new_callable=AsyncMock)
    async def test_normalizer_load_failure_returns_error_dict(
        self, mock_load_normalizer, mock_session_factory, mock_engine
    ):
        """When normalizer loading fails, worker returns error dict."""
        # Arrange
        mock_load_normalizer.side_effect = ConnectionError("DB connection refused")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session)

        mock_engine_instance = MagicMock()
        mock_engine_instance.dispose = AsyncMock()
        mock_engine.return_value = mock_engine_instance

        ctx = _make_context()

        # Act
        result = await run_gap_analysis_cycle(ctx)

        # Assert - error dict with DB error
        assert "error" in result
        assert "DB connection refused" in result["error"]
        assert result["extracted"] == 0

    @pytest.mark.asyncio
    @patch("app.workers.gap_worker.get_async_engine")
    @patch("app.workers.gap_worker.get_async_session_factory")
    @patch("app.workers.gap_worker.load_normalizer_from_db", new_callable=AsyncMock)
    @patch("app.workers.gap_worker.GapAnalyzer")
    @patch("app.workers.gap_worker.logger")
    async def test_exception_is_logged(
        self, mock_logger, mock_analyzer_cls, mock_load_normalizer, mock_session_factory, mock_engine
    ):
        """Worker logs the error when an exception occurs."""
        # Arrange
        mock_load_normalizer.return_value = MagicMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session)

        mock_engine_instance = MagicMock()
        mock_engine_instance.dispose = AsyncMock()
        mock_engine.return_value = mock_engine_instance

        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.run_nightly_cycle = AsyncMock(
            side_effect=ValueError("Config validation error")
        )
        mock_analyzer_cls.return_value = mock_analyzer_instance

        ctx = _make_context()

        # Act
        await run_gap_analysis_cycle(ctx)

        # Assert - error was logged
        mock_logger.error.assert_called_once()
        log_args = mock_logger.error.call_args
        assert "failed" in log_args[0][0].lower() or "Gap analysis cycle failed" in log_args[0][0]

    @pytest.mark.asyncio
    @patch("app.workers.gap_worker.get_async_engine")
    @patch("app.workers.gap_worker.get_async_session_factory")
    @patch("app.workers.gap_worker.load_normalizer_from_db", new_callable=AsyncMock)
    @patch("app.workers.gap_worker.GapAnalyzer")
    async def test_engine_disposed_on_error(
        self, mock_analyzer_cls, mock_load_normalizer, mock_session_factory, mock_engine
    ):
        """Engine is disposed even when an exception occurs (cleanup in finally)."""
        # Arrange
        mock_load_normalizer.return_value = MagicMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session)

        mock_engine_instance = MagicMock()
        mock_engine_instance.dispose = AsyncMock()
        mock_engine.return_value = mock_engine_instance

        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.run_nightly_cycle = AsyncMock(
            side_effect=RuntimeError("Unexpected failure")
        )
        mock_analyzer_cls.return_value = mock_analyzer_instance

        ctx = _make_context()

        # Act
        await run_gap_analysis_cycle(ctx)

        # Assert - engine was disposed (cleanup happened)
        mock_engine_instance.dispose.assert_called_once()


# ─── TEST: CONTEXT DICT ──────────────────────────────────────────────────────


class TestContextDict:
    """Worker accepts a context dict with expected ARQ resource keys."""

    @pytest.mark.asyncio
    @patch("app.workers.gap_worker.get_async_engine")
    @patch("app.workers.gap_worker.get_async_session_factory")
    @patch("app.workers.gap_worker.load_normalizer_from_db", new_callable=AsyncMock)
    @patch("app.workers.gap_worker.GapAnalyzer")
    async def test_extracts_all_expected_keys_from_context(
        self, mock_analyzer_cls, mock_load_normalizer, mock_session_factory, mock_engine
    ):
        """Worker extracts llm_router, schema_registry, redis_client, ws_manager from ctx."""
        # Arrange
        mock_load_normalizer.return_value = MagicMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session)

        mock_engine_instance = MagicMock()
        mock_engine_instance.dispose = AsyncMock()
        mock_engine.return_value = mock_engine_instance

        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.run_nightly_cycle = AsyncMock(
            return_value={"extracted": 0, "carried_forward": 0, "heatmaps_generated": 0}
        )
        mock_analyzer_cls.return_value = mock_analyzer_instance

        llm = MagicMock(name="llm_router")
        registry = MagicMock(name="schema_registry")
        redis = MagicMock(name="redis_client")
        ws = MagicMock(name="ws_manager")

        ctx = {
            "llm_router": llm,
            "schema_registry": registry,
            "redis_client": redis,
            "ws_manager": ws,
        }

        # Act
        await run_gap_analysis_cycle(ctx)

        # Assert - all context values were passed to GapAnalyzer
        call_kwargs = mock_analyzer_cls.call_args.kwargs
        assert call_kwargs["llm_router"] is llm
        assert call_kwargs["schema_registry"] is registry
        assert call_kwargs["redis_client"] is redis
        assert call_kwargs["ws_manager"] is ws

    @pytest.mark.asyncio
    @patch("app.workers.gap_worker.get_async_engine")
    @patch("app.workers.gap_worker.get_async_session_factory")
    @patch("app.workers.gap_worker.load_normalizer_from_db", new_callable=AsyncMock)
    @patch("app.workers.gap_worker.GapAnalyzer")
    async def test_handles_missing_context_keys_gracefully(
        self, mock_analyzer_cls, mock_load_normalizer, mock_session_factory, mock_engine
    ):
        """Worker passes None for missing context keys without crashing."""
        # Arrange
        mock_load_normalizer.return_value = MagicMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = MagicMock(return_value=mock_session)

        mock_engine_instance = MagicMock()
        mock_engine_instance.dispose = AsyncMock()
        mock_engine.return_value = mock_engine_instance

        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.run_nightly_cycle = AsyncMock(
            return_value={"extracted": 0, "carried_forward": 0, "heatmaps_generated": 0}
        )
        mock_analyzer_cls.return_value = mock_analyzer_instance

        # Empty context — all keys missing
        ctx = {}

        # Act
        result = await run_gap_analysis_cycle(ctx)

        # Assert - still completes without raising
        assert "timestamp" in result

        # Assert - GapAnalyzer received None for missing keys
        call_kwargs = mock_analyzer_cls.call_args.kwargs
        assert call_kwargs["llm_router"] is None
        assert call_kwargs["schema_registry"] is None
        assert call_kwargs["redis_client"] is None
        assert call_kwargs["ws_manager"] is None
