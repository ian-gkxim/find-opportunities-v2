"""Unit tests for WebSocket heatmap notification (broadcast_heatmap_available).

Tests cover:
- Publishing correct JSON payload to Redis "gap_updates" channel
- Payload structure: type, beneficiary_id, heatmap_id, generated_at
- Connected clients receive the notification via _send_to_all
- Fallback to module-level publish_event when no redis_client provided

Requirements validated: 3.5
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.websocket_manager import WebSocketManager


class FakeWebSocket:
    """Minimal WebSocket mock for testing connection management."""

    def __init__(self, client_id: str = "ws-1"):
        self.client_id = client_id
        self.accepted = False
        self.sent_messages: list[str] = []
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, data: str):
        if self.closed:
            raise RuntimeError("WebSocket is closed")
        self.sent_messages.append(data)


class FakeRedisClient:
    """Minimal Redis mock for testing pub/sub publishing."""

    def __init__(self):
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


@pytest.fixture
def redis_client():
    return FakeRedisClient()


@pytest.fixture
def manager(redis_client):
    return WebSocketManager(redis_client=redis_client)


# ---------------------------------------------------------------------------
# broadcast_heatmap_available — Redis Publishing Tests
# ---------------------------------------------------------------------------


class TestBroadcastHeatmapAvailableRedis:
    """Tests that broadcast_heatmap_available publishes correct payload to Redis."""

    @pytest.mark.asyncio
    async def test_publishes_to_gap_updates_channel(self, manager, redis_client):
        """Verify message is published to the 'gap_updates' Redis channel."""
        await manager.broadcast_heatmap_available(
            beneficiary_id="consultant_1",
            heatmap_id="heatmap-uuid-123",
            generated_at="2024-01-15T02:30:00Z",
        )

        assert len(redis_client.published) == 1
        channel, _ = redis_client.published[0]
        assert channel == "gap_updates"

    @pytest.mark.asyncio
    async def test_payload_contains_correct_type(self, manager, redis_client):
        """Verify payload type field is 'gap_heatmap_available'."""
        await manager.broadcast_heatmap_available(
            beneficiary_id="consultant_1",
            heatmap_id="heatmap-uuid-123",
            generated_at="2024-01-15T02:30:00Z",
        )

        _, raw_msg = redis_client.published[0]
        msg = json.loads(raw_msg)
        assert msg["type"] == "gap_heatmap_available"

    @pytest.mark.asyncio
    async def test_payload_contains_beneficiary_id(self, manager, redis_client):
        """Verify payload includes the correct beneficiary_id."""
        await manager.broadcast_heatmap_available(
            beneficiary_id="consultant_42",
            heatmap_id="hm-1",
            generated_at="2024-06-01T10:00:00Z",
        )

        _, raw_msg = redis_client.published[0]
        msg = json.loads(raw_msg)
        assert msg["beneficiary_id"] == "consultant_42"

    @pytest.mark.asyncio
    async def test_payload_contains_heatmap_id(self, manager, redis_client):
        """Verify payload includes the correct heatmap_id."""
        await manager.broadcast_heatmap_available(
            beneficiary_id="consultant_1",
            heatmap_id="abc-def-ghi-789",
            generated_at="2024-01-15T02:30:00Z",
        )

        _, raw_msg = redis_client.published[0]
        msg = json.loads(raw_msg)
        assert msg["heatmap_id"] == "abc-def-ghi-789"

    @pytest.mark.asyncio
    async def test_payload_contains_generated_at(self, manager, redis_client):
        """Verify payload includes the correct generated_at timestamp."""
        await manager.broadcast_heatmap_available(
            beneficiary_id="consultant_1",
            heatmap_id="hm-1",
            generated_at="2024-12-25T00:00:00Z",
        )

        _, raw_msg = redis_client.published[0]
        msg = json.loads(raw_msg)
        assert msg["generated_at"] == "2024-12-25T00:00:00Z"

    @pytest.mark.asyncio
    async def test_payload_has_exactly_four_fields(self, manager, redis_client):
        """Verify the payload contains exactly type, beneficiary_id, heatmap_id, generated_at."""
        await manager.broadcast_heatmap_available(
            beneficiary_id="consultant_1",
            heatmap_id="hm-1",
            generated_at="2024-01-15T02:30:00Z",
        )

        _, raw_msg = redis_client.published[0]
        msg = json.loads(raw_msg)
        expected_keys = {"type", "beneficiary_id", "heatmap_id", "generated_at"}
        assert set(msg.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_firm_level_beneficiary_id(self, manager, redis_client):
        """Verify __firm__ beneficiary_id is published correctly."""
        await manager.broadcast_heatmap_available(
            beneficiary_id="__firm__",
            heatmap_id="firm-heatmap-uuid",
            generated_at="2024-03-01T02:30:00Z",
        )

        _, raw_msg = redis_client.published[0]
        msg = json.loads(raw_msg)
        assert msg["beneficiary_id"] == "__firm__"
        assert msg["type"] == "gap_heatmap_available"


# ---------------------------------------------------------------------------
# broadcast_heatmap_available — Client Delivery Tests
# ---------------------------------------------------------------------------


class TestBroadcastHeatmapAvailableClientDelivery:
    """Tests that connected clients receive the heatmap notification."""

    @pytest.mark.asyncio
    async def test_connected_client_receives_notification(self, manager):
        """Verify a single connected client receives the heatmap message."""
        ws = FakeWebSocket("ws-1")
        await manager.connect("user-1", ws)

        await manager.broadcast_heatmap_available(
            beneficiary_id="consultant_1",
            heatmap_id="hm-1",
            generated_at="2024-01-15T02:30:00Z",
        )

        assert len(ws.sent_messages) == 1
        msg = json.loads(ws.sent_messages[0])
        assert msg["type"] == "gap_heatmap_available"
        assert msg["beneficiary_id"] == "consultant_1"
        assert msg["heatmap_id"] == "hm-1"
        assert msg["generated_at"] == "2024-01-15T02:30:00Z"

    @pytest.mark.asyncio
    async def test_multiple_clients_receive_notification(self, manager):
        """Verify all connected clients receive the heatmap message."""
        ws_a = FakeWebSocket("a")
        ws_b = FakeWebSocket("b")
        ws_c = FakeWebSocket("c")
        await manager.connect("user-1", ws_a)
        await manager.connect("user-2", ws_b)
        await manager.connect("user-1", ws_c)

        await manager.broadcast_heatmap_available(
            beneficiary_id="consultant_1",
            heatmap_id="hm-1",
            generated_at="2024-01-15T02:30:00Z",
        )

        for ws in [ws_a, ws_b, ws_c]:
            assert len(ws.sent_messages) == 1
            msg = json.loads(ws.sent_messages[0])
            assert msg["type"] == "gap_heatmap_available"

    @pytest.mark.asyncio
    async def test_dead_connection_cleaned_up_during_broadcast(self, manager):
        """Verify dead connections are removed when broadcast encounters them."""
        ws_alive = FakeWebSocket("alive")
        ws_dead = FakeWebSocket("dead")
        ws_dead.closed = True

        await manager.connect("user-1", ws_alive)
        await manager.connect("user-1", ws_dead)

        await manager.broadcast_heatmap_available(
            beneficiary_id="consultant_1",
            heatmap_id="hm-1",
            generated_at="2024-01-15T02:30:00Z",
        )

        # Alive connection received the message
        assert len(ws_alive.sent_messages) == 1
        # Dead connection was cleaned up
        assert ws_dead not in manager.active_connections.get("user-1", [])

    @pytest.mark.asyncio
    async def test_no_clients_connected_no_error(self, manager):
        """Verify broadcast works gracefully with no connected clients."""
        # Should not raise
        await manager.broadcast_heatmap_available(
            beneficiary_id="consultant_1",
            heatmap_id="hm-1",
            generated_at="2024-01-15T02:30:00Z",
        )


# ---------------------------------------------------------------------------
# broadcast_heatmap_available — Fallback Publishing Tests
# ---------------------------------------------------------------------------


class TestBroadcastHeatmapAvailableFallback:
    """Tests fallback to module-level publish_event when no redis_client."""

    @pytest.mark.asyncio
    async def test_uses_publish_event_when_no_redis_client(self):
        """Verify module-level publish_event is used when redis_client is None."""
        manager = WebSocketManager(redis_client=None)

        with patch(
            "app.core.websocket_manager.publish_event", new_callable=AsyncMock
        ) as mock_pub:
            mock_pub.return_value = 1
            await manager.broadcast_heatmap_available(
                beneficiary_id="consultant_1",
                heatmap_id="hm-fallback",
                generated_at="2024-01-15T02:30:00Z",
            )

            mock_pub.assert_called_once()
            call_args = mock_pub.call_args
            assert call_args[0][0] == "gap_updates"

            msg = json.loads(call_args[0][1])
            assert msg["type"] == "gap_heatmap_available"
            assert msg["beneficiary_id"] == "consultant_1"
            assert msg["heatmap_id"] == "hm-fallback"
            assert msg["generated_at"] == "2024-01-15T02:30:00Z"
