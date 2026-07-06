"""Unit tests for WebSocketManager.

Tests cover:
- Connection tracking (connect, disconnect, multiple connections per user)
- Broadcasting pipeline updates via Redis pub/sub
- Broadcasting notifications via Redis pub/sub
- Broadcasting score changes via Redis pub/sub
- Graceful handling of connection drops
- Client message handling (ping/pong)
- Cleanup of empty user entries

Requirements validated: 8.4, 16.2, 16.6
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.websocket_manager import WebSocketManager


class FakeWebSocket:
    """Minimal WebSocket mock for testing connection management."""

    def __init__(self, client_id: str = "ws-1"):
        self.client_id = client_id
        self.accepted = False
        self.sent_messages: list[str] = []
        self.closed = False
        self._receive_queue: list[str] = []

    async def accept(self):
        self.accepted = True

    async def send_text(self, data: str):
        if self.closed:
            raise RuntimeError("WebSocket is closed")
        self.sent_messages.append(data)

    async def receive_text(self) -> str:
        if self._receive_queue:
            return self._receive_queue.pop(0)
        raise Exception("No more messages")

    def enqueue_message(self, data: str):
        """Queue a message to be returned by receive_text."""
        self._receive_queue.append(data)


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


@pytest.fixture
def ws():
    return FakeWebSocket("ws-1")


@pytest.fixture
def ws2():
    return FakeWebSocket("ws-2")


# ---------------------------------------------------------------------------
# Connection Management Tests
# ---------------------------------------------------------------------------


class TestConnect:
    """Tests for WebSocketManager.connect()"""

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(self, manager, ws):
        await manager.connect("user-1", ws)
        assert ws.accepted is True

    @pytest.mark.asyncio
    async def test_connect_registers_connection(self, manager, ws):
        await manager.connect("user-1", ws)
        assert ws in manager.active_connections["user-1"]

    @pytest.mark.asyncio
    async def test_connect_multiple_per_user(self, manager, ws, ws2):
        await manager.connect("user-1", ws)
        await manager.connect("user-1", ws2)
        assert len(manager.active_connections["user-1"]) == 2
        assert ws in manager.active_connections["user-1"]
        assert ws2 in manager.active_connections["user-1"]

    @pytest.mark.asyncio
    async def test_connect_multiple_users(self, manager, ws, ws2):
        await manager.connect("user-1", ws)
        await manager.connect("user-2", ws2)
        assert "user-1" in manager.active_connections
        assert "user-2" in manager.active_connections
        assert manager.total_connections == 2

    @pytest.mark.asyncio
    async def test_total_connections_count(self, manager):
        ws_a = FakeWebSocket("a")
        ws_b = FakeWebSocket("b")
        ws_c = FakeWebSocket("c")
        await manager.connect("user-1", ws_a)
        await manager.connect("user-1", ws_b)
        await manager.connect("user-2", ws_c)
        assert manager.total_connections == 3


class TestDisconnect:
    """Tests for WebSocketManager.disconnect()"""

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self, manager, ws):
        await manager.connect("user-1", ws)
        await manager.disconnect("user-1", ws)
        assert "user-1" not in manager.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_one_of_multiple(self, manager, ws, ws2):
        await manager.connect("user-1", ws)
        await manager.connect("user-1", ws2)
        await manager.disconnect("user-1", ws)
        assert ws not in manager.active_connections["user-1"]
        assert ws2 in manager.active_connections["user-1"]

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_empty_user(self, manager, ws):
        await manager.connect("user-1", ws)
        await manager.disconnect("user-1", ws)
        assert "user-1" not in manager.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_unknown_user_no_error(self, manager, ws):
        # Should not raise even if user never connected
        await manager.disconnect("unknown-user", ws)

    @pytest.mark.asyncio
    async def test_disconnect_already_removed_no_error(self, manager, ws):
        await manager.connect("user-1", ws)
        await manager.disconnect("user-1", ws)
        # Calling disconnect again should be safe
        await manager.disconnect("user-1", ws)


# ---------------------------------------------------------------------------
# Broadcasting Tests
# ---------------------------------------------------------------------------


class TestBroadcastPipelineUpdate:
    """Tests for broadcast_pipeline_update via Redis pub/sub."""

    @pytest.mark.asyncio
    async def test_publishes_to_pipeline_updates_channel(self, manager, redis_client):
        await manager.broadcast_pipeline_update("rec-123", "Replied")

        assert len(redis_client.published) == 1
        channel, raw_msg = redis_client.published[0]
        assert channel == "pipeline_updates"

        msg = json.loads(raw_msg)
        assert msg["type"] == "pipeline_update"
        assert msg["record_id"] == "rec-123"
        assert msg["status"] == "Replied"

    @pytest.mark.asyncio
    async def test_includes_metadata_when_provided(self, manager, redis_client):
        metadata = {"prospect_name": "Acme Corp", "opportunity_type": "cold_outreach"}
        await manager.broadcast_pipeline_update("rec-456", "Meeting Booked", metadata=metadata)

        _, raw_msg = redis_client.published[0]
        msg = json.loads(raw_msg)
        assert msg["metadata"] == metadata

    @pytest.mark.asyncio
    async def test_no_metadata_key_when_not_provided(self, manager, redis_client):
        await manager.broadcast_pipeline_update("rec-789", "Sent")

        _, raw_msg = redis_client.published[0]
        msg = json.loads(raw_msg)
        assert "metadata" not in msg


class TestBroadcastNotification:
    """Tests for broadcast_notification via Redis pub/sub."""

    @pytest.mark.asyncio
    async def test_publishes_to_notifications_channel(self, manager, redis_client):
        notification = {
            "category": "requires_action",
            "title": "Enrichment failed",
            "message": "Company X enrichment failed after 3 retries",
        }
        await manager.broadcast_notification(notification)

        assert len(redis_client.published) == 1
        channel, raw_msg = redis_client.published[0]
        assert channel == "notifications"

        msg = json.loads(raw_msg)
        assert msg["type"] == "notification"
        assert msg["category"] == "requires_action"
        assert msg["title"] == "Enrichment failed"

    @pytest.mark.asyncio
    async def test_merges_notification_with_type(self, manager, redis_client):
        notification = {"category": "alert", "severity": "high"}
        await manager.broadcast_notification(notification)

        _, raw_msg = redis_client.published[0]
        msg = json.loads(raw_msg)
        # "type" is always added as "notification"
        assert msg["type"] == "notification"
        assert msg["category"] == "alert"
        assert msg["severity"] == "high"


class TestBroadcastScoreChange:
    """Tests for broadcast_score_change via Redis pub/sub."""

    @pytest.mark.asyncio
    async def test_publishes_to_score_changes_channel(self, manager, redis_client):
        await manager.broadcast_score_change("prospect-1", 85, "A-tier")

        assert len(redis_client.published) == 1
        channel, raw_msg = redis_client.published[0]
        assert channel == "score_changes"

        msg = json.loads(raw_msg)
        assert msg["type"] == "score_change"
        assert msg["prospect_id"] == "prospect-1"
        assert msg["score"] == 85
        assert msg["tier"] == "A-tier"


# ---------------------------------------------------------------------------
# Message Delivery Tests
# ---------------------------------------------------------------------------


class TestSendToAll:
    """Tests for _send_to_all delivering messages to connected clients."""

    @pytest.mark.asyncio
    async def test_sends_to_all_connected_users(self, manager):
        ws_a = FakeWebSocket("a")
        ws_b = FakeWebSocket("b")
        await manager.connect("user-1", ws_a)
        await manager.connect("user-2", ws_b)

        message = json.dumps({"type": "test", "data": "hello"})
        await manager._send_to_all(message)

        assert message in ws_a.sent_messages
        assert message in ws_b.sent_messages

    @pytest.mark.asyncio
    async def test_sends_to_all_connections_of_same_user(self, manager):
        ws_a = FakeWebSocket("a")
        ws_b = FakeWebSocket("b")
        await manager.connect("user-1", ws_a)
        await manager.connect("user-1", ws_b)

        message = json.dumps({"type": "test"})
        await manager._send_to_all(message)

        assert message in ws_a.sent_messages
        assert message in ws_b.sent_messages


class TestConnectionDropHandling:
    """Tests for graceful handling of dropped connections."""

    @pytest.mark.asyncio
    async def test_dead_connection_removed_on_send(self, manager):
        ws_alive = FakeWebSocket("alive")
        ws_dead = FakeWebSocket("dead")
        ws_dead.closed = True  # Simulate broken connection

        await manager.connect("user-1", ws_alive)
        await manager.connect("user-1", ws_dead)

        message = json.dumps({"type": "test"})
        await manager._send_to_all(message)

        # Alive connection received the message
        assert message in ws_alive.sent_messages
        # Dead connection was cleaned up
        assert ws_dead not in manager.active_connections.get("user-1", [])

    @pytest.mark.asyncio
    async def test_all_dead_connections_cleaned_up(self, manager):
        ws_dead1 = FakeWebSocket("dead1")
        ws_dead1.closed = True
        ws_dead2 = FakeWebSocket("dead2")
        ws_dead2.closed = True

        await manager.connect("user-1", ws_dead1)
        await manager.connect("user-1", ws_dead2)

        await manager._send_to_all(json.dumps({"type": "test"}))

        # User should be completely removed since all connections are dead
        assert "user-1" not in manager.active_connections

    @pytest.mark.asyncio
    async def test_send_to_user_with_no_connections(self, manager):
        # Should not raise
        await manager._send_to_user("nonexistent-user", '{"type": "test"}')


# ---------------------------------------------------------------------------
# Client Message Handling Tests
# ---------------------------------------------------------------------------


class TestHandleClientMessage:
    """Tests for _handle_client_message processing."""

    @pytest.mark.asyncio
    async def test_ping_responds_with_pong(self, manager, ws):
        await manager.connect("user-1", ws)
        await manager._handle_client_message(
            "user-1", ws, json.dumps({"type": "ping"})
        )

        assert len(ws.sent_messages) == 1
        response = json.loads(ws.sent_messages[0])
        assert response == {"type": "pong"}

    @pytest.mark.asyncio
    async def test_invalid_json_ignored(self, manager, ws):
        await manager.connect("user-1", ws)
        # Should not raise
        await manager._handle_client_message("user-1", ws, "not valid json")
        assert len(ws.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_unknown_message_type_no_response(self, manager, ws):
        await manager.connect("user-1", ws)
        await manager._handle_client_message(
            "user-1", ws, json.dumps({"type": "unknown_action"})
        )
        assert len(ws.sent_messages) == 0


# ---------------------------------------------------------------------------
# Fallback to module-level publish_event Tests
# ---------------------------------------------------------------------------


class TestFallbackPublishing:
    """Tests that publishing works via module-level helpers when no redis_client."""

    @pytest.mark.asyncio
    async def test_broadcast_uses_publish_event_when_no_redis(self):
        manager = WebSocketManager(redis_client=None)

        with patch("app.core.websocket_manager.publish_event", new_callable=AsyncMock) as mock_pub:
            mock_pub.return_value = 1
            await manager.broadcast_pipeline_update("rec-1", "Sent")

            mock_pub.assert_called_once()
            call_args = mock_pub.call_args
            assert call_args[0][0] == "pipeline_updates"
            msg = json.loads(call_args[0][1])
            assert msg["record_id"] == "rec-1"

    @pytest.mark.asyncio
    async def test_notification_uses_publish_event_when_no_redis(self):
        manager = WebSocketManager(redis_client=None)

        with patch("app.core.websocket_manager.publish_event", new_callable=AsyncMock) as mock_pub:
            mock_pub.return_value = 1
            await manager.broadcast_notification({"category": "alert"})

            mock_pub.assert_called_once()
            call_args = mock_pub.call_args
            assert call_args[0][0] == "notifications"

    @pytest.mark.asyncio
    async def test_score_change_uses_publish_event_when_no_redis(self):
        manager = WebSocketManager(redis_client=None)

        with patch("app.core.websocket_manager.publish_event", new_callable=AsyncMock) as mock_pub:
            mock_pub.return_value = 1
            await manager.broadcast_score_change("p-1", 50, "B-tier")

            mock_pub.assert_called_once()
            call_args = mock_pub.call_args
            assert call_args[0][0] == "score_changes"
