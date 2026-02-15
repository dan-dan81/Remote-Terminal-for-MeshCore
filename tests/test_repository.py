"""Tests for repository layer."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database import Database
from app.repository import MessageRepository


@pytest.fixture
async def test_db():
    """Create an in-memory test database with the module-level db swapped in."""
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


async def _create_message(test_db, **overrides) -> int:
    """Helper to insert a message and return its id."""
    defaults = {
        "msg_type": "CHAN",
        "text": "Hello",
        "conversation_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA0",
        "sender_timestamp": 1700000000,
        "received_at": 1700000000,
    }
    defaults.update(overrides)
    msg_id = await MessageRepository.create(**defaults)
    assert msg_id is not None
    return msg_id


class TestMessageRepositoryAddPath:
    """Test MessageRepository.add_path against a real SQLite database."""

    @pytest.mark.asyncio
    async def test_add_path_to_message_with_no_existing_paths(self, test_db):
        """Adding a path to a message with no existing paths creates a new array."""
        msg_id = await _create_message(test_db)

        result = await MessageRepository.add_path(
            message_id=msg_id, path="1A2B", received_at=1700000000
        )

        assert len(result) == 1
        assert result[0].path == "1A2B"
        assert result[0].received_at == 1700000000

    @pytest.mark.asyncio
    async def test_add_path_to_message_with_existing_paths(self, test_db):
        """Adding a path to a message with existing paths appends to the array."""
        msg_id = await _create_message(test_db)

        await MessageRepository.add_path(message_id=msg_id, path="1A", received_at=1699999999)
        result = await MessageRepository.add_path(
            message_id=msg_id, path="2B3C", received_at=1700000000
        )

        assert len(result) == 2
        assert result[0].path == "1A"
        assert result[1].path == "2B3C"

    @pytest.mark.asyncio
    async def test_add_path_to_nonexistent_message_returns_empty(self, test_db):
        """Adding a path to a nonexistent message returns empty list."""
        result = await MessageRepository.add_path(
            message_id=999999, path="1A2B", received_at=1700000000
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_add_path_uses_current_time_if_not_provided(self, test_db):
        """Adding a path without received_at uses current timestamp."""
        msg_id = await _create_message(test_db)

        with patch("app.repository.time") as mock_time:
            mock_time.time.return_value = 1700000500.5
            result = await MessageRepository.add_path(message_id=msg_id, path="1A2B")

        assert len(result) == 1
        assert result[0].received_at == 1700000500

    @pytest.mark.asyncio
    async def test_add_empty_path_for_direct_message(self, test_db):
        """Adding an empty path (direct message) works correctly."""
        msg_id = await _create_message(test_db)

        result = await MessageRepository.add_path(
            message_id=msg_id, path="", received_at=1700000000
        )

        assert len(result) == 1
        assert result[0].path == ""  # Empty path = direct
        assert result[0].received_at == 1700000000

    @pytest.mark.asyncio
    async def test_add_multiple_paths_accumulate(self, test_db):
        """Multiple add_path calls accumulate all paths."""
        msg_id = await _create_message(test_db)

        await MessageRepository.add_path(msg_id, "", received_at=1700000001)
        await MessageRepository.add_path(msg_id, "1A", received_at=1700000002)
        result = await MessageRepository.add_path(msg_id, "1A2B", received_at=1700000003)

        assert len(result) == 3
        assert result[0].path == ""
        assert result[1].path == "1A"
        assert result[2].path == "1A2B"


class TestMessageRepositoryGetByContent:
    """Test MessageRepository.get_by_content method."""

    @pytest.mark.asyncio
    async def test_get_by_content_finds_matching_message(self):
        """Returns message when all content fields match."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(
            return_value={
                "id": 42,
                "type": "CHAN",
                "conversation_key": "ABCD1234",
                "text": "Hello world",
                "sender_timestamp": 1700000000,
                "received_at": 1700000001,
                "paths": None,
                "txt_type": 0,
                "signature": None,
                "outgoing": 0,
                "acked": 1,
            }
        )
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.get_by_content(
                msg_type="CHAN",
                conversation_key="ABCD1234",
                text="Hello world",
                sender_timestamp=1700000000,
            )

        assert result is not None
        assert result.id == 42
        assert result.type == "CHAN"
        assert result.conversation_key == "ABCD1234"
        assert result.text == "Hello world"
        assert result.acked == 1

    @pytest.mark.asyncio
    async def test_get_by_content_returns_none_when_not_found(self):
        """Returns None when no message matches."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.get_by_content(
                msg_type="CHAN",
                conversation_key="NONEXISTENT",
                text="Not found",
                sender_timestamp=1700000000,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_content_handles_null_sender_timestamp(self):
        """Handles messages with NULL sender_timestamp correctly."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(
            return_value={
                "id": 43,
                "type": "PRIV",
                "conversation_key": "abc123",
                "text": "Test message",
                "sender_timestamp": None,
                "received_at": 1700000001,
                "paths": None,
                "txt_type": 0,
                "signature": None,
                "outgoing": 1,
                "acked": 0,
            }
        )
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.get_by_content(
                msg_type="PRIV",
                conversation_key="abc123",
                text="Test message",
                sender_timestamp=None,
            )

        assert result is not None
        assert result.sender_timestamp is None
        assert result.outgoing is True

    @pytest.mark.asyncio
    async def test_get_by_content_parses_paths_correctly(self):
        """Parses paths JSON into MessagePath objects."""
        paths_json = json.dumps(
            [
                {"path": "1A2B", "received_at": 1700000000},
                {"path": "3C4D", "received_at": 1700000001},
            ]
        )

        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(
            return_value={
                "id": 44,
                "type": "CHAN",
                "conversation_key": "ABCD1234",
                "text": "Multi-path message",
                "sender_timestamp": 1700000000,
                "received_at": 1700000000,
                "paths": paths_json,
                "txt_type": 0,
                "signature": None,
                "outgoing": 0,
                "acked": 2,
            }
        )
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.get_by_content(
                msg_type="CHAN",
                conversation_key="ABCD1234",
                text="Multi-path message",
                sender_timestamp=1700000000,
            )

        assert result is not None
        assert result.paths is not None
        assert len(result.paths) == 2
        assert result.paths[0].path == "1A2B"
        assert result.paths[1].path == "3C4D"

    @pytest.mark.asyncio
    async def test_get_by_content_handles_corrupted_paths_json(self):
        """Handles corrupted paths JSON gracefully."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(
            return_value={
                "id": 45,
                "type": "CHAN",
                "conversation_key": "ABCD1234",
                "text": "Corrupted paths",
                "sender_timestamp": 1700000000,
                "received_at": 1700000000,
                "paths": "not valid json {",
                "txt_type": 0,
                "signature": None,
                "outgoing": 0,
                "acked": 0,
            }
        )
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.get_by_content(
                msg_type="CHAN",
                conversation_key="ABCD1234",
                text="Corrupted paths",
                sender_timestamp=1700000000,
            )

        # Should return message with paths=None instead of raising
        assert result is not None
        assert result.paths is None


class TestMessageRepositoryGetAckCount:
    """Test MessageRepository.get_ack_count method."""

    @pytest.mark.asyncio
    async def test_get_ack_count_returns_count(self):
        """Returns ack count for existing message."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"acked": 3})
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.get_ack_count(message_id=42)

        assert result == 3

    @pytest.mark.asyncio
    async def test_get_ack_count_returns_zero_for_nonexistent(self):
        """Returns 0 for nonexistent message."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.get_ack_count(message_id=999)

        assert result == 0

    @pytest.mark.asyncio
    async def test_get_ack_count_returns_zero_for_unacked(self):
        """Returns 0 for message with no acks."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"acked": 0})
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.get_ack_count(message_id=42)

        assert result == 0


