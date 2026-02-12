"""End-to-end tests for the packet processing pipeline.

These tests verify the full flow from raw packet arrival through to
WebSocket broadcast, using real packet data and a real database.

The fixtures in fixtures/websocket_events.json define the contract
between backend and frontend - both sides test against the same data.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database import Database
from app.decoder import DecryptedDirectMessage, PacketInfo, PayloadType
from app.repository import (
    ChannelRepository,
    ContactRepository,
    MessageRepository,
    RawPacketRepository,
)

# Load shared fixtures
FIXTURES_PATH = Path(__file__).parent / "fixtures" / "websocket_events.json"
with open(FIXTURES_PATH) as f:
    FIXTURES = json.load(f)


@pytest.fixture
async def test_db():
    """Create an in-memory test database.

    We need to patch the db module-level variable before any repository
    methods are called, so they use our test database.
    """
    import app.repository as repo_module

    db = Database(":memory:")
    await db.connect()

    # Store original and patch the module attribute directly
    original_db = repo_module.db
    repo_module.db = db

    try:
        yield db
    finally:
        repo_module.db = original_db
        await db.disconnect()


@pytest.fixture
def captured_broadcasts():
    """Capture WebSocket broadcasts for verification."""
    broadcasts = []

    def mock_broadcast(event_type: str, data: dict):
        """Synchronous mock that captures broadcasts."""
        broadcasts.append({"type": event_type, "data": data})

    return broadcasts, mock_broadcast


class TestChannelMessagePipeline:
    """Test channel message flow: packet → decrypt → store → broadcast."""

    @pytest.mark.asyncio
    async def test_channel_message_creates_message_and_broadcasts(
        self, test_db, captured_broadcasts
    ):
        """A decryptable channel packet creates a message and broadcasts it."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["channel_message"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])

        # Create the channel in DB first using upsert
        await ChannelRepository.upsert(
            key=fixture["channel_key_hex"].upper(), name=fixture["channel_name"], is_hashtag=True
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            result = await process_raw_packet(packet_bytes, timestamp=1700000000)

        # Verify packet was processed successfully
        assert result is not None
        assert result.get("decrypted") is True

        # Verify message was stored in database
        messages = await MessageRepository.get_all(
            msg_type="CHAN", conversation_key=fixture["channel_key_hex"].upper(), limit=10
        )
        assert len(messages) == 1
        msg = messages[0]
        assert "Flightless🥝:" in msg.text
        assert "hashtag room is essentially public" in msg.text

        # Verify WebSocket broadcast format matches fixture
        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 1

        broadcast = message_broadcasts[0]
        expected = fixture["expected_ws_event"]["data"]
        assert broadcast["data"]["type"] == expected["type"]
        assert broadcast["data"]["conversation_key"] == expected["conversation_key"]
        assert broadcast["data"]["outgoing"] == expected["outgoing"]
        assert (
            expected["text"][:30] in broadcast["data"]["text"]
        )  # Check text contains expected content

    @pytest.mark.asyncio
    async def test_duplicate_packet_not_broadcast_twice(self, test_db, captured_broadcasts):
        """Same packet arriving twice only creates one message and one broadcast."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["duplicate_channel_message"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])
        channel_key_hex = "7ABA109EDCF304A84433CB71D0F3AB73"

        # Create the channel in DB first
        await ChannelRepository.upsert(
            key=channel_key_hex, name=fixture["channel_name"], is_hashtag=True
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            # Process same packet twice
            result1 = await process_raw_packet(packet_bytes, timestamp=1700000000)
            result2 = await process_raw_packet(packet_bytes, timestamp=1700000001)

        # First should succeed, second should be detected as duplicate
        assert result1 is not None
        assert result1.get("decrypted") is True

        # Second packet still processes but message is deduplicated
        assert result2 is not None

        # Only ONE message should exist in database
        messages = await MessageRepository.get_all(
            msg_type="CHAN", conversation_key=channel_key_hex, limit=10
        )
        assert len(messages) == 1

        # Only ONE message broadcast should have been sent
        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 1

    @pytest.mark.asyncio
    async def test_unknown_channel_stores_raw_packet_only(self, test_db, captured_broadcasts):
        """Packet for unknown channel is stored but not decrypted."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["channel_message"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])

        # DON'T create the channel - simulate unknown channel

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            result = await process_raw_packet(packet_bytes, timestamp=1700000000)

        # Packet should be stored but not decrypted
        assert result is not None

        # Raw packet should be stored
        raw_packets = await RawPacketRepository.get_all_undecrypted()
        assert len(raw_packets) >= 1

        # No message broadcast (only raw_packet broadcast)
        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 0


class TestAdvertisementPipeline:
    """Test advertisement flow: packet → parse → upsert contact → broadcast."""

    @pytest.mark.asyncio
    async def test_advertisement_creates_contact_with_gps(self, test_db, captured_broadcasts):
        """Advertisement packet creates/updates contact with GPS coordinates."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["advertisement_with_gps"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            # Process the advertisement packet through the normal pipeline
            await process_raw_packet(packet_bytes, timestamp=1700000000)

        # Verify contact was created in database
        expected = fixture["expected_ws_event"]["data"]
        contact = await ContactRepository.get_by_key_prefix(expected["public_key"][:12])

        assert contact is not None
        assert contact.name == expected["name"]
        assert contact.type == expected["type"]
        assert contact.lat is not None
        assert contact.lon is not None
        assert abs(contact.lat - expected["lat"]) < 0.001
        assert abs(contact.lon - expected["lon"]) < 0.001
        # This advertisement has path_len=6 (6 hops through repeaters)
        assert contact.last_path_len == 6
        assert contact.last_path is not None
        assert len(contact.last_path) == 12  # 6 bytes = 12 hex chars

        # Verify WebSocket broadcast
        contact_broadcasts = [b for b in broadcasts if b["type"] == "contact"]
        assert len(contact_broadcasts) == 1

        broadcast = contact_broadcasts[0]
        assert broadcast["data"]["public_key"] == expected["public_key"]
        assert broadcast["data"]["name"] == expected["name"]
        assert broadcast["data"]["type"] == expected["type"]
        assert broadcast["data"]["last_path_len"] == 6

    @pytest.mark.asyncio
    async def test_advertisement_updates_existing_contact(self, test_db, captured_broadcasts):
        """Advertisement for existing contact updates their info."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["advertisement_chat_node"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])
        expected = fixture["expected_ws_event"]["data"]

        # Create existing contact with different/missing data
        await ContactRepository.upsert(
            {
                "public_key": expected["public_key"],
                "name": "OldName",
                "type": 0,
                "lat": None,
                "lon": None,
            }
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            await process_raw_packet(packet_bytes, timestamp=1700000000)

        # Verify contact was updated
        contact = await ContactRepository.get_by_key_prefix(expected["public_key"][:12])

        assert contact.name == expected["name"]  # Name updated
        assert contact.type == expected["type"]  # Type updated
        assert contact.lat is not None  # GPS added
        assert contact.lon is not None
        # This advertisement has path_len=0 (direct neighbor)
        assert contact.last_path_len == 0
        # Empty path stored as None or ""
        assert contact.last_path in (None, "")

    @pytest.mark.asyncio
    async def test_advertisement_triggers_historical_decrypt_for_new_contact(
        self, test_db, captured_broadcasts
    ):
        """New contact via advertisement starts historical DM decryption when setting enabled."""
        from app.packet_processor import process_raw_packet
        from app.repository import AppSettingsRepository

        # Enable auto-decrypt setting
        await AppSettingsRepository.update(auto_decrypt_dm_on_advert=True)

        fixture = FIXTURES["advertisement_with_gps"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])
        expected = fixture["expected_ws_event"]["data"]

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch(
                "app.packet_processor.start_historical_dm_decryption", new=AsyncMock()
            ) as mock_start:
                await process_raw_packet(packet_bytes, timestamp=1700000000)

        mock_start.assert_awaited_once_with(None, expected["public_key"], expected["name"])

    @pytest.mark.asyncio
    async def test_advertisement_skips_historical_decrypt_for_existing_contact(
        self, test_db, captured_broadcasts
    ):
        """Existing contact via advertisement does not start historical DM decryption."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["advertisement_chat_node"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])
        expected = fixture["expected_ws_event"]["data"]

        await ContactRepository.upsert(
            {
                "public_key": expected["public_key"],
                "name": "Existing",
                "type": 0,
                "lat": None,
                "lon": None,
            }
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch(
                "app.packet_processor.start_historical_dm_decryption", new=AsyncMock()
            ) as mock_start:
                await process_raw_packet(packet_bytes, timestamp=1700000000)

        assert mock_start.await_count == 0

    @pytest.mark.asyncio
    async def test_advertisement_keeps_shorter_path_within_window(
        self, test_db, captured_broadcasts
    ):
        """When receiving echoed advertisements, keep the shortest path within 60s window."""
        from app.packet_processor import _process_advertisement

        # Create a contact with a longer path (path_len=3)
        test_pubkey = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        await ContactRepository.upsert(
            {
                "public_key": test_pubkey,
                "name": "TestNode",
                "type": 1,
                "last_seen": 1000,
                "last_path_len": 3,
                "last_path": "aabbcc",  # 3 bytes = 3 hops
            }
        )

        # Simulate receiving a shorter path (path_len=1) within 60s
        # We'll call _process_advertisement directly with mock packet_info
        from unittest.mock import MagicMock

        from app.decoder import ParsedAdvertisement

        broadcasts, mock_broadcast = captured_broadcasts

        # Mock packet_info with shorter path
        short_packet_info = MagicMock()
        short_packet_info.path_length = 1
        short_packet_info.path = bytes.fromhex("aa")
        short_packet_info.payload = b""  # Will be parsed by parse_advertisement

        # Mock parse_advertisement to return our test contact
        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.parse_advertisement") as mock_parse:
                mock_parse.return_value = ParsedAdvertisement(
                    public_key=test_pubkey,
                    name="TestNode",
                    timestamp=1050,
                    lat=None,
                    lon=None,
                    device_role=1,
                )
                # Process at timestamp 1050 (within 60s of last_seen=1000)
                await _process_advertisement(b"", timestamp=1050, packet_info=short_packet_info)

        # Verify the shorter path was stored
        contact = await ContactRepository.get_by_key(test_pubkey)
        assert contact.last_path_len == 1  # Updated to shorter path

        # Now simulate receiving a longer path (path_len=5) - should keep the shorter one
        long_packet_info = MagicMock()
        long_packet_info.path_length = 5
        long_packet_info.path = bytes.fromhex("aabbccddee")

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.parse_advertisement") as mock_parse:
                mock_parse.return_value = ParsedAdvertisement(
                    public_key=test_pubkey,
                    name="TestNode",
                    timestamp=1055,
                    lat=None,
                    lon=None,
                    device_role=1,
                )
                # Process at timestamp 1055 (within 60s of last update)
                await _process_advertisement(b"", timestamp=1055, packet_info=long_packet_info)

        # Verify the shorter path was kept
        contact = await ContactRepository.get_by_key(test_pubkey)
        assert contact.last_path_len == 1  # Still the shorter path

    @pytest.mark.asyncio
    async def test_advertisement_replaces_stale_path_outside_window(
        self, test_db, captured_broadcasts
    ):
        """When existing path is stale (>60s), a new longer path should replace it.

        In a mesh network, a stale short path may no longer be valid (node moved, repeater
        went offline). Accepting the new longer path ensures we have a working route.
        """
        from app.packet_processor import _process_advertisement

        test_pubkey = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        await ContactRepository.upsert(
            {
                "public_key": test_pubkey,
                "name": "TestNode",
                "type": 1,
                "last_seen": 1000,
                "last_path_len": 1,  # Short path
                "last_path": "aa",
            }
        )

        from unittest.mock import MagicMock

        from app.decoder import ParsedAdvertisement

        broadcasts, mock_broadcast = captured_broadcasts

        # New longer path arriving AFTER 60s window (timestamp 1000 + 61 = 1061)
        long_packet_info = MagicMock()
        long_packet_info.path_length = 4
        long_packet_info.path = bytes.fromhex("aabbccdd")
        long_packet_info.payload = b""

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.parse_advertisement") as mock_parse:
                mock_parse.return_value = ParsedAdvertisement(
                    public_key=test_pubkey,
                    name="TestNode",
                    timestamp=1061,
                    lat=None,
                    lon=None,
                    device_role=1,
                )
                await _process_advertisement(b"", timestamp=1061, packet_info=long_packet_info)

        # Verify the longer path replaced the stale shorter one
        contact = await ContactRepository.get_by_key(test_pubkey)
        assert contact.last_path_len == 4
        assert contact.last_path == "aabbccdd"


class TestAckPipeline:
    """Test ACK flow: outgoing message → ACK received → broadcast update."""

    @pytest.mark.asyncio
    async def test_ack_updates_message_and_broadcasts(self, test_db, captured_broadcasts):
        """ACK receipt updates message ack count and broadcasts."""
        from app.event_handlers import on_ack, track_pending_ack
        from app.repository import MessageRepository

        # Create a message that's waiting for ACK (acked defaults to 0)
        msg_id = await MessageRepository.create(
            msg_type="PRIV",
            text="Hello",
            conversation_key="abc123def456789012345678901234567890123456789012345678901234",
            sender_timestamp=1700000000,
            received_at=1700000000,
            outgoing=True,
        )

        # Track pending ACK
        ack_code = "test_ack_123"
        track_pending_ack(ack_code, message_id=msg_id, timeout_ms=30000)

        broadcasts, mock_broadcast = captured_broadcasts

        # Create a mock Event with the ACK code
        # on_ack expects event.payload.get("code")
        mock_event = MagicMock()
        mock_event.payload = {"code": ack_code}

        # Patch broadcast_event in the event_handlers module
        with patch("app.event_handlers.broadcast_event", mock_broadcast):
            await on_ack(mock_event)

        # Verify message was updated in database
        messages = await MessageRepository.get_all(
            msg_type="PRIV",
            conversation_key="abc123def456789012345678901234567890123456789012345678901234",
            limit=10,
        )
        assert len(messages) == 1
        assert messages[0].acked == 1

        # Verify broadcast format matches fixture
        ack_broadcasts = [b for b in broadcasts if b["type"] == "message_acked"]
        assert len(ack_broadcasts) == 1

        broadcast = ack_broadcasts[0]
        assert "message_id" in broadcast["data"]
        assert "ack_count" in broadcast["data"]
        assert broadcast["data"]["ack_count"] == 1


class TestCreateMessageFromDecrypted:
    """Test the shared message creation function used by both real-time and historical decryption."""

    @pytest.mark.asyncio
    async def test_schedules_bot_in_background(self, test_db, captured_broadcasts):
        """Bot execution is scheduled and does not block channel message persistence."""
        from app.packet_processor import create_message_from_decrypted

        packet_id, _ = await RawPacketRepository.create(b"test_packet_bot_channel", 1700000000)
        broadcasts, mock_broadcast = captured_broadcasts

        def _capture_task(coro):
            coro.close()
            return MagicMock()

        with (
            patch("app.packet_processor.broadcast_event", mock_broadcast),
            patch(
                "app.packet_processor.asyncio.create_task", side_effect=_capture_task
            ) as mock_task,
            patch("app.bot.run_bot_for_message", new_callable=AsyncMock) as mock_bot,
        ):
            msg_id = await create_message_from_decrypted(
                packet_id=packet_id,
                channel_key="ABC123DEF456",
                sender="BotTrigger",
                message_text="Hello from channel",
                timestamp=1700000000,
                received_at=1700000001,
                trigger_bot=True,
            )

        assert msg_id is not None
        mock_task.assert_called_once()
        mock_bot.assert_called_once()
        assert mock_bot.await_count == 0

    @pytest.mark.asyncio
    async def test_creates_message_and_broadcasts(self, test_db, captured_broadcasts):
        """create_message_from_decrypted creates message and broadcasts correctly."""
        from app.packet_processor import create_message_from_decrypted

        # Create a raw packet first (required for the function)
        packet_id, _ = await RawPacketRepository.create(b"test_packet_data", 1700000000)

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            msg_id = await create_message_from_decrypted(
                packet_id=packet_id,
                channel_key="ABC123DEF456",
                sender="TestSender",
                message_text="Hello world",
                timestamp=1700000000,
                received_at=1700000001,
            )

        # Should return a message ID
        assert msg_id is not None
        assert isinstance(msg_id, int)

        # Verify message was stored in database
        messages = await MessageRepository.get_all(
            msg_type="CHAN", conversation_key="ABC123DEF456", limit=10
        )
        assert len(messages) == 1
        assert messages[0].text == "TestSender: Hello world"
        assert messages[0].sender_timestamp == 1700000000

        # Verify broadcast was sent with correct structure
        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 1

        broadcast = message_broadcasts[0]["data"]
        assert broadcast["id"] == msg_id
        assert broadcast["type"] == "CHAN"
        assert broadcast["conversation_key"] == "ABC123DEF456"
        assert broadcast["text"] == "TestSender: Hello world"
        assert broadcast["sender_timestamp"] == 1700000000
        assert broadcast["received_at"] == 1700000001
        assert broadcast["paths"] is None  # Historical decryption has no path info
        assert broadcast["outgoing"] is False
        assert broadcast["acked"] == 0

    @pytest.mark.asyncio
    async def test_handles_message_without_sender(self, test_db, captured_broadcasts):
        """create_message_from_decrypted handles messages without sender prefix."""
        from app.packet_processor import create_message_from_decrypted

        packet_id, _ = await RawPacketRepository.create(b"test_packet_data_2", 1700000000)

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            msg_id = await create_message_from_decrypted(
                packet_id=packet_id,
                channel_key="ABC123DEF456",
                sender=None,  # No sender
                message_text="System message",
                timestamp=1700000000,
                received_at=1700000001,
            )

        assert msg_id is not None

        # Verify text is stored without sender prefix
        messages = await MessageRepository.get_all(
            msg_type="CHAN", conversation_key="ABC123DEF456", limit=10
        )
        assert len(messages) == 1
        assert messages[0].text == "System message"  # No "None: " prefix

    @pytest.mark.asyncio
    async def test_returns_none_for_duplicate(self, test_db, captured_broadcasts):
        """create_message_from_decrypted returns None for duplicate message."""
        from app.packet_processor import create_message_from_decrypted

        packet_id_1, _ = await RawPacketRepository.create(b"packet_1", 1700000000)
        packet_id_2, _ = await RawPacketRepository.create(b"packet_2", 1700000001)

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            # First call creates the message
            msg_id_1 = await create_message_from_decrypted(
                packet_id=packet_id_1,
                channel_key="ABC123DEF456",
                sender="Sender",
                message_text="Duplicate test",
                timestamp=1700000000,
                received_at=1700000001,
            )

            # Second call with same content (different packet) returns None
            msg_id_2 = await create_message_from_decrypted(
                packet_id=packet_id_2,
                channel_key="ABC123DEF456",
                sender="Sender",
                message_text="Duplicate test",
                timestamp=1700000000,  # Same sender_timestamp
                received_at=1700000002,
            )

        assert msg_id_1 is not None
        assert msg_id_2 is None  # Duplicate detected

        # Only one message broadcast
        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 1

    @pytest.mark.asyncio
    async def test_links_raw_packet_to_message(self, test_db, captured_broadcasts):
        """create_message_from_decrypted links raw packet to created message."""
        from app.packet_processor import create_message_from_decrypted

        packet_id, _ = await RawPacketRepository.create(b"test_packet", 1700000000)

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            await create_message_from_decrypted(
                packet_id=packet_id,
                channel_key="ABC123DEF456",
                sender="Sender",
                message_text="Link test",
                timestamp=1700000000,
                received_at=1700000001,
            )

        # Verify packet is marked decrypted (has message_id set)
        undecrypted = await RawPacketRepository.get_all_undecrypted()
        packet_ids = [p[0] for p in undecrypted]
        assert packet_id not in packet_ids  # Should be marked as decrypted


class TestMessageBroadcastStructure:
    """Test that message broadcasts have the correct structure for frontend."""

    @pytest.mark.asyncio
    async def test_realtime_broadcast_includes_path(self, test_db, captured_broadcasts):
        """Real-time packet processing includes path in broadcast."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["channel_message"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])
        channel_key_hex = fixture["channel_key_hex"].upper()

        await ChannelRepository.upsert(
            key=channel_key_hex, name=fixture["channel_name"], is_hashtag=True
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            await process_raw_packet(packet_bytes, timestamp=1700000000)

        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 1

        broadcast = message_broadcasts[0]["data"]
        # Real-time processing extracts path from packet (flood packets have empty path)
        assert "paths" in broadcast
        # The test packet is a flood packet, so paths should contain a single entry with empty path
        assert broadcast["paths"] is not None
        assert len(broadcast["paths"]) == 1
        assert broadcast["paths"][0]["path"] == ""  # Empty string = direct/flood


class TestRawPacketStorage:
    """Test raw packet storage for later decryption."""

    @pytest.mark.asyncio
    async def test_raw_packet_stored_with_decryption_status(self, test_db, captured_broadcasts):
        """Raw packets are stored with correct decryption status."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["channel_message"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])
        channel_key_hex = fixture["channel_key_hex"].upper()

        # Create channel so packet can be decrypted
        await ChannelRepository.upsert(
            key=channel_key_hex, name=fixture["channel_name"], is_hashtag=True
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            await process_raw_packet(packet_bytes, timestamp=1700000000)

        # Verify raw_packet broadcast was sent
        raw_broadcasts = [b for b in broadcasts if b["type"] == "raw_packet"]
        assert len(raw_broadcasts) == 1

        # Verify broadcast includes decryption info
        raw_broadcast = raw_broadcasts[0]["data"]
        assert raw_broadcast["decrypted"] is True
        assert "decrypted_info" in raw_broadcast
        assert raw_broadcast["decrypted_info"]["channel_name"] == fixture["channel_name"]


class TestCreateDMMessageFromDecrypted:
    """Test the DM message creation function for direct message decryption."""

    # Test data from real MeshCore DM example
    FACE12_PRIV = (
        "58BA1940E97099CBB4357C62CE9C7F4B245C94C90D722E67201B989F9FEACF7B"
        "77ACADDB84438514022BDB0FC3140C2501859BE1772AC7B8C7E41DC0F40490A1"
    )
    # FACE12 public key - derived via scalar × basepoint, NOT the last 32 bytes!
    # The last 32 bytes (77AC...) are the signing prefix, not the public key.
    FACE12_PUB = "FACE123334789E2B81519AFDBC39A3C9EB7EA3457AD367D3243597A484847E46"
    A1B2C3_PUB = "a1b2c3d3ba9f5fa8705b9845fe11cc6f01d1d49caaf4d122ac7121663c5beec7"

    @pytest.mark.asyncio
    async def test_schedules_bot_in_background(self, test_db, captured_broadcasts):
        """Bot execution is scheduled and does not block DM persistence."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import create_dm_message_from_decrypted

        packet_id, _ = await RawPacketRepository.create(b"test_packet_bot_dm", 1700000000)
        decrypted = DecryptedDirectMessage(
            timestamp=1700000000,
            flags=0,
            message="Hello from DM",
            dest_hash="fa",
            src_hash="a1",
        )
        broadcasts, mock_broadcast = captured_broadcasts

        def _capture_task(coro):
            coro.close()
            return MagicMock()

        with (
            patch("app.packet_processor.broadcast_event", mock_broadcast),
            patch(
                "app.packet_processor.asyncio.create_task", side_effect=_capture_task
            ) as mock_task,
            patch("app.bot.run_bot_for_message", new_callable=AsyncMock) as mock_bot,
        ):
            msg_id = await create_dm_message_from_decrypted(
                packet_id=packet_id,
                decrypted=decrypted,
                their_public_key=self.A1B2C3_PUB,
                our_public_key=self.FACE12_PUB,
                received_at=1700000001,
                outgoing=False,
                trigger_bot=True,
            )

        assert msg_id is not None
        mock_task.assert_called_once()
        mock_bot.assert_called_once()
        assert mock_bot.await_count == 0

    @pytest.mark.asyncio
    async def test_creates_dm_message_and_broadcasts(self, test_db, captured_broadcasts):
        """create_dm_message_from_decrypted creates message and broadcasts correctly."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import create_dm_message_from_decrypted

        # Create a raw packet first
        packet_id, _ = await RawPacketRepository.create(b"test_dm_packet", 1700000000)

        # Create a mock decrypted message
        decrypted = DecryptedDirectMessage(
            timestamp=1700000000,
            flags=0,
            message="Hello, World!",
            dest_hash="fa",
            src_hash="a1",
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            msg_id = await create_dm_message_from_decrypted(
                packet_id=packet_id,
                decrypted=decrypted,
                their_public_key=self.A1B2C3_PUB,
                our_public_key=self.FACE12_PUB,
                received_at=1700000001,
                outgoing=False,
            )

        # Should return a message ID
        assert msg_id is not None
        assert isinstance(msg_id, int)

        # Verify message was stored in database
        messages = await MessageRepository.get_all(
            msg_type="PRIV", conversation_key=self.A1B2C3_PUB.lower(), limit=10
        )
        assert len(messages) == 1
        assert messages[0].text == "Hello, World!"
        assert messages[0].sender_timestamp == 1700000000
        assert messages[0].outgoing is False

        # Verify broadcast was sent with correct structure
        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 1

        broadcast = message_broadcasts[0]["data"]
        assert broadcast["id"] == msg_id
        assert broadcast["type"] == "PRIV"
        assert broadcast["conversation_key"] == self.A1B2C3_PUB.lower()
        assert broadcast["text"] == "Hello, World!"
        assert broadcast["outgoing"] is False

    @pytest.mark.asyncio
    async def test_handles_outgoing_dm(self, test_db, captured_broadcasts):
        """create_dm_message_from_decrypted handles outgoing messages correctly."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import create_dm_message_from_decrypted

        packet_id, _ = await RawPacketRepository.create(b"test_outgoing_dm", 1700000000)

        decrypted = DecryptedDirectMessage(
            timestamp=1700000000,
            flags=0,
            message="My outgoing message",
            dest_hash="a1",  # Destination is contact (first byte of A1B2C3_PUB)
            src_hash="fa",  # Source is us (first byte of derived FACE12_PUB)
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            msg_id = await create_dm_message_from_decrypted(
                packet_id=packet_id,
                decrypted=decrypted,
                their_public_key=self.A1B2C3_PUB,
                our_public_key=self.FACE12_PUB,
                received_at=1700000001,
                outgoing=True,
            )

        assert msg_id is not None

        # Verify outgoing flag is set correctly
        messages = await MessageRepository.get_all(
            msg_type="PRIV", conversation_key=self.A1B2C3_PUB.lower(), limit=10
        )
        assert len(messages) == 1
        assert messages[0].outgoing is True

        # Verify broadcast shows outgoing
        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert message_broadcasts[0]["data"]["outgoing"] is True

    @pytest.mark.asyncio
    async def test_returns_none_for_duplicate_dm(self, test_db, captured_broadcasts):
        """create_dm_message_from_decrypted returns None for duplicate DM."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import create_dm_message_from_decrypted

        packet_id_1, _ = await RawPacketRepository.create(b"dm_packet_1", 1700000000)
        packet_id_2, _ = await RawPacketRepository.create(b"dm_packet_2", 1700000001)

        decrypted = DecryptedDirectMessage(
            timestamp=1700000000,
            flags=0,
            message="Duplicate DM test",
            dest_hash="fa",
            src_hash="a1",
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            # First call creates the message
            msg_id_1 = await create_dm_message_from_decrypted(
                packet_id=packet_id_1,
                decrypted=decrypted,
                their_public_key=self.A1B2C3_PUB,
                our_public_key=self.FACE12_PUB,
                received_at=1700000001,
                outgoing=False,
            )

            # Second call with same content returns None
            msg_id_2 = await create_dm_message_from_decrypted(
                packet_id=packet_id_2,
                decrypted=decrypted,
                their_public_key=self.A1B2C3_PUB,
                our_public_key=self.FACE12_PUB,
                received_at=1700000002,
                outgoing=False,
            )

        assert msg_id_1 is not None
        assert msg_id_2 is None  # Duplicate detected

        # Only one message broadcast
        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 1

    @pytest.mark.asyncio
    async def test_links_raw_packet_to_dm_message(self, test_db, captured_broadcasts):
        """create_dm_message_from_decrypted links raw packet to message."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import create_dm_message_from_decrypted

        packet_id, _ = await RawPacketRepository.create(b"link_test_dm", 1700000000)

        decrypted = DecryptedDirectMessage(
            timestamp=1700000000,
            flags=0,
            message="Link test DM",
            dest_hash="fa",
            src_hash="a1",
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            await create_dm_message_from_decrypted(
                packet_id=packet_id,
                decrypted=decrypted,
                their_public_key=self.A1B2C3_PUB,
                our_public_key=self.FACE12_PUB,
                received_at=1700000001,
                outgoing=False,
            )

        # Verify packet is marked decrypted
        undecrypted = await RawPacketRepository.get_all_undecrypted()
        packet_ids = [p[0] for p in undecrypted]
        assert packet_id not in packet_ids

    @pytest.mark.asyncio
    async def test_dm_includes_path_in_broadcast(self, test_db, captured_broadcasts):
        """create_dm_message_from_decrypted includes path in broadcast when provided."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import create_dm_message_from_decrypted

        packet_id, _ = await RawPacketRepository.create(b"path_test_dm", 1700000000)

        decrypted = DecryptedDirectMessage(
            timestamp=1700000000,
            flags=0,
            message="Path test DM",
            dest_hash="fa",
            src_hash="a1",
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            await create_dm_message_from_decrypted(
                packet_id=packet_id,
                decrypted=decrypted,
                their_public_key=self.A1B2C3_PUB,
                our_public_key=self.FACE12_PUB,
                received_at=1700000001,
                path="aabbcc",  # Path through 3 repeaters
                outgoing=False,
            )

        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 1

        broadcast = message_broadcasts[0]["data"]
        assert broadcast["paths"] is not None
        assert len(broadcast["paths"]) == 1
        assert broadcast["paths"][0]["path"] == "aabbcc"
        assert broadcast["paths"][0]["received_at"] == 1700000001


class TestDMDecryptionFunction:
    """Test the DM decryption function with real crypto."""

    # Same test data
    FACE12_PRIV = bytes.fromhex(
        "58BA1940E97099CBB4357C62CE9C7F4B245C94C90D722E67201B989F9FEACF7B"
        "77ACADDB84438514022BDB0FC3140C2501859BE1772AC7B8C7E41DC0F40490A1"
    )
    # FACE12 public key - derived via scalar × basepoint, NOT the last 32 bytes!
    # The last 32 bytes (77AC...) are the signing prefix, not the public key.
    FACE12_PUB = bytes.fromhex("FACE123334789E2B81519AFDBC39A3C9EB7EA3457AD367D3243597A484847E46")
    A1B2C3_PUB = bytes.fromhex("a1b2c3d3ba9f5fa8705b9845fe11cc6f01d1d49caaf4d122ac7121663c5beec7")
    FULL_PACKET = bytes.fromhex(
        "0900FAA1295471ADB44A98B13CA528A4B5C4FBC29B4DA3CED477519B2FBD8FD5467C31E5D58B"
    )
    EXPECTED_MESSAGE = "Hello there, Mr. Face!"

    @pytest.mark.asyncio
    async def test_full_dm_decryption_pipeline(self, test_db, captured_broadcasts):
        """Test complete DM decryption from raw packet through to stored message."""
        from app.decoder import try_decrypt_dm
        from app.packet_processor import create_dm_message_from_decrypted

        # Store the raw packet
        packet_id, _ = await RawPacketRepository.create(self.FULL_PACKET, 1700000000)

        # Decrypt the packet
        decrypted = try_decrypt_dm(
            self.FULL_PACKET,
            self.FACE12_PRIV,
            self.A1B2C3_PUB,
            our_public_key=self.FACE12_PUB,
        )

        assert decrypted is not None
        assert decrypted.message == self.EXPECTED_MESSAGE

        # Determine direction (src_hash = a1 matches A1B2C3, so it's inbound)
        outgoing = decrypted.src_hash == format(self.FACE12_PUB[0], "02x")
        assert outgoing is False  # This is an inbound message

        broadcasts, mock_broadcast = captured_broadcasts

        # Create the message
        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            msg_id = await create_dm_message_from_decrypted(
                packet_id=packet_id,
                decrypted=decrypted,
                their_public_key=self.A1B2C3_PUB.hex(),
                our_public_key=self.FACE12_PUB.hex(),
                received_at=1700000000,
                outgoing=outgoing,
            )

        assert msg_id is not None

        # Verify the message is stored correctly
        messages = await MessageRepository.get_all(
            msg_type="PRIV", conversation_key=self.A1B2C3_PUB.hex().lower(), limit=10
        )
        assert len(messages) == 1
        assert messages[0].text == self.EXPECTED_MESSAGE
        assert messages[0].outgoing is False

        # Verify raw packet is linked
        undecrypted = await RawPacketRepository.get_all_undecrypted()
        assert packet_id not in [p[0] for p in undecrypted]


class TestRepeaterMessageFiltering:
    """Test that messages from repeaters are not stored in chat history.

    Repeaters only send CLI responses (not chat messages), and these are handled
    by the command endpoint. The packet processor filters them out based on
    contact type to prevent duplicate storage.
    """

    # A repeater contact
    REPEATER_PUB = "a1b2c3d3ba9f5fa8705b9845fe11cc6f01d1d49caaf4d122ac7121663c5beec7"
    # A normal client contact
    CLIENT_PUB = "b2c3d4e4cb0a6fb9816ca956ff22dd7f12e2e5adbbf5e233bd8232774d6cffe8"
    # Our public key
    OUR_PUB = "FACE123334789E2B81519AFDBC39A3C9EB7EA3457AD367D3243597A484847E46"

    @pytest.mark.asyncio
    async def test_repeater_message_not_stored(self, test_db, captured_broadcasts):
        """Messages from repeaters should not be stored in database."""
        from app.decoder import DecryptedDirectMessage
        from app.models import CONTACT_TYPE_REPEATER
        from app.packet_processor import create_dm_message_from_decrypted
        from app.repository import ContactRepository, MessageRepository, RawPacketRepository

        # Create a repeater contact first
        await ContactRepository.upsert(
            {
                "public_key": self.REPEATER_PUB,
                "name": "Test Repeater",
                "type": CONTACT_TYPE_REPEATER,  # type=2 is repeater
                "flags": 0,
                "on_radio": False,
            }
        )

        # Store a raw packet
        packet_id, _ = await RawPacketRepository.create(b"\x09\x00test", 1700000000)

        # Create a DecryptedDirectMessage (simulating a CLI response from repeater)
        decrypted = DecryptedDirectMessage(
            timestamp=1700000000,
            flags=0,  # flags don't matter - we filter by contact type
            message="cli response: version 1.0",
            dest_hash="fa",
            src_hash="a1",
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            msg_id = await create_dm_message_from_decrypted(
                packet_id=packet_id,
                decrypted=decrypted,
                their_public_key=self.REPEATER_PUB,
                our_public_key=self.OUR_PUB,
                received_at=1700000001,
                outgoing=False,
            )

        # Should return None (not stored because sender is a repeater)
        assert msg_id is None

        # Should not broadcast
        assert len(broadcasts) == 0

        # Should not be in database
        messages = await MessageRepository.get_all(
            msg_type="PRIV", conversation_key=self.REPEATER_PUB.lower(), limit=10
        )
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_client_message_still_stored(self, test_db, captured_broadcasts):
        """Messages from normal clients should still be stored."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import create_dm_message_from_decrypted
        from app.repository import ContactRepository, MessageRepository, RawPacketRepository

        # Create a normal client contact (type=1)
        await ContactRepository.upsert(
            {
                "public_key": self.CLIENT_PUB,
                "name": "Test Client",
                "type": 1,  # type=1 is client
                "flags": 0,
                "on_radio": False,
            }
        )

        packet_id, _ = await RawPacketRepository.create(b"\x09\x00test2", 1700000000)

        decrypted = DecryptedDirectMessage(
            timestamp=1700000000,
            flags=0,
            message="Hello, world!",
            dest_hash="fa",
            src_hash="b2",
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            msg_id = await create_dm_message_from_decrypted(
                packet_id=packet_id,
                decrypted=decrypted,
                their_public_key=self.CLIENT_PUB,
                our_public_key=self.OUR_PUB,
                received_at=1700000001,
                outgoing=False,
            )

        # Should return message ID (stored because sender is a client)
        assert msg_id is not None

        # Should broadcast
        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 1

        # Should be in database
        messages = await MessageRepository.get_all(
            msg_type="PRIV", conversation_key=self.CLIENT_PUB.lower(), limit=10
        )
        assert len(messages) == 1


class TestProcessDirectMessageDispatch:
    """T1: Test _process_direct_message dispatch logic.

    This tests the internal function that determines direction (incoming vs outgoing),
    looks up candidate contacts by first-byte hash, and attempts DM decryption.
    Uses real DB for contacts, mocks keystore and decoder functions.
    """

    # Our public key starts with 0xFA
    OUR_PUB_HEX = "FACE123334789E2B81519AFDBC39A3C9EB7EA3457AD367D3243597A484847E46"
    OUR_PUB = bytes.fromhex(OUR_PUB_HEX)
    OUR_PRIV = bytes(64)  # Dummy 64-byte private key (mocked, never actually used for crypto)

    # Contact whose public key starts with 0xA1
    CONTACT_PUB_HEX = "a1b2c3d3ba9f5fa8705b9845fe11cc6f01d1d49caaf4d122ac7121663c5beec7"
    CONTACT_PUB = bytes.fromhex(CONTACT_PUB_HEX)

    def _make_packet_info(
        self, dest_byte: int, src_byte: int, payload_extra: bytes = b"\x00" * 32
    ) -> PacketInfo:
        """Build a PacketInfo with a TEXT_MESSAGE payload containing given dest/src hash bytes."""
        # payload: [dest_hash:1][src_hash:1][mac:2][ciphertext...]
        payload = bytes([dest_byte, src_byte]) + payload_extra
        return PacketInfo(
            route_type=1,  # FLOOD
            payload_type=PayloadType.TEXT_MESSAGE,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=payload,
        )

    def _keystore_patches(self, has_key=True):
        """Return a context manager stack that patches keystore functions."""
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(patch("app.packet_processor.has_private_key", return_value=has_key))
        stack.enter_context(
            patch(
                "app.packet_processor.get_private_key",
                return_value=self.OUR_PRIV if has_key else None,
            )
        )
        stack.enter_context(
            patch(
                "app.packet_processor.get_public_key",
                return_value=self.OUR_PUB if has_key else None,
            )
        )
        return stack

    @pytest.mark.asyncio
    async def test_returns_none_when_no_private_key(self, test_db):
        """Without a private key, _process_direct_message returns None immediately."""
        from app.packet_processor import _process_direct_message

        packet_info = self._make_packet_info(0xFA, 0xA1)
        with self._keystore_patches(has_key=False):
            result = await _process_direct_message(b"\x09\x00" + b"\x00" * 30, 1, 1000, packet_info)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_packet_info_is_none(self, test_db):
        """When packet_info is None and parse_packet also returns None, returns None."""
        from app.packet_processor import _process_direct_message

        with self._keystore_patches(has_key=True):
            with patch("app.packet_processor.parse_packet", return_value=None):
                result = await _process_direct_message(b"\x09\x00", 1, 1000, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_payload_too_short(self, test_db):
        """Payload shorter than 4 bytes causes early return."""
        from app.packet_processor import _process_direct_message

        short_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.TEXT_MESSAGE,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\xfa\xa1\x00",  # Only 3 bytes
        )
        with self._keystore_patches(has_key=True):
            result = await _process_direct_message(b"\x09\x00", 1, 1000, short_info)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_neither_hash_matches_us(self, test_db):
        """If neither dest_hash nor src_hash matches our first byte, returns None."""
        from app.packet_processor import _process_direct_message

        # Our first byte is 0xFA; use 0xBB and 0xCC instead
        packet_info = self._make_packet_info(0xBB, 0xCC)
        with self._keystore_patches(has_key=True):
            result = await _process_direct_message(b"\x09\x00" + b"\x00" * 30, 1, 1000, packet_info)
        assert result is None

    @pytest.mark.asyncio
    async def test_incoming_direction_dest_is_us(self, test_db, captured_broadcasts):
        """When dest_hash matches us and src_hash does not, direction is incoming."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import _process_direct_message

        # dest=0xFA (us), src=0xA1 (contact) -> incoming
        packet_info = self._make_packet_info(0xFA, 0xA1)

        # Create contact in DB so lookup succeeds
        await ContactRepository.upsert(
            {"public_key": self.CONTACT_PUB_HEX, "name": "Alice", "type": 1}
        )

        mock_decrypted = DecryptedDirectMessage(
            timestamp=1000, flags=0, message="Hello", dest_hash="fa", src_hash="a1"
        )
        broadcasts, mock_broadcast = captured_broadcasts

        with self._keystore_patches(has_key=True):
            with patch(
                "app.packet_processor.try_decrypt_dm", return_value=mock_decrypted
            ) as mock_try:
                with patch("app.packet_processor.broadcast_event", mock_broadcast):
                    result = await _process_direct_message(
                        b"\x09\x00" + b"\x00" * 30, 1, 1000, packet_info
                    )

        assert result is not None
        assert result["decrypted"] is True
        # Verify try_decrypt_dm was called with our_public_key (incoming => filter enabled)
        call_kwargs = mock_try.call_args
        assert (
            call_kwargs[1].get("our_public_key") == self.OUR_PUB
            or call_kwargs[0][3] == self.OUR_PUB
        )

    @pytest.mark.asyncio
    async def test_outgoing_direction_src_is_us(self, test_db, captured_broadcasts):
        """When src_hash matches us and dest_hash does not, direction is outgoing."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import _process_direct_message

        # src=0xFA (us), dest=0xA1 (contact) -> outgoing
        packet_info = self._make_packet_info(0xA1, 0xFA)

        await ContactRepository.upsert(
            {"public_key": self.CONTACT_PUB_HEX, "name": "Alice", "type": 1}
        )

        mock_decrypted = DecryptedDirectMessage(
            timestamp=1000, flags=0, message="My outgoing", dest_hash="a1", src_hash="fa"
        )
        broadcasts, mock_broadcast = captured_broadcasts

        with self._keystore_patches(has_key=True):
            with patch(
                "app.packet_processor.try_decrypt_dm", return_value=mock_decrypted
            ) as mock_try:
                with patch("app.packet_processor.broadcast_event", mock_broadcast):
                    result = await _process_direct_message(
                        b"\x09\x00" + b"\x00" * 30, 1, 1000, packet_info
                    )

        assert result is not None
        assert result["decrypted"] is True
        # Outgoing: our_public_key should be None (skip dest_hash filter)
        call_kwargs = mock_try.call_args
        assert call_kwargs[1].get("our_public_key") is None or call_kwargs[0][3] is None

    @pytest.mark.asyncio
    async def test_ambiguous_both_hashes_match_defaults_incoming(
        self, test_db, captured_broadcasts
    ):
        """When both dest_hash and src_hash match our first byte, defaults to incoming."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import _process_direct_message

        # Both 0xFA -> ambiguous, should default to incoming
        packet_info = self._make_packet_info(0xFA, 0xFA)

        # Contact also starts with 0xFA
        fa_contact_pub = "fa" + "bb" * 31
        await ContactRepository.upsert(
            {"public_key": fa_contact_pub, "name": "FaContact", "type": 1}
        )

        mock_decrypted = DecryptedDirectMessage(
            timestamp=1000, flags=0, message="Ambiguous", dest_hash="fa", src_hash="fa"
        )
        broadcasts, mock_broadcast = captured_broadcasts

        with self._keystore_patches(has_key=True):
            with patch(
                "app.packet_processor.try_decrypt_dm", return_value=mock_decrypted
            ) as mock_try:
                with patch("app.packet_processor.broadcast_event", mock_broadcast):
                    result = await _process_direct_message(
                        b"\x09\x00" + b"\x00" * 30, 1, 1000, packet_info
                    )

        assert result is not None
        # For incoming, try_decrypt_dm should be called with our_public_key set
        call_kwargs = mock_try.call_args
        assert (
            call_kwargs[1].get("our_public_key") == self.OUR_PUB
            or call_kwargs[0][3] == self.OUR_PUB
        )

    @pytest.mark.asyncio
    async def test_returns_none_when_no_candidate_contacts(self, test_db):
        """If no contacts match the relevant hash byte, returns None."""
        from app.packet_processor import _process_direct_message

        # Incoming: dest=0xFA (us), src=0xA1 -> looks up contacts starting with "a1"
        packet_info = self._make_packet_info(0xFA, 0xA1)

        # Don't create any contacts -> no candidates
        with self._keystore_patches(has_key=True):
            result = await _process_direct_message(b"\x09\x00" + b"\x00" * 30, 1, 1000, packet_info)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_decrypt_fails_all_candidates(self, test_db):
        """When try_decrypt_dm returns None for all candidates, returns None."""
        from app.packet_processor import _process_direct_message

        packet_info = self._make_packet_info(0xFA, 0xA1)

        await ContactRepository.upsert(
            {"public_key": self.CONTACT_PUB_HEX, "name": "Alice", "type": 1}
        )

        with self._keystore_patches(has_key=True):
            with patch("app.packet_processor.try_decrypt_dm", return_value=None):
                result = await _process_direct_message(
                    b"\x09\x00" + b"\x00" * 30, 1, 1000, packet_info
                )
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_message_on_successful_decrypt(self, test_db, captured_broadcasts):
        """Successful decryption creates a DM message via create_dm_message_from_decrypted."""
        from app.decoder import DecryptedDirectMessage
        from app.packet_processor import _process_direct_message

        # First, create a raw packet so create_dm_message_from_decrypted can link it
        packet_id, _ = await RawPacketRepository.create(b"\x09\x00" + b"\x00" * 30, 1000)

        packet_info = self._make_packet_info(0xFA, 0xA1)

        await ContactRepository.upsert(
            {"public_key": self.CONTACT_PUB_HEX, "name": "Alice", "type": 1}
        )

        mock_decrypted = DecryptedDirectMessage(
            timestamp=1000, flags=0, message="Real message", dest_hash="fa", src_hash="a1"
        )
        broadcasts, mock_broadcast = captured_broadcasts

        with self._keystore_patches(has_key=True):
            with patch("app.packet_processor.try_decrypt_dm", return_value=mock_decrypted):
                with patch("app.packet_processor.broadcast_event", mock_broadcast):
                    result = await _process_direct_message(
                        b"\x09\x00" + b"\x00" * 30, packet_id, 1000, packet_info
                    )

        assert result is not None
        assert result["decrypted"] is True
        assert result["message_id"] is not None

        # Verify message was stored in DB
        messages = await MessageRepository.get_all(
            msg_type="PRIV", conversation_key=self.CONTACT_PUB_HEX.lower(), limit=10
        )
        assert len(messages) == 1
        assert messages[0].text == "Real message"
        assert messages[0].outgoing is False


class TestProcessRawPacketIntegration:
    """T2: Test process_raw_packet dispatching to sub-processors.

    Verifies that the main entry point correctly routes packets by payload type,
    always broadcasts raw_packet events, and returns the expected result structure.
    Uses real DB for packet storage, mocks parse_packet to control payload type.
    """

    @pytest.mark.asyncio
    async def test_dispatches_group_text(self, test_db, captured_broadcasts):
        """GROUP_TEXT packets are dispatched to _process_group_text."""
        from app.packet_processor import process_raw_packet

        broadcasts, mock_broadcast = captured_broadcasts
        raw = b"\x15\x00" + b"\xaa" * 30  # Dummy bytes, parsing is mocked

        group_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.GROUP_TEXT,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\xab" + b"\x00" * 20,
        )

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.parse_packet", return_value=group_info):
                with patch(
                    "app.packet_processor._process_group_text",
                    new_callable=AsyncMock,
                    return_value={
                        "decrypted": True,
                        "channel_name": "#test",
                        "sender": "Bob",
                        "message_id": 99,
                    },
                ) as mock_gt:
                    result = await process_raw_packet(raw, timestamp=2000)

        mock_gt.assert_awaited_once()
        assert result["decrypted"] is True
        assert result["channel_name"] == "#test"

    @pytest.mark.asyncio
    async def test_dispatches_group_text_even_for_duplicates(self, test_db, captured_broadcasts):
        """GROUP_TEXT always dispatches regardless of is_new_packet flag."""
        from app.packet_processor import process_raw_packet

        broadcasts, mock_broadcast = captured_broadcasts

        group_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.GROUP_TEXT,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\xab" + b"\x00" * 20,
        )

        raw = b"\x15\x00" + b"\xbb" * 30

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.parse_packet", return_value=group_info):
                with patch(
                    "app.packet_processor._process_group_text",
                    new_callable=AsyncMock,
                    return_value=None,
                ) as mock_gt:
                    # Process same packet twice
                    await process_raw_packet(raw, timestamp=2000)
                    await process_raw_packet(raw, timestamp=2001)

        # _process_group_text should be called both times
        assert mock_gt.await_count == 2

    @pytest.mark.asyncio
    async def test_dispatches_advert_only_for_new_packets(self, test_db, captured_broadcasts):
        """ADVERT packets are dispatched only when is_new_packet is True."""
        from app.packet_processor import process_raw_packet

        broadcasts, mock_broadcast = captured_broadcasts

        advert_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.ADVERT,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\x00" * 101,
        )

        raw = b"\x11\x00" + b"\xcc" * 30

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.parse_packet", return_value=advert_info):
                with patch(
                    "app.packet_processor._process_advertisement",
                    new_callable=AsyncMock,
                ) as mock_adv:
                    # First call: new packet -> should dispatch
                    await process_raw_packet(raw, timestamp=3000)
                    # Second call: duplicate -> should NOT dispatch
                    await process_raw_packet(raw, timestamp=3001)

        assert mock_adv.await_count == 1

    @pytest.mark.asyncio
    async def test_dispatches_text_message(self, test_db, captured_broadcasts):
        """TEXT_MESSAGE packets are dispatched to _process_direct_message."""
        from app.packet_processor import process_raw_packet

        broadcasts, mock_broadcast = captured_broadcasts

        dm_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.TEXT_MESSAGE,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\xfa\xa1" + b"\x00" * 30,
        )

        raw = b"\x09\x00" + b"\xdd" * 30

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.parse_packet", return_value=dm_info):
                with patch(
                    "app.packet_processor._process_direct_message",
                    new_callable=AsyncMock,
                    return_value={"decrypted": True, "sender": "Alice", "message_id": 42},
                ) as mock_dm:
                    result = await process_raw_packet(raw, timestamp=4000)

        mock_dm.assert_awaited_once()
        assert result["decrypted"] is True

    @pytest.mark.asyncio
    async def test_always_broadcasts_raw_packet(self, test_db, captured_broadcasts):
        """Every call to process_raw_packet broadcasts a raw_packet event."""
        from app.packet_processor import process_raw_packet

        broadcasts, mock_broadcast = captured_broadcasts

        # Use a packet type that does not trigger any sub-processor (e.g. ACK)
        ack_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.ACK,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\x00" * 10,
        )

        raw = b"\x0d\x00" + b"\xee" * 20

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.parse_packet", return_value=ack_info):
                await process_raw_packet(raw, timestamp=5000)

        raw_broadcasts = [b for b in broadcasts if b["type"] == "raw_packet"]
        assert len(raw_broadcasts) == 1
        assert raw_broadcasts[0]["data"]["payload_type"] == "ACK"

    @pytest.mark.asyncio
    async def test_result_structure(self, test_db, captured_broadcasts):
        """process_raw_packet returns a dict with all expected keys."""
        from app.packet_processor import process_raw_packet

        broadcasts, mock_broadcast = captured_broadcasts

        raw = b"\x0d\x00" + b"\xff" * 20
        ack_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.ACK,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\x00" * 10,
        )

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.parse_packet", return_value=ack_info):
                result = await process_raw_packet(raw, timestamp=6000, snr=5.5, rssi=-80)

        assert "packet_id" in result
        assert result["timestamp"] == 6000
        assert result["snr"] == 5.5
        assert result["rssi"] == -80
        assert result["payload_type"] == "ACK"
        assert result["decrypted"] is False
        assert result["message_id"] is None

    @pytest.mark.asyncio
    async def test_raw_packet_stored_in_db(self, test_db, captured_broadcasts):
        """process_raw_packet stores the raw bytes in the database."""
        from app.packet_processor import process_raw_packet

        broadcasts, mock_broadcast = captured_broadcasts
        raw = b"\x0d\x00" + b"\xab\xcd" * 10

        ack_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.ACK,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\x00" * 10,
        )

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.parse_packet", return_value=ack_info):
                result = await process_raw_packet(raw, timestamp=7000)

        # Verify packet is in undecrypted list
        undecrypted = await RawPacketRepository.get_all_undecrypted()
        packet_ids = [p[0] for p in undecrypted]
        assert result["packet_id"] in packet_ids


class TestRunHistoricalDmDecryption:
    """T3: Test run_historical_dm_decryption background task.

    Verifies iteration over undecrypted packets, decryption attempts,
    message creation, and notification broadcasting.
    Uses real DB for raw packet storage, mocks try_decrypt_dm and parse_packet.
    """

    OUR_PUB_HEX = "FACE123334789E2B81519AFDBC39A3C9EB7EA3457AD367D3243597A484847E46"
    OUR_PUB = bytes.fromhex(OUR_PUB_HEX)
    OUR_PRIV = bytes.fromhex(
        "58BA1940E97099CBB4357C62CE9C7F4B245C94C90D722E67201B989F9FEACF7B"
        "77ACADDB84438514022BDB0FC3140C2501859BE1772AC7B8C7E41DC0F40490A1"
    )

    CONTACT_PUB_HEX = "a1b2c3d3ba9f5fa8705b9845fe11cc6f01d1d49caaf4d122ac7121663c5beec7"
    CONTACT_PUB = bytes.fromhex(CONTACT_PUB_HEX)

    def _make_text_message_bytes(self, unique_suffix: bytes = b"") -> bytes:
        """Build a minimal raw packet with TEXT_MESSAGE payload type.

        Packet header byte: route_type=FLOOD(0x01), payload_type=TEXT_MESSAGE(0x02), version=0
        header = (0x02 << 2) | 0x01 = 0x09
        Then path_length=0, then payload with dest/src/mac/ciphertext.
        """
        header = 0x09
        path_length = 0
        # Payload: [dest:1][src:1][mac:2][ciphertext:16] = 20 bytes min
        payload = bytes([0xFA, 0xA1]) + b"\x00\x00" + b"\xab" * 16 + unique_suffix
        return bytes([header, path_length]) + payload

    @pytest.mark.asyncio
    async def test_returns_early_when_no_undecrypted_packets(self, test_db, captured_broadcasts):
        """With no undecrypted TEXT_MESSAGE packets, returns immediately without broadcasting."""
        from app.packet_processor import run_historical_dm_decryption

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.websocket.ws_manager") as mock_ws:
                mock_ws.broadcast = AsyncMock()
                await run_historical_dm_decryption(
                    self.OUR_PRIV, self.CONTACT_PUB, self.CONTACT_PUB_HEX
                )

        # No success broadcast should have been sent
        success_broadcasts = [b for b in broadcasts if b["type"] == "success"]
        assert len(success_broadcasts) == 0

    @pytest.mark.asyncio
    async def test_iterates_and_decrypts_packets(self, test_db, captured_broadcasts):
        """Successfully decrypts packets and creates messages in DB."""
        from app.packet_processor import run_historical_dm_decryption

        # Store some TEXT_MESSAGE packets in DB
        raw1 = self._make_text_message_bytes(b"\x01")
        raw2 = self._make_text_message_bytes(b"\x02")
        raw3 = self._make_text_message_bytes(b"\x03")
        pkt_id1, _ = await RawPacketRepository.create(raw1, 1000)
        pkt_id2, _ = await RawPacketRepository.create(raw2, 1001)
        pkt_id3, _ = await RawPacketRepository.create(raw3, 1002)

        mock_packet_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.TEXT_MESSAGE,
            payload_version=0,
            path_length=2,
            path=b"\xaa\xbb",
            payload=b"\xfa\xa1" + b"\x00" * 18,
        )

        call_count = 0

        def mock_decrypt(raw, priv, contact_pub, our_public_key=None):
            nonlocal call_count
            call_count += 1
            # Decrypt packets 1 and 3, fail on packet 2
            if call_count in (1, 3):
                return DecryptedDirectMessage(
                    timestamp=1000 + call_count,
                    flags=0,
                    message=f"Decrypted message {call_count}",
                    dest_hash="fa",
                    src_hash="a1",
                )
            return None

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.try_decrypt_dm", side_effect=mock_decrypt):
                with patch("app.packet_processor.parse_packet", return_value=mock_packet_info):
                    with patch("app.packet_processor.derive_public_key", return_value=self.OUR_PUB):
                        with patch("app.websocket.ws_manager") as mock_ws:
                            mock_ws.broadcast = AsyncMock()
                            await run_historical_dm_decryption(
                                self.OUR_PRIV, self.CONTACT_PUB, self.CONTACT_PUB_HEX
                            )

        # 2 of 3 packets should have been decrypted
        messages = await MessageRepository.get_all(
            msg_type="PRIV", conversation_key=self.CONTACT_PUB_HEX.lower(), limit=10
        )
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_does_not_create_message_on_decrypt_failure(self, test_db, captured_broadcasts):
        """When try_decrypt_dm returns None for all packets, no messages are created."""
        from app.packet_processor import run_historical_dm_decryption

        raw = self._make_text_message_bytes(b"\x10")
        await RawPacketRepository.create(raw, 2000)

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.try_decrypt_dm", return_value=None):
                with patch("app.packet_processor.derive_public_key", return_value=self.OUR_PUB):
                    with patch("app.websocket.ws_manager") as mock_ws:
                        mock_ws.broadcast = AsyncMock()
                        await run_historical_dm_decryption(
                            self.OUR_PRIV, self.CONTACT_PUB, self.CONTACT_PUB_HEX
                        )

        messages = await MessageRepository.get_all(
            msg_type="PRIV", conversation_key=self.CONTACT_PUB_HEX.lower(), limit=10
        )
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_sets_trigger_bot_false(self, test_db, captured_broadcasts):
        """Historical decryption calls create_dm_message_from_decrypted with trigger_bot=False."""
        from app.packet_processor import run_historical_dm_decryption

        raw = self._make_text_message_bytes(b"\x20")
        await RawPacketRepository.create(raw, 3000)

        mock_packet_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.TEXT_MESSAGE,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\xfa\xa1" + b"\x00" * 18,
        )

        mock_decrypted = DecryptedDirectMessage(
            timestamp=3000, flags=0, message="Historical msg", dest_hash="fa", src_hash="a1"
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.try_decrypt_dm", return_value=mock_decrypted):
                with patch("app.packet_processor.parse_packet", return_value=mock_packet_info):
                    with patch("app.packet_processor.derive_public_key", return_value=self.OUR_PUB):
                        with patch(
                            "app.packet_processor.create_dm_message_from_decrypted",
                            new_callable=AsyncMock,
                            return_value=42,
                        ) as mock_create:
                            with patch("app.websocket.ws_manager") as mock_ws:
                                mock_ws.broadcast = AsyncMock()
                                await run_historical_dm_decryption(
                                    self.OUR_PRIV, self.CONTACT_PUB, self.CONTACT_PUB_HEX
                                )

        mock_create.assert_awaited_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["trigger_bot"] is False

    @pytest.mark.asyncio
    async def test_broadcasts_success_when_decrypted(self, test_db, captured_broadcasts):
        """When at least one packet is decrypted, broadcasts a success notification."""
        from app.packet_processor import run_historical_dm_decryption

        raw = self._make_text_message_bytes(b"\x30")
        await RawPacketRepository.create(raw, 4000)

        mock_packet_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.TEXT_MESSAGE,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\xfa\xa1" + b"\x00" * 18,
        )
        mock_decrypted = DecryptedDirectMessage(
            timestamp=4000, flags=0, message="Success msg", dest_hash="fa", src_hash="a1"
        )

        broadcasts, mock_broadcast = captured_broadcasts
        success_calls = []

        def mock_success(message, details=None):
            success_calls.append({"message": message, "details": details})

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.try_decrypt_dm", return_value=mock_decrypted):
                with patch("app.packet_processor.parse_packet", return_value=mock_packet_info):
                    with patch("app.packet_processor.derive_public_key", return_value=self.OUR_PUB):
                        with patch("app.websocket.broadcast_success", mock_success):
                            await run_historical_dm_decryption(
                                self.OUR_PRIV,
                                self.CONTACT_PUB,
                                self.CONTACT_PUB_HEX,
                                display_name="Alice",
                            )

        assert len(success_calls) == 1
        assert "Alice" in success_calls[0]["message"]
        assert "1 message" in success_calls[0]["details"]

    @pytest.mark.asyncio
    async def test_no_broadcast_when_zero_decrypted(self, test_db, captured_broadcasts):
        """When no packets are decrypted, no success notification is broadcast."""
        from app.packet_processor import run_historical_dm_decryption

        raw = self._make_text_message_bytes(b"\x40")
        await RawPacketRepository.create(raw, 5000)

        broadcasts, mock_broadcast = captured_broadcasts
        success_calls = []

        def mock_success(message, details=None):
            success_calls.append({"message": message, "details": details})

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.try_decrypt_dm", return_value=None):
                with patch("app.packet_processor.derive_public_key", return_value=self.OUR_PUB):
                    with patch("app.websocket.broadcast_success", mock_success):
                        await run_historical_dm_decryption(
                            self.OUR_PRIV, self.CONTACT_PUB, self.CONTACT_PUB_HEX
                        )

        assert len(success_calls) == 0

    @pytest.mark.asyncio
    async def test_plural_message_in_success_broadcast(self, test_db, captured_broadcasts):
        """Success notification uses plural 'messages' when count > 1."""
        from app.packet_processor import run_historical_dm_decryption

        # Create two distinct TEXT_MESSAGE packets
        raw1 = self._make_text_message_bytes(b"\x50")
        raw2 = self._make_text_message_bytes(b"\x51")
        await RawPacketRepository.create(raw1, 6000)
        await RawPacketRepository.create(raw2, 6001)

        mock_packet_info = PacketInfo(
            route_type=1,
            payload_type=PayloadType.TEXT_MESSAGE,
            payload_version=0,
            path_length=0,
            path=b"",
            payload=b"\xfa\xa1" + b"\x00" * 18,
        )

        call_idx = 0

        def mock_decrypt(raw, priv, contact_pub, our_public_key=None):
            nonlocal call_idx
            call_idx += 1
            return DecryptedDirectMessage(
                timestamp=6000 + call_idx,
                flags=0,
                message=f"Msg {call_idx}",
                dest_hash="fa",
                src_hash="a1",
            )

        broadcasts, mock_broadcast = captured_broadcasts
        success_calls = []

        def mock_success(message, details=None):
            success_calls.append({"message": message, "details": details})

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            with patch("app.packet_processor.try_decrypt_dm", side_effect=mock_decrypt):
                with patch("app.packet_processor.parse_packet", return_value=mock_packet_info):
                    with patch("app.packet_processor.derive_public_key", return_value=self.OUR_PUB):
                        with patch("app.websocket.broadcast_success", mock_success):
                            await run_historical_dm_decryption(
                                self.OUR_PRIV,
                                self.CONTACT_PUB,
                                self.CONTACT_PUB_HEX,
                                display_name="Bob",
                            )

        assert len(success_calls) == 1
        assert "2 messages" in success_calls[0]["details"]
