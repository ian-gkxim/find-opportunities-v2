# Feature: sender-voice-assets, Property 8: Analytics voice segmentation correctness
"""Property-based test for AnalyticsService.compute_voice_segmented_funnel().

Generates random send/reply counts for voice and no-voice segments (where
replies <= sends and sends >= 1) and verifies that voice_applied_reply_rate
equals round(voice_replies/voice_sends, 4) and no_voice_reply_rate equals
round(no_voice_replies/no_voice_sends, 4), each computed independently.

**Validates: Requirements 4.2**
"""

from __future__ import annotations

from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.analytics_service import AnalyticsService, StageTransition


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for send counts (>= 1 to avoid division by zero)
sends_strategy = st.integers(min_value=1, max_value=10_000)


@st.composite
def sends_replies_strategy(draw: st.DrawFn) -> tuple[int, int]:
    """Generate (sends, replies) where sends >= 1 and 0 <= replies <= sends."""
    sends = draw(sends_strategy)
    replies = draw(st.integers(min_value=0, max_value=sends))
    return sends, replies


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_transitions(count: int, stage: str) -> list[StageTransition]:
    """Create minimal stage transitions for funnel computation."""
    return [
        StageTransition(
            record_id=f"r{i}",
            stage_name=stage,
            entered_at=datetime(2024, 6, 1, 10, 0),
            exited_at=datetime(2024, 6, 2, 10, 0),
            exited_to_next=True,
        )
        for i in range(count)
    ]


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestVoiceAnalyticsSegmentation:
    """Property 8: Analytics voice segmentation correctness."""

    @given(
        voice_pair=sends_replies_strategy(),
        no_voice_pair=sends_replies_strategy(),
    )
    @settings(max_examples=200)
    def test_voice_reply_rate_equals_ratio(
        self,
        voice_pair: tuple[int, int],
        no_voice_pair: tuple[int, int],
    ) -> None:
        """FOR ANY sends/replies counts where sends >= 1 and replies <= sends,
        voice_applied_reply_rate equals round(voice_replies / voice_sends, 4).

        **Validates: Requirements 4.2**
        """
        voice_sends, voice_replies = voice_pair
        no_voice_sends, no_voice_replies = no_voice_pair

        service = AnalyticsService()
        result = service.compute_voice_segmented_funnel(
            transitions_voice=_make_transitions(1, "Sent"),
            transitions_no_voice=_make_transitions(1, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=voice_sends,
            voice_replies=voice_replies,
            no_voice_sends=no_voice_sends,
            no_voice_replies=no_voice_replies,
        )

        expected_voice_rr = round(voice_replies / voice_sends, 4)
        assert result.voice_applied_reply_rate == expected_voice_rr, (
            f"voice_applied_reply_rate mismatch: expected {expected_voice_rr}, "
            f"got {result.voice_applied_reply_rate} "
            f"(voice_sends={voice_sends}, voice_replies={voice_replies})"
        )

    @given(
        voice_pair=sends_replies_strategy(),
        no_voice_pair=sends_replies_strategy(),
    )
    @settings(max_examples=200)
    def test_no_voice_reply_rate_equals_ratio(
        self,
        voice_pair: tuple[int, int],
        no_voice_pair: tuple[int, int],
    ) -> None:
        """FOR ANY sends/replies counts where sends >= 1 and replies <= sends,
        no_voice_reply_rate equals round(no_voice_replies / no_voice_sends, 4).

        **Validates: Requirements 4.2**
        """
        voice_sends, voice_replies = voice_pair
        no_voice_sends, no_voice_replies = no_voice_pair

        service = AnalyticsService()
        result = service.compute_voice_segmented_funnel(
            transitions_voice=_make_transitions(1, "Sent"),
            transitions_no_voice=_make_transitions(1, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=voice_sends,
            voice_replies=voice_replies,
            no_voice_sends=no_voice_sends,
            no_voice_replies=no_voice_replies,
        )

        expected_no_voice_rr = round(no_voice_replies / no_voice_sends, 4)
        assert result.no_voice_reply_rate == expected_no_voice_rr, (
            f"no_voice_reply_rate mismatch: expected {expected_no_voice_rr}, "
            f"got {result.no_voice_reply_rate} "
            f"(no_voice_sends={no_voice_sends}, no_voice_replies={no_voice_replies})"
        )

    @given(
        voice_pair=sends_replies_strategy(),
        no_voice_pair=sends_replies_strategy(),
    )
    @settings(max_examples=200)
    def test_rates_computed_independently(
        self,
        voice_pair: tuple[int, int],
        no_voice_pair: tuple[int, int],
    ) -> None:
        """FOR ANY sends/replies counts, changing one segment's counts does not
        affect the other segment's reply rate — rates are computed independently.

        We verify this by computing the funnel once, then computing with different
        no_voice values and confirming voice_applied_reply_rate is unchanged, and
        vice versa.

        **Validates: Requirements 4.2**
        """
        voice_sends, voice_replies = voice_pair
        no_voice_sends, no_voice_replies = no_voice_pair

        service = AnalyticsService()

        # Compute with original values
        result = service.compute_voice_segmented_funnel(
            transitions_voice=_make_transitions(1, "Sent"),
            transitions_no_voice=_make_transitions(1, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=voice_sends,
            voice_replies=voice_replies,
            no_voice_sends=no_voice_sends,
            no_voice_replies=no_voice_replies,
        )

        # Compute with different no_voice values — voice rate should not change
        alt_no_voice_sends = max(1, (no_voice_sends + 7) % 10_000)
        alt_no_voice_replies = min(voice_replies, alt_no_voice_sends)
        result_alt_no_voice = service.compute_voice_segmented_funnel(
            transitions_voice=_make_transitions(1, "Sent"),
            transitions_no_voice=_make_transitions(1, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=voice_sends,
            voice_replies=voice_replies,
            no_voice_sends=alt_no_voice_sends,
            no_voice_replies=alt_no_voice_replies,
        )

        assert result.voice_applied_reply_rate == result_alt_no_voice.voice_applied_reply_rate, (
            f"Changing no_voice counts affected voice_applied_reply_rate: "
            f"original={result.voice_applied_reply_rate}, "
            f"after change={result_alt_no_voice.voice_applied_reply_rate}"
        )

        # Compute with different voice values — no_voice rate should not change
        alt_voice_sends = max(1, (voice_sends + 13) % 10_000)
        alt_voice_replies = min(no_voice_replies, alt_voice_sends)
        result_alt_voice = service.compute_voice_segmented_funnel(
            transitions_voice=_make_transitions(1, "Sent"),
            transitions_no_voice=_make_transitions(1, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=alt_voice_sends,
            voice_replies=alt_voice_replies,
            no_voice_sends=no_voice_sends,
            no_voice_replies=no_voice_replies,
        )

        assert result.no_voice_reply_rate == result_alt_voice.no_voice_reply_rate, (
            f"Changing voice counts affected no_voice_reply_rate: "
            f"original={result.no_voice_reply_rate}, "
            f"after change={result_alt_voice.no_voice_reply_rate}"
        )
