"""Unit tests for app.workers.review_worker.

Validates batch processing limits, summary counts, and empty queue handling.

Requirements: 3.5
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.review_models import ReviewResult, ReviewStatus
from app.workers.review_worker import ReviewWorker, run_review_processing


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_review_result(
    material_id: str, status: ReviewStatus = ReviewStatus.REVIEWED
) -> ReviewResult:
    """Create a minimal ReviewResult for testing."""
    return ReviewResult(
        material_id=material_id,
        revised_content="revised content",
        review_status=status,
        reasoning_log=MagicMock(),
        quality_score_final=80,
        total_edits_applied=2,
    )


def _make_pending_row(material_id: str) -> dict:
    """Create a mock pending review row as returned by _fetch_pending_reviews."""
    return {
        "id": material_id,
        "pipeline_record_id": f"rec-{material_id}",
        "prepare_technique_id": "cv_and_cover_letter",
        "material_type": "tailored_cv",
        "content": f"Draft content for {material_id}",
        "quality_score": 72,
        "generated_at": datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    }


# ─── TEST: EMPTY QUEUE ───────────────────────────────────────────────────────


class TestEmptyQueue:
    """When no pending reviews exist, worker returns early with processed=0."""

    @pytest.mark.asyncio
    @patch("app.workers.review_worker._fetch_pending_reviews", new_callable=AsyncMock)
    async def test_empty_queue_returns_early(self, mock_fetch):
        """Empty queue returns summary with all counts at zero."""
        mock_fetch.return_value = []

        review_service = AsyncMock()
        ctx = {
            "review_service": review_service,
            "prospect": MagicMock(),
            "beneficiary": MagicMock(),
            "enrichment": MagicMock(),
            "opportunity_description": "Test opportunity",
        }

        result = await run_review_processing(ctx)

        assert result["processed"] == 0
        assert result["reviewed"] == 0
        assert result["unreviewed"] == 0
        assert result["failed"] == 0
        # review_batch should NOT be called when queue is empty
        review_service.review_batch.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.workers.review_worker._fetch_pending_reviews", new_callable=AsyncMock)
    async def test_empty_queue_has_zero_elapsed(self, mock_fetch):
        """Empty queue returns elapsed_seconds of 0.0."""
        mock_fetch.return_value = []

        ctx = {
            "review_service": AsyncMock(),
        }

        result = await run_review_processing(ctx)

        assert result["elapsed_seconds"] == 0.0


# ─── TEST: BATCH SIZE LIMIT ──────────────────────────────────────────────────


class TestBatchSizeLimit:
    """Batch processing respects BATCH_SIZE limit."""

    @pytest.mark.asyncio
    @patch("app.workers.review_worker._fetch_pending_reviews", new_callable=AsyncMock)
    async def test_batch_respects_batch_size_limit(self, mock_fetch):
        """Fetch is called with BATCH_SIZE as the limit parameter."""
        mock_fetch.return_value = [
            _make_pending_row(f"mat-{i}") for i in range(ReviewWorker.BATCH_SIZE)
        ]

        review_service = AsyncMock()
        review_service.review_batch = AsyncMock(
            return_value=[
                _make_review_result(f"mat-{i}")
                for i in range(ReviewWorker.BATCH_SIZE)
            ]
        )

        ctx = {
            "review_service": review_service,
            "prospect": MagicMock(),
            "beneficiary": MagicMock(),
            "enrichment": MagicMock(),
            "opportunity_description": "Software Engineer at Acme",
        }

        result = await run_review_processing(ctx)

        # Verify fetch was called with BATCH_SIZE
        mock_fetch.assert_called_once_with(limit=ReviewWorker.BATCH_SIZE)
        # Verify review_batch was called with the correct number of materials
        review_service.review_batch.assert_called_once()
        call_kwargs = review_service.review_batch.call_args.kwargs
        assert len(call_kwargs["materials"]) == ReviewWorker.BATCH_SIZE
        assert result["processed"] == ReviewWorker.BATCH_SIZE

    @pytest.mark.asyncio
    @patch("app.workers.review_worker._fetch_pending_reviews", new_callable=AsyncMock)
    async def test_processes_partial_batch(self, mock_fetch):
        """When fewer than BATCH_SIZE items available, processes only those."""
        partial_count = 4
        mock_fetch.return_value = [
            _make_pending_row(f"mat-{i}") for i in range(partial_count)
        ]

        review_service = AsyncMock()
        review_service.review_batch = AsyncMock(
            return_value=[
                _make_review_result(f"mat-{i}") for i in range(partial_count)
            ]
        )

        ctx = {
            "review_service": review_service,
            "prospect": MagicMock(),
            "beneficiary": MagicMock(),
            "enrichment": MagicMock(),
            "opportunity_description": "Test",
        }

        result = await run_review_processing(ctx)

        # Still fetches with BATCH_SIZE limit, but processes only what's returned
        mock_fetch.assert_called_once_with(limit=ReviewWorker.BATCH_SIZE)
        review_service.review_batch.assert_called_once()
        call_kwargs = review_service.review_batch.call_args.kwargs
        assert len(call_kwargs["materials"]) == partial_count
        assert result["processed"] == partial_count


# ─── TEST: SUMMARY COUNTS ────────────────────────────────────────────────────


class TestSummaryCounts:
    """Worker returns correct summary counts for mixed review outcomes."""

    @pytest.mark.asyncio
    @patch("app.workers.review_worker._fetch_pending_reviews", new_callable=AsyncMock)
    async def test_returns_correct_summary_counts(self, mock_fetch):
        """Mixed results (reviewed, unreviewed, failed) are tallied correctly."""
        mock_fetch.return_value = [
            _make_pending_row(f"mat-{i}") for i in range(5)
        ]

        # 3 reviewed, 1 unreviewed, 1 failed
        mixed_results = [
            _make_review_result("mat-0", ReviewStatus.REVIEWED),
            _make_review_result("mat-1", ReviewStatus.REVIEWED),
            _make_review_result("mat-2", ReviewStatus.UNREVIEWED),
            _make_review_result("mat-3", ReviewStatus.REVIEWED),
            _make_review_result("mat-4", ReviewStatus.REVIEW_FAILED),
        ]

        review_service = AsyncMock()
        review_service.review_batch = AsyncMock(return_value=mixed_results)

        ctx = {
            "review_service": review_service,
            "prospect": MagicMock(),
            "beneficiary": MagicMock(),
            "enrichment": MagicMock(),
            "opportunity_description": "Test",
        }

        result = await run_review_processing(ctx)

        assert result["processed"] == 5
        assert result["reviewed"] == 3
        assert result["unreviewed"] == 1
        assert result["failed"] == 1

    @pytest.mark.asyncio
    @patch("app.workers.review_worker._fetch_pending_reviews", new_callable=AsyncMock)
    async def test_all_reviewed_counts(self, mock_fetch):
        """When all materials succeed, reviewed equals processed."""
        mock_fetch.return_value = [
            _make_pending_row(f"mat-{i}") for i in range(3)
        ]
        all_reviewed = [
            _make_review_result(f"mat-{i}", ReviewStatus.REVIEWED)
            for i in range(3)
        ]

        review_service = AsyncMock()
        review_service.review_batch = AsyncMock(return_value=all_reviewed)

        ctx = {
            "review_service": review_service,
            "prospect": MagicMock(),
            "beneficiary": MagicMock(),
            "enrichment": MagicMock(),
            "opportunity_description": "Test",
        }

        result = await run_review_processing(ctx)

        assert result["processed"] == 3
        assert result["reviewed"] == 3
        assert result["unreviewed"] == 0
        assert result["failed"] == 0

    @pytest.mark.asyncio
    @patch("app.workers.review_worker._fetch_pending_reviews", new_callable=AsyncMock)
    async def test_all_failed_counts(self, mock_fetch):
        """When all materials fail, failed equals processed."""
        mock_fetch.return_value = [
            _make_pending_row(f"mat-{i}") for i in range(2)
        ]
        all_failed = [
            _make_review_result(f"mat-{i}", ReviewStatus.REVIEW_FAILED)
            for i in range(2)
        ]

        review_service = AsyncMock()
        review_service.review_batch = AsyncMock(return_value=all_failed)

        ctx = {
            "review_service": review_service,
            "prospect": MagicMock(),
            "beneficiary": MagicMock(),
            "enrichment": MagicMock(),
            "opportunity_description": "Test",
        }

        result = await run_review_processing(ctx)

        assert result["processed"] == 2
        assert result["reviewed"] == 0
        assert result["unreviewed"] == 0
        assert result["failed"] == 2


# ─── TEST: REVIEW WORKER CLASS ───────────────────────────────────────────────


class TestReviewWorkerClass:
    """ReviewWorker class has correct constants."""

    def test_batch_size_is_10(self):
        assert ReviewWorker.BATCH_SIZE == 10

    def test_concurrency_limit_is_3(self):
        assert ReviewWorker.CONCURRENCY_LIMIT == 3
