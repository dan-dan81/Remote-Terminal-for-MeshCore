"""WebSocket router for real-time updates."""

import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.radio import radio_manager
from app.repository import ChannelRepository, ContactRepository, RawPacketRepository
from app.websocket import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await ws_manager.connect(websocket)

    # Send initial state
    try:
        # Health status
        db_size_mb = 0.0
        try:
            db_size_bytes = os.path.getsize(settings.database_path)
            db_size_mb = round(db_size_bytes / (1024 * 1024), 2)
        except OSError:
            pass

        # Get oldest undecrypted packet info
        oldest_ts = None
        try:
            oldest_ts = await RawPacketRepository.get_oldest_undecrypted()
        except RuntimeError:
            pass  # Database not connected

        health_data = {
            "status": "ok" if radio_manager.is_connected else "degraded",
            "radio_connected": radio_manager.is_connected,
            "serial_port": radio_manager.port,
            "database_size_mb": db_size_mb,
            "oldest_undecrypted_timestamp": oldest_ts,
        }
        await ws_manager.send_personal(websocket, "health", health_data)

        # Contacts
        contacts = await ContactRepository.get_all(limit=500)
        await ws_manager.send_personal(
            websocket,
            "contacts",
            [c.model_dump() for c in contacts],
        )

        # Channels
        channels = await ChannelRepository.get_all()
        await ws_manager.send_personal(
            websocket,
            "channels",
            [c.model_dump() for c in channels],
        )

    except Exception as e:
        logger.error("Error sending initial state: %s", e)

    # Keep connection alive and handle incoming messages
    try:
        while True:
            # We don't expect messages from client, but need to keep connection open
            # and handle pings/pongs
            data = await websocket.receive_text()
            # Client can send "ping" to keep alive
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
        await ws_manager.disconnect(websocket)
