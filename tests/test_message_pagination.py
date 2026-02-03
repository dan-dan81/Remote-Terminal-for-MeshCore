"""Tests for message pagination using cursor parameters."""

import pytest

from app.database import Database
from app.repository import MessageRepository


@pytest.fixture
async def test_db():
    """Create an in-memory test database."""
    import app.repository as repo_module

    db = Database(":memory:")
    await db.connect()

    original_db = repo_module.db
    repo_module.db = db

    try:
        yield db
    finally:
        repo_module.db = original_db
        await db.disconnect()


@pytest.mark.asyncio
async def test_cursor_pagination_avoids_overlap(test_db):
    key = "ABC123DEF456ABC123DEF456ABC12345"

    ids = []
    for received_at, text in [(200, "m1"), (200, "m2"), (150, "m3"), (100, "m4")]:
        msg_id = await MessageRepository.create(
            msg_type="CHAN",
            text=text,
            conversation_key=key,
            sender_timestamp=received_at,
            received_at=received_at,
        )
        assert msg_id is not None
        ids.append(msg_id)

    page1 = await MessageRepository.get_all(
        msg_type="CHAN",
        conversation_key=key,
        limit=2,
        offset=0,
    )
    assert len(page1) == 2

    oldest = page1[-1]
    page2 = await MessageRepository.get_all(
        msg_type="CHAN",
        conversation_key=key,
        limit=2,
        offset=0,
        before=oldest.received_at,
        before_id=oldest.id,
    )
    assert len(page2) == 2

    ids_page1 = {m.id for m in page1}
    ids_page2 = {m.id for m in page2}
    assert ids_page1.isdisjoint(ids_page2)
