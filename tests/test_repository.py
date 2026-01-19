"""Tests for repository layer, specifically the add_path method."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMessageRepositoryAddPath:
    """Test MessageRepository.add_path method."""

    @pytest.mark.asyncio
    async def test_add_path_to_message_with_no_existing_paths(self):
        """Adding a path to a message with no existing paths creates a new array."""

        # Mock the database connection
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"paths": None})
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.add_path(
                message_id=42, path="1A2B", received_at=1700000000
            )

        assert len(result) == 1
        assert result[0].path == "1A2B"
        assert result[0].received_at == 1700000000

        # Verify the UPDATE was called with correct JSON
        update_call = mock_conn.execute.call_args_list[-1]
        assert update_call[0][0] == "UPDATE messages SET paths = ? WHERE id = ?"
        paths_json = update_call[0][1][0]
        parsed = json.loads(paths_json)
        assert len(parsed) == 1
        assert parsed[0]["path"] == "1A2B"

    @pytest.mark.asyncio
    async def test_add_path_to_message_with_existing_paths(self):
        """Adding a path to a message with existing paths appends to the array."""
        existing_paths = json.dumps([{"path": "1A", "received_at": 1699999999}])

        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"paths": existing_paths})
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.add_path(
                message_id=42, path="2B3C", received_at=1700000000
            )

        assert len(result) == 2
        assert result[0].path == "1A"
        assert result[1].path == "2B3C"

        # Verify the UPDATE contains both paths
        update_call = mock_conn.execute.call_args_list[-1]
        paths_json = update_call[0][1][0]
        parsed = json.loads(paths_json)
        assert len(parsed) == 2
        assert parsed[0]["path"] == "1A"
        assert parsed[1]["path"] == "2B3C"

    @pytest.mark.asyncio
    async def test_add_path_to_nonexistent_message_returns_empty(self):
        """Adding a path to a nonexistent message returns empty list."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.add_path(
                message_id=999, path="1A2B", received_at=1700000000
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_add_path_handles_corrupted_json(self):
        """Adding a path handles corrupted JSON in existing paths gracefully."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"paths": "not valid json {"})
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.add_path(
                message_id=42, path="1A2B", received_at=1700000000
            )

        # Should recover and create new array with just the new path
        assert len(result) == 1
        assert result[0].path == "1A2B"

    @pytest.mark.asyncio
    async def test_add_path_uses_current_time_if_not_provided(self):
        """Adding a path without received_at uses current timestamp."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"paths": None})
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db), patch("app.repository.time") as mock_time:
            mock_time.time.return_value = 1700000500.5

            from app.repository import MessageRepository

            result = await MessageRepository.add_path(message_id=42, path="1A2B")

        assert len(result) == 1
        assert result[0].received_at == 1700000500

    @pytest.mark.asyncio
    async def test_add_empty_path_for_direct_message(self):
        """Adding an empty path (direct message) works correctly."""
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"paths": None})
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("app.repository.db", mock_db):
            from app.repository import MessageRepository

            result = await MessageRepository.add_path(
                message_id=42, path="", received_at=1700000000
            )

        assert len(result) == 1
        assert result[0].path == ""  # Empty path = direct
        assert result[0].received_at == 1700000000


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
