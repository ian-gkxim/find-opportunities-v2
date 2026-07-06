"""WebSocket endpoint for real-time dashboard updates.

Requirements 8.4, 16.2:
- WS /ws — WebSocket connection endpoint
- Accept connection with user_id from query param or auth
- Wire to WebSocketManager.handle_websocket()
"""

from fastapi import APIRouter, Query, WebSocket

from app.core.websocket_manager import WebSocketManager

router = APIRouter(tags=["websocket"])

# Module-level WebSocket manager instance.
# In production, this is initialized during app startup with a Redis client.
_ws_manager: WebSocketManager | None = None


def get_ws_manager() -> WebSocketManager:
    """Get or create the WebSocket manager singleton.

    In production, this is configured during app lifespan with Redis.
    For testing, a manager without Redis is used.
    """
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager


def set_ws_manager(manager: WebSocketManager) -> None:
    """Set the WebSocket manager instance (called during app startup)."""
    global _ws_manager
    _ws_manager = manager


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str = Query(default="anonymous", description="User identifier"),
) -> None:
    """WebSocket endpoint for real-time dashboard updates.

    Accepts a connection and delegates lifecycle management to
    WebSocketManager.handle_websocket(). The connection receives:
    - Pipeline status updates (type: "pipeline_update")
    - Dashboard notifications (type: "notification")
    - Score changes (type: "score_change")

    The client can send:
    - {"type": "ping"} — receives {"type": "pong"} back

    Connection is authenticated via user_id query parameter.
    In production, this would use token-based auth.
    """
    manager = get_ws_manager()
    await manager.handle_websocket(user_id, websocket)
