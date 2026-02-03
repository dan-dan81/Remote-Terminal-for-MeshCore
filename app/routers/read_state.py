"""Read state management endpoints."""

import logging
import time

from fastapi import APIRouter, Query

from app.database import db
from app.models import UnreadCounts
from app.repository import MessageRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/read-state", tags=["read-state"])


@router.get("/unreads", response_model=UnreadCounts)
async def get_unreads(
    name: str | None = Query(default=None, description="User's name for @mention detection"),
) -> UnreadCounts:
    """Get unread counts, mention flags, and last message times for all conversations.

    Computes unread counts server-side using last_read_at timestamps on
    channels and contacts, avoiding the need to fetch bulk messages.
    """
    data = await MessageRepository.get_unread_counts(name)
    return UnreadCounts(**data)


@router.post("/mark-all-read")
async def mark_all_read() -> dict:
    """Mark all contacts and channels as read.

    Updates last_read_at to current timestamp for all contacts and channels
    in a single database transaction.
    """
    now = int(time.time())

    # Update all contacts and channels in one transaction
    await db.conn.execute("UPDATE contacts SET last_read_at = ?", (now,))
    await db.conn.execute("UPDATE channels SET last_read_at = ?", (now,))
    await db.conn.commit()

    logger.info("Marked all contacts and channels as read at %d", now)
    return {"status": "ok", "timestamp": now}
