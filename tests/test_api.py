"""Tests for API endpoints.

These tests verify the REST API behavior for critical operations.
Uses FastAPI's TestClient for synchronous testing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHealthEndpoint:
    """Test the health check endpoint."""

    def test_health_returns_connection_status(self):
        """Health endpoint returns radio connection status."""
        from fastapi.testclient import TestClient

        with patch("app.routers.health.radio_manager") as mock_rm:
            mock_rm.is_connected = True
            mock_rm.port = "/dev/ttyUSB0"

            from app.main import app

            client = TestClient(app)

            response = client.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert data["radio_connected"] is True
            assert data["serial_port"] == "/dev/ttyUSB0"

    def test_health_disconnected_state(self):
        """Health endpoint reflects disconnected radio."""
        from fastapi.testclient import TestClient

        with patch("app.routers.health.radio_manager") as mock_rm:
            mock_rm.is_connected = False
            mock_rm.port = None

            from app.main import app

            client = TestClient(app)

            response = client.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert data["radio_connected"] is False
            assert data["serial_port"] is None


class TestMessagesEndpoint:
    """Test message-related endpoints."""

    def test_send_direct_message_requires_connection(self):
        """Sending message when disconnected returns 503."""
        from fastapi.testclient import TestClient

        with patch("app.dependencies.radio_manager") as mock_rm:
            mock_rm.is_connected = False
            mock_rm.meshcore = None

            from app.main import app

            client = TestClient(app)

            response = client.post(
                "/api/messages/direct", json={"destination": "abc123", "text": "Hello"}
            )

            assert response.status_code == 503
            assert "not connected" in response.json()["detail"].lower()

    def test_send_channel_message_requires_connection(self):
        """Sending channel message when disconnected returns 503."""
        from fastapi.testclient import TestClient

        with patch("app.dependencies.radio_manager") as mock_rm:
            mock_rm.is_connected = False
            mock_rm.meshcore = None

            from app.main import app

            client = TestClient(app)

            response = client.post(
                "/api/messages/channel",
                json={"channel_key": "0123456789ABCDEF0123456789ABCDEF", "text": "Hello"},
            )

            assert response.status_code == 503

    def test_send_direct_message_contact_not_found(self):
        """Sending to unknown contact returns 404."""
        from fastapi.testclient import TestClient

        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix.return_value = None

        with (
            patch("app.dependencies.radio_manager") as mock_rm,
            patch(
                "app.repository.ContactRepository.get_by_key_or_prefix", new_callable=AsyncMock
            ) as mock_get,
        ):
            mock_rm.is_connected = True
            mock_rm.meshcore = mock_mc
            mock_get.return_value = None

            from app.main import app

            client = TestClient(app)

            response = client.post(
                "/api/messages/direct", json={"destination": "nonexistent", "text": "Hello"}
            )

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_send_direct_message_duplicate_returns_500(self):
        """If MessageRepository.create returns None (duplicate), returns 500."""
        from app.models import SendDirectMessageRequest
        from app.routers.messages import send_direct_message

        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix.return_value = {"public_key": "a" * 64}

        mock_add_result = MagicMock()
        mock_add_result.type = MagicMock()
        mock_add_result.type.name = "OK"
        mock_mc.commands.add_contact = AsyncMock(return_value=mock_add_result)

        mock_send_result = MagicMock()
        mock_send_result.type = MagicMock()
        mock_send_result.type.name = "OK"
        mock_send_result.payload = {"expected_ack": b"\x00\x01"}
        mock_mc.commands.send_msg = AsyncMock(return_value=mock_send_result)

        mock_contact = MagicMock()
        mock_contact.public_key = "a" * 64
        mock_contact.to_radio_dict.return_value = {"public_key": "a" * 64}

        with (
            patch("app.dependencies.radio_manager") as mock_rm,
            patch("app.repository.ContactRepository") as mock_contact_repo,
            patch("app.routers.messages.MessageRepository") as mock_msg_repo,
        ):
            mock_rm.is_connected = True
            mock_rm.meshcore = mock_mc
            mock_contact_repo.get_by_key_or_prefix = AsyncMock(return_value=mock_contact)
            mock_contact_repo.update_last_contacted = AsyncMock()
            # Simulate duplicate - create returns None
            mock_msg_repo.create = AsyncMock(return_value=None)

            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await send_direct_message(
                    SendDirectMessageRequest(destination="a" * 64, text="Hello")
                )

            assert exc_info.value.status_code == 500
            assert "unexpected duplicate" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_send_channel_message_duplicate_returns_500(self):
        """If MessageRepository.create returns None (duplicate), returns 500."""
        from app.models import SendChannelMessageRequest
        from app.routers.messages import send_channel_message

        mock_mc = MagicMock()
        mock_send_result = MagicMock()
        mock_send_result.type = MagicMock()
        mock_send_result.type.name = "OK"
        mock_send_result.payload = {}
        mock_mc.commands.send_chan_msg = AsyncMock(return_value=mock_send_result)
        mock_mc.commands.set_channel = AsyncMock(return_value=mock_send_result)

        mock_channel = MagicMock()
        mock_channel.name = "test"
        mock_channel.key = "0123456789ABCDEF0123456789ABCDEF"

        with (
            patch("app.dependencies.radio_manager") as mock_rm,
            patch("app.repository.ChannelRepository") as mock_chan_repo,
            patch("app.routers.messages.MessageRepository") as mock_msg_repo,
        ):
            mock_rm.is_connected = True
            mock_rm.meshcore = mock_mc
            mock_chan_repo.get_by_key = AsyncMock(return_value=mock_channel)
            # Simulate duplicate - create returns None
            mock_msg_repo.create = AsyncMock(return_value=None)

            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await send_channel_message(
                    SendChannelMessageRequest(
                        channel_key="0123456789ABCDEF0123456789ABCDEF", text="Hello"
                    )
                )

            assert exc_info.value.status_code == 500
            assert "unexpected duplicate" in exc_info.value.detail.lower()


class TestChannelsEndpoint:
    """Test channel-related endpoints."""

    @pytest.mark.asyncio
    async def test_create_hashtag_channel_derives_key(self):
        """Creating hashtag channel derives key from name and stores in DB."""
        import hashlib

        from app.routers.channels import CreateChannelRequest, create_channel

        with patch("app.routers.channels.ChannelRepository") as mock_repo:
            mock_repo.upsert = AsyncMock()

            request = CreateChannelRequest(name="#mychannel")

            result = await create_channel(request)

            # Verify the key derivation - channel stored in DB, not pushed to radio
            expected_key_hex = hashlib.sha256(b"#mychannel").digest()[:16].hex().upper()
            mock_repo.upsert.assert_called_once()
            call_args = mock_repo.upsert.call_args
            assert call_args[1]["key"] == expected_key_hex
            assert call_args[1]["name"] == "#mychannel"
            assert call_args[1]["is_hashtag"] is True
            assert call_args[1]["on_radio"] is False  # Not pushed to radio on create

            # Verify response
            assert result.key == expected_key_hex
            assert result.name == "#mychannel"

    @pytest.mark.asyncio
    async def test_create_channel_with_explicit_key(self):
        """Creating channel with explicit key uses provided key."""
        from app.routers.channels import CreateChannelRequest, create_channel

        with patch("app.routers.channels.ChannelRepository") as mock_repo:
            mock_repo.upsert = AsyncMock()

            explicit_key = "0123456789abcdef0123456789abcdef"  # 32 hex chars = 16 bytes
            request = CreateChannelRequest(name="private", key=explicit_key)

            result = await create_channel(request)

            # Verify key stored in DB correctly (stored as uppercase hex)
            mock_repo.upsert.assert_called_once()
            call_args = mock_repo.upsert.call_args
            assert call_args[1]["key"] == explicit_key.upper()
            assert call_args[1]["name"] == "private"
            assert call_args[1]["on_radio"] is False

            # Verify response
            assert result.key == explicit_key.upper()


class TestPacketsEndpoint:
    """Test packet decryption endpoints."""

    def test_get_undecrypted_count(self):
        """Get undecrypted packet count returns correct value."""
        from fastapi.testclient import TestClient

        with patch("app.routers.packets.RawPacketRepository") as mock_repo:
            mock_repo.get_undecrypted_count = AsyncMock(return_value=42)

            from app.main import app

            client = TestClient(app)

            response = client.get("/api/packets/undecrypted/count")

            assert response.status_code == 200
            assert response.json()["count"] == 42


class TestReadStateEndpoints:
    """Test read state tracking endpoints."""

    @pytest.mark.asyncio
    async def test_mark_contact_read_updates_timestamp(self):
        """Marking contact as read updates last_read_at in database."""
        import time

        import aiosqlite

        from app.database import db
        from app.repository import ContactRepository

        # Use in-memory database for testing
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        # Create contacts table with last_read_at column
        await conn.execute("""
            CREATE TABLE contacts (
                public_key TEXT PRIMARY KEY,
                name TEXT,
                type INTEGER DEFAULT 0,
                flags INTEGER DEFAULT 0,
                last_path TEXT,
                last_path_len INTEGER DEFAULT -1,
                last_advert INTEGER,
                lat REAL,
                lon REAL,
                last_seen INTEGER,
                on_radio INTEGER DEFAULT 0,
                last_contacted INTEGER,
                last_read_at INTEGER
            )
        """)

        # Insert a test contact
        await conn.execute(
            "INSERT INTO contacts (public_key, name) VALUES (?, ?)",
            ("abc123def456789012345678901234567890123456789012345678901234", "TestContact"),
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            before_time = int(time.time())

            # Update last_read_at
            updated = await ContactRepository.update_last_read_at(
                "abc123def456789012345678901234567890123456789012345678901234"
            )

            assert updated is True

            # Verify the timestamp was set
            contact = await ContactRepository.get_by_key(
                "abc123def456789012345678901234567890123456789012345678901234"
            )
            assert contact is not None
            assert contact.last_read_at is not None
            assert contact.last_read_at >= before_time
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_mark_channel_read_updates_timestamp(self):
        """Marking channel as read updates last_read_at in database."""
        import time

        import aiosqlite

        from app.database import db
        from app.repository import ChannelRepository

        # Use in-memory database for testing
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        # Create channels table with last_read_at column
        await conn.execute("""
            CREATE TABLE channels (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_hashtag INTEGER DEFAULT 0,
                on_radio INTEGER DEFAULT 0,
                last_read_at INTEGER
            )
        """)

        # Insert a test channel
        await conn.execute(
            "INSERT INTO channels (key, name) VALUES (?, ?)",
            ("0123456789ABCDEF0123456789ABCDEF", "#testchannel"),
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            before_time = int(time.time())

            # Update last_read_at
            updated = await ChannelRepository.update_last_read_at(
                "0123456789ABCDEF0123456789ABCDEF"
            )

            assert updated is True

            # Verify the timestamp was set
            channel = await ChannelRepository.get_by_key("0123456789ABCDEF0123456789ABCDEF")
            assert channel is not None
            assert channel.last_read_at is not None
            assert channel.last_read_at >= before_time
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_mark_nonexistent_contact_returns_false(self):
        """Marking nonexistent contact returns False."""
        import aiosqlite

        from app.database import db
        from app.repository import ContactRepository

        # Use in-memory database for testing
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        await conn.execute("""
            CREATE TABLE contacts (
                public_key TEXT PRIMARY KEY,
                name TEXT,
                type INTEGER DEFAULT 0,
                flags INTEGER DEFAULT 0,
                last_path TEXT,
                last_path_len INTEGER DEFAULT -1,
                last_advert INTEGER,
                lat REAL,
                lon REAL,
                last_seen INTEGER,
                on_radio INTEGER DEFAULT 0,
                last_contacted INTEGER,
                last_read_at INTEGER
            )
        """)
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            updated = await ContactRepository.update_last_read_at("nonexistent")
            assert updated is False
        finally:
            db._connection = original_conn
            await conn.close()

    def test_mark_contact_read_endpoint_returns_404_for_missing(self):
        """Mark-read endpoint returns 404 for nonexistent contact."""
        from fastapi.testclient import TestClient

        with patch(
            "app.repository.ContactRepository.get_by_key_or_prefix", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None

            from app.main import app

            client = TestClient(app)

            response = client.post("/api/contacts/nonexistent/mark-read")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

    def test_mark_channel_read_endpoint_returns_404_for_missing(self):
        """Mark-read endpoint returns 404 for nonexistent channel."""
        from fastapi.testclient import TestClient

        with patch(
            "app.repository.ChannelRepository.get_by_key", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None

            from app.main import app

            client = TestClient(app)

            response = client.post("/api/channels/NONEXISTENT/mark-read")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_unreads_returns_counts_and_mentions(self):
        """GET /unreads returns unread counts, mentions, and last message times."""
        import aiosqlite

        from app.database import db
        from app.repository import MessageRepository

        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        # Create tables
        await conn.execute("""
            CREATE TABLE contacts (
                public_key TEXT PRIMARY KEY,
                name TEXT,
                type INTEGER DEFAULT 0,
                flags INTEGER DEFAULT 0,
                last_path TEXT,
                last_path_len INTEGER DEFAULT -1,
                last_advert INTEGER,
                lat REAL,
                lon REAL,
                last_seen INTEGER,
                on_radio INTEGER DEFAULT 0,
                last_contacted INTEGER,
                last_read_at INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE channels (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_hashtag INTEGER DEFAULT 0,
                on_radio INTEGER DEFAULT 0,
                last_read_at INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                type TEXT NOT NULL,
                conversation_key TEXT NOT NULL,
                text TEXT NOT NULL,
                sender_timestamp INTEGER,
                received_at INTEGER NOT NULL,
                paths TEXT,
                txt_type INTEGER DEFAULT 0,
                signature TEXT,
                outgoing INTEGER DEFAULT 0,
                acked INTEGER DEFAULT 0,
                UNIQUE(type, conversation_key, text, sender_timestamp)
            )
        """)

        # Insert channel and contact
        await conn.execute(
            "INSERT INTO channels (key, name, last_read_at) VALUES (?, ?, ?)",
            ("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", "Public", 1000),
        )
        await conn.execute(
            "INSERT INTO contacts (public_key, name, last_read_at) VALUES (?, ?, ?)",
            ("abcd" * 16, "Alice", 1000),
        )

        # Insert messages: 2 unread channel msgs (after last_read_at=1000),
        # 1 read (before), 1 outgoing (should not count)
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("CHAN", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", "Bob: hello", 1001, 0),
        )
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("CHAN", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", "Bob: @[TestUser] hey", 1002, 0),
        )
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("CHAN", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", "Bob: old msg", 999, 0),
        )
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("CHAN", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", "Me: outgoing", 1003, 1),
        )

        # Insert 1 unread DM
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("PRIV", "abcd" * 16, "hi there", 1005, 0),
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            result = await MessageRepository.get_unread_counts("TestUser")

            # Channel: 2 unread (1001 and 1002), one has mention
            assert result["counts"]["channel-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1"] == 2
            assert result["mentions"]["channel-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1"] is True

            # Contact: 1 unread
            assert result["counts"][f"contact-{'abcd' * 16}"] == 1

            # Last message times should include all conversations
            assert "channel-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1" in result["last_message_times"]
            assert result["last_message_times"]["channel-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1"] == 1003
            assert f"contact-{'abcd' * 16}" in result["last_message_times"]
            assert result["last_message_times"][f"contact-{'abcd' * 16}"] == 1005
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_get_unreads_no_name_skips_mentions(self):
        """GET /unreads without name param returns counts but no mention flags."""
        import aiosqlite

        from app.database import db
        from app.repository import MessageRepository

        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        await conn.execute("""
            CREATE TABLE channels (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_hashtag INTEGER DEFAULT 0,
                on_radio INTEGER DEFAULT 0,
                last_read_at INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE contacts (
                public_key TEXT PRIMARY KEY,
                name TEXT,
                type INTEGER DEFAULT 0,
                flags INTEGER DEFAULT 0,
                last_path TEXT,
                last_path_len INTEGER DEFAULT -1,
                last_advert INTEGER,
                lat REAL,
                lon REAL,
                last_seen INTEGER,
                on_radio INTEGER DEFAULT 0,
                last_contacted INTEGER,
                last_read_at INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                type TEXT NOT NULL,
                conversation_key TEXT NOT NULL,
                text TEXT NOT NULL,
                sender_timestamp INTEGER,
                received_at INTEGER NOT NULL,
                paths TEXT,
                txt_type INTEGER DEFAULT 0,
                signature TEXT,
                outgoing INTEGER DEFAULT 0,
                acked INTEGER DEFAULT 0,
                UNIQUE(type, conversation_key, text, sender_timestamp)
            )
        """)

        await conn.execute(
            "INSERT INTO channels (key, name, last_read_at) VALUES (?, ?, ?)",
            ("CHAN1KEY1CHAN1KEY1CHAN1KEY1CHAN1KEY1", "Public", 0),
        )
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("CHAN", "CHAN1KEY1CHAN1KEY1CHAN1KEY1CHAN1KEY1", "Bob: @[Alice] hey", 1001, 0),
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            result = await MessageRepository.get_unread_counts(None)

            assert result["counts"]["channel-CHAN1KEY1CHAN1KEY1CHAN1KEY1CHAN1KEY1"] == 1
            # No mentions since name was None
            assert len(result["mentions"]) == 0
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_unreads_reset_after_mark_read(self):
        """Marking a conversation as read zeroes its unread count; new messages after count again."""
        import aiosqlite

        from app.database import db
        from app.repository import MessageRepository

        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        await conn.execute("""
            CREATE TABLE channels (
                key TEXT PRIMARY KEY, name TEXT NOT NULL,
                is_hashtag INTEGER DEFAULT 0, on_radio INTEGER DEFAULT 0, last_read_at INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE contacts (
                public_key TEXT PRIMARY KEY, name TEXT,
                type INTEGER DEFAULT 0, flags INTEGER DEFAULT 0,
                last_path TEXT, last_path_len INTEGER DEFAULT -1,
                last_advert INTEGER, lat REAL, lon REAL, last_seen INTEGER,
                on_radio INTEGER DEFAULT 0, last_contacted INTEGER, last_read_at INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY, type TEXT NOT NULL,
                conversation_key TEXT NOT NULL, text TEXT NOT NULL,
                sender_timestamp INTEGER, received_at INTEGER NOT NULL,
                paths TEXT, txt_type INTEGER DEFAULT 0, signature TEXT,
                outgoing INTEGER DEFAULT 0, acked INTEGER DEFAULT 0,
                UNIQUE(type, conversation_key, text, sender_timestamp)
            )
        """)

        chan_key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1"
        await conn.execute(
            "INSERT INTO channels (key, name, last_read_at) VALUES (?, ?, ?)",
            (chan_key, "Public", 1000),
        )
        # 2 unread messages (received_at > last_read_at=1000)
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("CHAN", chan_key, "msg1", 1001, 0),
        )
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("CHAN", chan_key, "msg2", 1002, 0),
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            # Verify 2 unread
            result = await MessageRepository.get_unread_counts(None)
            assert result["counts"][f"channel-{chan_key}"] == 2

            # Simulate mark-read by updating last_read_at to after all messages
            await conn.execute(
                "UPDATE channels SET last_read_at = ? WHERE key = ?", (1002, chan_key)
            )
            await conn.commit()

            # Verify 0 unread
            result = await MessageRepository.get_unread_counts(None)
            assert result["counts"].get(f"channel-{chan_key}", 0) == 0

            # New message arrives after the read point
            await conn.execute(
                "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
                ("CHAN", chan_key, "msg3", 1003, 0),
            )
            await conn.commit()

            # Verify exactly 1 unread
            result = await MessageRepository.get_unread_counts(None)
            assert result["counts"][f"channel-{chan_key}"] == 1
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_unreads_exclude_outgoing_messages(self):
        """Outgoing messages should never count as unread, even when received_at > last_read_at.

        This is critical: without the outgoing filter, every message we send would
        show as an unread badge in the sidebar.
        """
        import aiosqlite

        from app.database import db
        from app.repository import MessageRepository

        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        await conn.execute("""
            CREATE TABLE channels (
                key TEXT PRIMARY KEY, name TEXT NOT NULL,
                is_hashtag INTEGER DEFAULT 0, on_radio INTEGER DEFAULT 0, last_read_at INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE contacts (
                public_key TEXT PRIMARY KEY, name TEXT,
                type INTEGER DEFAULT 0, flags INTEGER DEFAULT 0,
                last_path TEXT, last_path_len INTEGER DEFAULT -1,
                last_advert INTEGER, lat REAL, lon REAL, last_seen INTEGER,
                on_radio INTEGER DEFAULT 0, last_contacted INTEGER, last_read_at INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY, type TEXT NOT NULL,
                conversation_key TEXT NOT NULL, text TEXT NOT NULL,
                sender_timestamp INTEGER, received_at INTEGER NOT NULL,
                paths TEXT, txt_type INTEGER DEFAULT 0, signature TEXT,
                outgoing INTEGER DEFAULT 0, acked INTEGER DEFAULT 0,
                UNIQUE(type, conversation_key, text, sender_timestamp)
            )
        """)

        contact_key = "abcd" * 16
        await conn.execute(
            "INSERT INTO contacts (public_key, name, last_read_at) VALUES (?, ?, ?)",
            (contact_key, "Bob", 1000),
        )
        # 1 incoming (should count) + 2 outgoing (should NOT count)
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("PRIV", contact_key, "incoming msg", 1001, 0),
        )
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("PRIV", contact_key, "my reply", 1002, 1),
        )
        await conn.execute(
            "INSERT INTO messages (type, conversation_key, text, received_at, outgoing) VALUES (?, ?, ?, ?, ?)",
            ("PRIV", contact_key, "another reply", 1003, 1),
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            result = await MessageRepository.get_unread_counts(None)
            # Only the 1 incoming message should count as unread
            assert result["counts"][f"contact-{contact_key}"] == 1
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_mark_all_read_updates_all_conversations(self):
        """Bulk mark-all-read updates all contacts and channels."""
        import time

        import aiosqlite

        from app.database import db

        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        # Create tables
        await conn.execute("""
            CREATE TABLE contacts (
                public_key TEXT PRIMARY KEY,
                name TEXT,
                last_read_at INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE channels (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                last_read_at INTEGER
            )
        """)

        # Insert test data with NULL last_read_at
        await conn.execute(
            "INSERT INTO contacts (public_key, name) VALUES (?, ?)", ("contact1", "Alice")
        )
        await conn.execute(
            "INSERT INTO contacts (public_key, name) VALUES (?, ?)", ("contact2", "Bob")
        )
        await conn.execute("INSERT INTO channels (key, name) VALUES (?, ?)", ("CHAN1", "#test1"))
        await conn.execute("INSERT INTO channels (key, name) VALUES (?, ?)", ("CHAN2", "#test2"))
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            before_time = int(time.time())

            # Call the endpoint
            from app.routers.read_state import mark_all_read

            result = await mark_all_read()

            assert result["status"] == "ok"
            assert result["timestamp"] >= before_time

            # Verify all contacts updated
            cursor = await conn.execute("SELECT last_read_at FROM contacts")
            rows = await cursor.fetchall()
            for row in rows:
                assert row["last_read_at"] >= before_time

            # Verify all channels updated
            cursor = await conn.execute("SELECT last_read_at FROM channels")
            rows = await cursor.fetchall()
            for row in rows:
                assert row["last_read_at"] >= before_time
        finally:
            db._connection = original_conn
            await conn.close()


class TestRawPacketRepository:
    """Test raw packet storage with deduplication."""

    @pytest.mark.asyncio
    async def test_create_returns_id_for_new_packet(self):
        """First insert of packet data returns a valid ID."""
        import aiosqlite

        from app.database import db
        from app.repository import RawPacketRepository

        # Use in-memory database for testing
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        # Create the raw_packets table with payload_hash for deduplication
        await conn.execute("""
            CREATE TABLE raw_packets (
                id INTEGER PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                data BLOB NOT NULL,
                message_id INTEGER,
                payload_hash TEXT
            )
        """)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_packets_payload_hash ON raw_packets(payload_hash)"
        )
        await conn.commit()

        # Patch the db._connection to use our test connection
        original_conn = db._connection
        db._connection = conn

        try:
            packet_data = b"\x01\x02\x03\x04\x05"
            packet_id, is_new = await RawPacketRepository.create(packet_data, 1234567890)

            assert packet_id is not None
            assert packet_id > 0
            assert is_new is True
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_different_packets_both_stored(self):
        """Different packet data both get stored with unique IDs."""
        import aiosqlite

        from app.database import db
        from app.repository import RawPacketRepository

        # Use in-memory database for testing
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        # Create the raw_packets table with payload_hash for deduplication
        await conn.execute("""
            CREATE TABLE raw_packets (
                id INTEGER PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                data BLOB NOT NULL,
                message_id INTEGER,
                payload_hash TEXT
            )
        """)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_packets_payload_hash ON raw_packets(payload_hash)"
        )
        await conn.commit()

        # Patch the db._connection to use our test connection
        original_conn = db._connection
        db._connection = conn

        try:
            packet1 = b"\x01\x02\x03"
            packet2 = b"\x04\x05\x06"

            id1, is_new1 = await RawPacketRepository.create(packet1, 1234567890)
            id2, is_new2 = await RawPacketRepository.create(packet2, 1234567891)

            assert id1 is not None
            assert id2 is not None
            assert id1 != id2
            assert is_new1 is True
            assert is_new2 is True
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_duplicate_packet_returns_existing_id(self):
        """Inserting same payload twice returns existing ID and is_new=False."""
        import aiosqlite

        from app.database import db
        from app.repository import RawPacketRepository

        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        # Create the raw_packets table with payload_hash for deduplication
        await conn.execute("""
            CREATE TABLE raw_packets (
                id INTEGER PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                data BLOB NOT NULL,
                message_id INTEGER,
                payload_hash TEXT
            )
        """)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_packets_payload_hash ON raw_packets(payload_hash)"
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            # Same packet data inserted twice
            packet_data = b"\x01\x02\x03\x04\x05"
            id1, is_new1 = await RawPacketRepository.create(packet_data, 1234567890)
            id2, is_new2 = await RawPacketRepository.create(packet_data, 1234567891)

            # Both should return the same ID
            assert id1 == id2
            # First is new, second is not
            assert is_new1 is True
            assert is_new2 is False
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_malformed_packet_uses_full_data_hash(self):
        """Malformed packets (can't extract payload) hash full data for dedup."""
        import aiosqlite

        from app.database import db
        from app.repository import RawPacketRepository

        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        await conn.execute("""
            CREATE TABLE raw_packets (
                id INTEGER PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                data BLOB NOT NULL,
                message_id INTEGER,
                payload_hash TEXT
            )
        """)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_packets_payload_hash ON raw_packets(payload_hash)"
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            # Single byte is too short to be valid packet (extract_payload returns None)
            malformed = b"\x01"
            id1, is_new1 = await RawPacketRepository.create(malformed, 1234567890)
            id2, is_new2 = await RawPacketRepository.create(malformed, 1234567891)

            # Should still deduplicate using full data hash
            assert id1 == id2
            assert is_new1 is True
            assert is_new2 is False

            # Different malformed packet should get different ID
            different_malformed = b"\x02"
            id3, is_new3 = await RawPacketRepository.create(different_malformed, 1234567892)
            assert id3 != id1
            assert is_new3 is True
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_prune_old_undecrypted_deletes_old_packets(self):
        """Prune deletes undecrypted packets older than specified days."""
        import time

        import aiosqlite

        from app.database import db
        from app.repository import RawPacketRepository

        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        await conn.execute("""
            CREATE TABLE raw_packets (
                id INTEGER PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                data BLOB NOT NULL UNIQUE,
                message_id INTEGER
            )
        """)

        now = int(time.time())
        old_timestamp = now - (15 * 86400)  # 15 days ago
        recent_timestamp = now - (5 * 86400)  # 5 days ago

        # Insert old undecrypted packet (message_id NULL = undecrypted)
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (old_timestamp, b"\x01\x02\x03"),
        )
        # Insert recent undecrypted packet (message_id NULL = undecrypted)
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (recent_timestamp, b"\x04\x05\x06"),
        )
        # Insert old but decrypted packet (should NOT be deleted)
        # message_id NOT NULL = decrypted
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data, message_id) VALUES (?, ?, ?)",
            (old_timestamp, b"\x07\x08\x09", 1),
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            # Prune packets older than 10 days
            deleted = await RawPacketRepository.prune_old_undecrypted(10)

            assert deleted == 1  # Only the old undecrypted packet

            # Verify remaining packets
            cursor = await conn.execute("SELECT COUNT(*) as count FROM raw_packets")
            row = await cursor.fetchone()
            assert row["count"] == 2  # Recent undecrypted + old decrypted
        finally:
            db._connection = original_conn
            await conn.close()

    @pytest.mark.asyncio
    async def test_prune_old_undecrypted_returns_zero_when_nothing_to_delete(self):
        """Prune returns 0 when no packets match criteria."""
        import time

        import aiosqlite

        from app.database import db
        from app.repository import RawPacketRepository

        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        await conn.execute("""
            CREATE TABLE raw_packets (
                id INTEGER PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                data BLOB NOT NULL UNIQUE,
                message_id INTEGER
            )
        """)

        now = int(time.time())
        recent_timestamp = now - (5 * 86400)  # 5 days ago

        # Insert only recent packet (message_id NULL = undecrypted)
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (recent_timestamp, b"\x01\x02\x03"),
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            # Prune packets older than 10 days (none should match)
            deleted = await RawPacketRepository.prune_old_undecrypted(10)
            assert deleted == 0
        finally:
            db._connection = original_conn
            await conn.close()


class TestMaintenanceEndpoint:
    """Test database maintenance endpoint."""

    @pytest.mark.asyncio
    async def test_maintenance_prunes_and_vacuums(self):
        """Maintenance endpoint prunes old packets and runs vacuum."""
        import time

        import aiosqlite

        from app.database import db
        from app.routers.packets import MaintenanceRequest, run_maintenance

        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row

        await conn.execute("""
            CREATE TABLE raw_packets (
                id INTEGER PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                data BLOB NOT NULL UNIQUE,
                message_id INTEGER
            )
        """)

        now = int(time.time())
        old_timestamp = now - (20 * 86400)  # 20 days ago

        # Insert old undecrypted packets (message_id NULL = undecrypted)
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (old_timestamp, b"\x01\x02\x03"),
        )
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (old_timestamp, b"\x04\x05\x06"),
        )
        await conn.commit()

        original_conn = db._connection
        db._connection = conn

        try:
            request = MaintenanceRequest(prune_undecrypted_days=14)
            result = await run_maintenance(request)

            assert result.packets_deleted == 2
            assert result.vacuumed is True
        finally:
            db._connection = original_conn
            await conn.close()


class TestHealthEndpointDatabaseSize:
    """Test database size reporting in health endpoint."""

    def test_health_includes_database_size(self):
        """Health endpoint includes database_size_mb field."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        with (
            patch("app.routers.health.radio_manager") as mock_rm,
            patch("app.routers.health.os.path.getsize") as mock_getsize,
        ):
            mock_rm.is_connected = True
            mock_rm.port = "/dev/ttyUSB0"
            mock_getsize.return_value = 10 * 1024 * 1024  # 10 MB

            from app.main import app

            client = TestClient(app)

            response = client.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert "database_size_mb" in data
            assert data["database_size_mb"] == 10.0


class TestHealthEndpointOldestUndecrypted:
    """Test oldest undecrypted packet timestamp in health endpoint."""

    def test_health_includes_oldest_undecrypted_timestamp(self):
        """Health endpoint includes oldest_undecrypted_timestamp when packets exist."""
        from unittest.mock import AsyncMock, patch

        from fastapi.testclient import TestClient

        with (
            patch("app.routers.health.radio_manager") as mock_rm,
            patch("app.routers.health.os.path.getsize") as mock_getsize,
            patch("app.routers.health.RawPacketRepository") as mock_repo,
        ):
            mock_rm.is_connected = True
            mock_rm.port = "/dev/ttyUSB0"
            mock_getsize.return_value = 5 * 1024 * 1024  # 5 MB
            mock_repo.get_oldest_undecrypted = AsyncMock(return_value=1700000000)

            from app.main import app

            client = TestClient(app)

            response = client.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert "oldest_undecrypted_timestamp" in data
            assert data["oldest_undecrypted_timestamp"] == 1700000000

    def test_health_oldest_undecrypted_null_when_none(self):
        """Health endpoint returns null for oldest_undecrypted_timestamp when no packets."""
        from unittest.mock import AsyncMock, patch

        from fastapi.testclient import TestClient

        with (
            patch("app.routers.health.radio_manager") as mock_rm,
            patch("app.routers.health.os.path.getsize") as mock_getsize,
            patch("app.routers.health.RawPacketRepository") as mock_repo,
        ):
            mock_rm.is_connected = True
            mock_rm.port = "/dev/ttyUSB0"
            mock_getsize.return_value = 1 * 1024 * 1024  # 1 MB
            mock_repo.get_oldest_undecrypted = AsyncMock(return_value=None)

            from app.main import app

            client = TestClient(app)

            response = client.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert "oldest_undecrypted_timestamp" in data
            assert data["oldest_undecrypted_timestamp"] is None

    def test_health_handles_db_not_connected(self):
        """Health endpoint gracefully handles database not connected."""
        from unittest.mock import AsyncMock, patch

        from fastapi.testclient import TestClient

        with (
            patch("app.routers.health.radio_manager") as mock_rm,
            patch("app.routers.health.os.path.getsize") as mock_getsize,
            patch("app.routers.health.RawPacketRepository") as mock_repo,
        ):
            mock_rm.is_connected = False
            mock_rm.port = None
            mock_getsize.side_effect = OSError("File not found")
            mock_repo.get_oldest_undecrypted = AsyncMock(side_effect=RuntimeError("No DB"))

            from app.main import app

            client = TestClient(app)

            response = client.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert data["oldest_undecrypted_timestamp"] is None
            assert data["database_size_mb"] == 0.0