class TestAppSettingsRepository:
    """Test AppSettingsRepository parsing and migration edge cases."""

    @pytest.mark.asyncio
    async def test_get_handles_corrupted_json_and_invalid_sort_order(self):
        """Corrupted JSON fields are recovered with safe defaults."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(
            return_value={
                "max_radio_contacts": 250,
                "favorites": "{not-json",
                "auto_decrypt_dm_on_advert": 1,
                "sidebar_sort_order": "invalid",
                "last_message_times": "{also-not-json",
                "preferences_migrated": 0,
                "advert_interval": None,
                "last_advert_time": None,
                "bots": "{bad-bots-json",
            }
        )
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import AppSettingsRepository

            settings = await AppSettingsRepository.get()

        assert settings.max_radio_contacts == 250
        assert settings.favorites == []
        assert settings.last_message_times == {}
        assert settings.sidebar_sort_order == "recent"
        assert settings.bots == []
        assert settings.advert_interval == 0
        assert settings.last_advert_time == 0

    @pytest.mark.asyncio
    async def test_add_favorite_is_idempotent(self):
        """Adding an existing favorite does not write duplicate entries."""
        from app.models import AppSettings, Favorite

        existing = AppSettings(favorites=[Favorite(type="contact", id="aa" * 32)])

        with (
            patch(
                "app.repository.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "app.repository.AppSettingsRepository.update",
                new_callable=AsyncMock,
            ) as mock_update,
        ):
            from app.repository import AppSettingsRepository

            result = await AppSettingsRepository.add_favorite("contact", "aa" * 32)

        assert result == existing
        mock_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_migrate_preferences_uses_recent_for_invalid_sort_order(self):
        """Migration normalizes invalid sort order to 'recent'."""
        from app.models import AppSettings

        current = AppSettings(preferences_migrated=False)
        migrated = AppSettings(preferences_migrated=True, sidebar_sort_order="recent")

        with (
            patch(
                "app.repository.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=current,
            ),
            patch(
                "app.repository.AppSettingsRepository.update",
                new_callable=AsyncMock,
                return_value=migrated,
            ) as mock_update,
        ):
            from app.repository import AppSettingsRepository

            result, did_migrate = await AppSettingsRepository.migrate_preferences_from_frontend(
                favorites=[{"type": "contact", "id": "bb" * 32}],
                sort_order="weird-order",
                last_message_times={"contact-bbbbbbbbbbbb": 123},
            )

        assert did_migrate is True
        assert result.preferences_migrated is True
        assert mock_update.call_args.kwargs["sidebar_sort_order"] == "recent"
        assert mock_update.call_args.kwargs["preferences_migrated"] is True


class TestMessageRepositoryGetById:
    """Test MessageRepository.get_by_id method."""

    @pytest.mark.asyncio
    async def test_returns_message_when_exists(self, test_db):
        """Returns message for valid ID."""
        msg_id = await _create_message(test_db, text="Find me", outgoing=True)

        result = await MessageRepository.get_by_id(msg_id)

        assert result is not None
        assert result.id == msg_id
        assert result.text == "Find me"
        assert result.outgoing is True

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, test_db):
        """Returns None for nonexistent ID."""
        result = await MessageRepository.get_by_id(999999)

        assert result is None
