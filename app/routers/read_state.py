"""Read state management endpoints."""

import logging
import time

from fastapi import APIRouter

from app.database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/read-state", tags=["read-state"])


@router.post("/mark-all-read")
async def mark_all_read() -> dict:
    """Mark all contacts and channels as read.

    Updates last_read_at to current timestamp for all contacts and channels
    in a single database transaction.
    """
    now = int(time.time())

    # Update all contacts and channels in one transaction
    await db.conn.execute(
        "UPDATE contacts SET last_read_at = ?",
        (now,)
    )
    await db.conn.execute(
        "UPDATE channels SET last_read_at = ?",
        (now,)
    )
    await db.conn.commit()

    logger.info("Marked all contacts and channels as read at %d", now)
    return {"status": "ok", "timestamp": now}
