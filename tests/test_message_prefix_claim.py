"""Tests for prefix-claiming DM messages."""

import pytest

from app.database import Database
from app.repository import ContactRepository, MessageRepository


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
async def test_claim_prefix_promotes_dm_to_full_key(test_db):
    full_key = "a1b2c3d3ba9f5fa8705b9845fe11cc6f01d1d49caaf4d122ac7121663c5beec7"
    prefix = full_key[:6].upper()

    # Create the contact so the claim safety check (exactly 1 contact matches prefix) passes
    await ContactRepository.upsert({"public_key": full_key, "name": "Test"})

    msg_id = await MessageRepository.create(
        msg_type="PRIV",
        text="hello",
        conversation_key=prefix,
        sender_timestamp=123,
        received_at=123,
    )
    assert msg_id is not None

    updated = await MessageRepository.claim_prefix_messages(full_key)
    assert updated == 1

    messages = await MessageRepository.get_all(
        msg_type="PRIV",
        conversation_key=full_key,
        limit=10,
    )
    assert len(messages) == 1
    assert messages[0].conversation_key == full_key.lower()
