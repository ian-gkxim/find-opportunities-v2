"""WebSocket Manager for real-time Dashboard updates.

Requirements 8.4, 16.2, 16.6:
- Real-time pipeline updates via WebSocket, reflecting status changes within
  10 seconds without page refresh.
- Redis pub/sub enables broadcasting across multiple worker processes and
  WebSocket server instances.
- Graceful handling of connection drops and cleanup.
- Server supports reconnection gracefully (client handles exponential backoff:
  1s start, 30s cap).

Architecture:
- Per-user connection tracking (a user can have multiple browser tabs/devices)
- Redis pub/sub for multi-worker broadcast (publish to channel, all workers
  with subscribers forward to their local WebSocket connections)
- JSON message serialization for all events
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.core.redis import (
    CHANNEL_NOTIFICATIONS,
    CHANNEL_PIPELINE_UPDATES,
    CHANNEL_SCORE_CHANGES,
    publish_event,
    subscribe_channels,
)

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections for real-time Dashboard updates.

    Responsibilities:
    - Track per-user WebSocket connections (multiple connections per user)
    - Publish events to Redis pub/sub for multi-worker broadcast
    - Subscribe to Redis channels and forward messages to local connections
    - Handle connection drops gracefully (remove from tracking, log cleanup)
    """

    def __init__(self, redis_client=None):
        """Initialize the WebSocket manager.

        Args:
            redis_client: Optional Redis client instance. If provided, used
                for direct pub/sub operations. Otherwise, falls back to the
                module-level publish_event and subscribe_channels helpers.
        """
        # Per-user connection tracking: user_id -> list of WebSocket connections
        self._connections: dict[str, list[WebSocket]] = {}
        self._redis = redis_client
        self._subscriber_task: asyncio.Task | None = None
        self._running: bool = False

    @property
    def active_connections(self) -> dict[str, list[WebSocket]]:
        """Expose active connections for introspection (e.g., health checks)."""
        return self._connections

    @property
    def total_connections(self) -> int:
        """Total number of active WebSocket connections across all users."""
        return sum(len(conns) for conns in self._connections.values())

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and register it for the user.

        Args:
            user_id: Identifier for the connected user.
            websocket: The WebSocket connection to register.
        """
        await websocket.accept()
        self._connections.setdefault(user_id, []).append(websocket)
        logger.info(
            "WebSocket connected: user=%s, total_connections=%d",
            user_id,
            self.total_connections,
        )

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection for the user.

        Handles the case where the connection may already have been removed
        (e.g., due to a connection drop detected elsewhere).

        Args:
            user_id: Identifier for the user disconnecting.
            websocket: The WebSocket connection to remove.
        """
        user_connections = self._connections.get(user_id)
        if user_connections is None:
            return

        try:
            user_connections.remove(websocket)
        except ValueError:
            # Connection already removed (e.g., due to earlier cleanup)
            pass

        # Clean up empty user entries to prevent memory leaks
        if not user_connections:
            del self._connections[user_id]

        logger.info(
            "WebSocket disconnected: user=%s, remaining_connections=%d",
            user_id,
            self.total_connections,
        )

    async def broadcast_pipeline_update(
        self, record_id: str, new_status: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Broadcast a pipeline status change to all connected clients.

        Publishes the event to Redis pub/sub so that all worker processes
        can forward it to their local WebSocket connections.

        Args:
            record_id: The pipeline record ID that changed status.
            new_status: The new pipeline status.
            metadata: Optional additional data (e.g., prospect name, opportunity type).
        """
        message = {
            "type": "pipeline_update",
            "record_id": record_id,
            "status": new_status,
        }
        if metadata:
            message["metadata"] = metadata

        serialized = json.dumps(message)

        if self._redis:
            await self._redis.publish(CHANNEL_PIPELINE_UPDATES, serialized)
        else:
            await publish_event(CHANNEL_PIPELINE_UPDATES, serialized)

        logger.debug(
            "Published pipeline update: record=%s, status=%s",
            record_id,
            new_status,
        )

    async def broadcast_notification(
        self, notification: dict[str, Any]
    ) -> None:
        """Broadcast a dashboard notification to all connected clients.

        Used for alerts, action-needed items, enrichment status changes, and
        other dashboard events.

        Args:
            notification: Dictionary with notification details. Expected keys:
                - type: "notification"
                - category: e.g., "requires_action", "enrichment_error", "alert"
                - title: Short description
                - message: Detailed message
                - Additional keys as needed
        """
        message = {
            "type": "notification",
            **notification,
        }

        serialized = json.dumps(message)

        if self._redis:
            await self._redis.publish(CHANNEL_NOTIFICATIONS, serialized)
        else:
            await publish_event(CHANNEL_NOTIFICATIONS, serialized)

        logger.debug("Published notification: %s", notification.get("category", "unknown"))

    async def broadcast_score_change(
        self, prospect_id: str, new_score: int, new_tier: str
    ) -> None:
        """Broadcast a score change to all connected clients.

        Args:
            prospect_id: The prospect whose score changed.
            new_score: The new account score (0-100).
            new_tier: The new tier classification (A-tier, B-tier, etc.).
        """
        message = {
            "type": "score_change",
            "prospect_id": prospect_id,
            "score": new_score,
            "tier": new_tier,
        }

        serialized = json.dumps(message)

        if self._redis:
            await self._redis.publish(CHANNEL_SCORE_CHANGES, serialized)
        else:
            await publish_event(CHANNEL_SCORE_CHANGES, serialized)

        logger.debug(
            "Published score change: prospect=%s, score=%d, tier=%s",
            prospect_id,
            new_score,
            new_tier,
        )

    async def _send_to_user(self, user_id: str, message: str) -> None:
        """Send a message to all connections for a specific user.

        Handles connection drops by removing dead connections.

        Args:
            user_id: Target user identifier.
            message: JSON-serialized message to send.
        """
        connections = self._connections.get(user_id, [])
        dead_connections: list[WebSocket] = []

        for ws in connections:
            try:
                await ws.send_text(message)
            except (WebSocketDisconnect, RuntimeError, Exception) as e:
                # Connection dropped — mark for cleanup
                logger.warning(
                    "WebSocket send failed for user=%s: %s", user_id, str(e)
                )
                dead_connections.append(ws)

        # Clean up dead connections
        for ws in dead_connections:
            await self.disconnect(user_id, ws)

    async def _send_to_all(self, message: str) -> None:
        """Send a message to all connected users.

        Iterates over all users and their connections, cleaning up any that
        have dropped.

        Args:
            message: JSON-serialized message to send.
        """
        # Copy keys to avoid modification during iteration
        user_ids = list(self._connections.keys())
        for user_id in user_ids:
            await self._send_to_user(user_id, message)

    async def start_subscriber(self) -> None:
        """Start the Redis pub/sub subscriber background task.

        Subscribes to all broadcast channels and forwards received messages
        to local WebSocket connections. This should be called once during
        application startup.
        """
        if self._running:
            return

        self._running = True
        self._subscriber_task = asyncio.create_task(self._subscriber_loop())
        logger.info("WebSocket manager subscriber started")

    async def stop_subscriber(self) -> None:
        """Stop the Redis pub/sub subscriber background task.

        Should be called during application shutdown for clean cleanup.
        """
        self._running = False
        if self._subscriber_task is not None:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
            self._subscriber_task = None
        logger.info("WebSocket manager subscriber stopped")

    async def _subscriber_loop(self) -> None:
        """Main subscriber loop: listen to Redis pub/sub and forward to clients.

        Handles Redis connection errors with automatic reconnection.
        """
        while self._running:
            try:
                pubsub = await subscribe_channels()
                logger.info("Redis pub/sub subscription active")

                async for raw_message in pubsub.listen():
                    if not self._running:
                        break

                    if raw_message["type"] != "message":
                        continue

                    data = raw_message.get("data")
                    if data:
                        await self._send_to_all(data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Redis subscriber error: %s", str(e))
                if self._running:
                    # Brief backoff before reconnecting
                    await asyncio.sleep(1)
            finally:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:
                    pass

    async def handle_websocket(self, user_id: str, websocket: WebSocket) -> None:
        """Full lifecycle handler for a WebSocket connection.

        Accepts the connection, keeps it alive, and cleans up on disconnect.
        This is a convenience method for use in FastAPI WebSocket endpoints.

        Args:
            user_id: The authenticated user's identifier.
            websocket: The WebSocket connection from the endpoint.
        """
        await self.connect(user_id, websocket)
        try:
            while True:
                # Keep connection alive by awaiting incoming messages
                # Client can send pings or other control messages
                data = await websocket.receive_text()
                # Handle client messages (e.g., ping/pong, subscription filters)
                await self._handle_client_message(user_id, websocket, data)
        except WebSocketDisconnect:
            logger.info("Client disconnected gracefully: user=%s", user_id)
        except Exception as e:
            logger.warning("WebSocket error for user=%s: %s", user_id, str(e))
        finally:
            await self.disconnect(user_id, websocket)

    async def _handle_client_message(
        self, user_id: str, websocket: WebSocket, raw_data: str
    ) -> None:
        """Process messages received from the client.

        Currently supports:
        - ping: responds with pong for keepalive
        - Other messages are logged and ignored

        Args:
            user_id: The user who sent the message.
            websocket: The connection that received the message.
            raw_data: Raw text received from the client.
        """
        try:
            message = json.loads(raw_data)
        except json.JSONDecodeError:
            return

        msg_type = message.get("type")

        if msg_type == "ping":
            await websocket.send_text(json.dumps({"type": "pong"}))
        else:
            logger.debug(
                "Received client message: user=%s, type=%s",
                user_id,
                msg_type,
            )
