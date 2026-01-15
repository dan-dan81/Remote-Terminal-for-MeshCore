"""End-to-end tests for the packet processing pipeline.

These tests verify the full flow from raw packet arrival through to
WebSocket broadcast, using real packet data and a real database.

The fixtures in fixtures/websocket_events.json define the contract
between backend and frontend - both sides test against the same data.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.database import Database
from app.repository import ChannelRepository, MessageRepository, ContactRepository, RawPacketRepository


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
    async def test_channel_message_creates_message_and_broadcasts(self, test_db, captured_broadcasts):
        """A decryptable channel packet creates a message and broadcasts it."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["channel_message"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])

        # Create the channel in DB first using upsert
        await ChannelRepository.upsert(
            key=fixture["channel_key_hex"].upper(),
            name=fixture["channel_name"],
            is_hashtag=True
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            result = await process_raw_packet(packet_bytes, timestamp=1700000000)

        # Verify packet was processed successfully
        assert result is not None
        assert result.get("decrypted") is True

        # Verify message was stored in database
        messages = await MessageRepository.get_all(
            msg_type="CHAN",
            conversation_key=fixture["channel_key_hex"].upper(),
            limit=10
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
        assert expected["text"][:30] in broadcast["data"]["text"]  # Check text contains expected content

    @pytest.mark.asyncio
    async def test_duplicate_packet_not_broadcast_twice(self, test_db, captured_broadcasts):
        """Same packet arriving twice only creates one message and one broadcast."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["duplicate_channel_message"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])
        channel_key_hex = "7ABA109EDCF304A84433CB71D0F3AB73"

        # Create the channel in DB first
        await ChannelRepository.upsert(
            key=channel_key_hex,
            name=fixture["channel_name"],
            is_hashtag=True
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
            msg_type="CHAN",
            conversation_key=channel_key_hex,
            limit=10
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
        raw_packets = await RawPacketRepository.get_undecrypted(limit=10)
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
            result = await process_raw_packet(packet_bytes, timestamp=1700000000)

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
        await ContactRepository.upsert({
            "public_key": expected["public_key"],
            "name": "OldName",
            "type": 0,
            "lat": None,
            "lon": None
        })

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
    async def test_advertisement_keeps_shorter_path_within_window(self, test_db, captured_broadcasts):
        """When receiving echoed advertisements, keep the shortest path within 60s window."""
        from app.packet_processor import _process_advertisement
        from app.decoder import parse_packet

        # Create a contact with a longer path (path_len=3)
        test_pubkey = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        await ContactRepository.upsert({
            "public_key": test_pubkey,
            "name": "TestNode",
            "type": 1,
            "last_seen": 1000,
            "last_path_len": 3,
            "last_path": "aabbcc",  # 3 bytes = 3 hops
        })

        # Simulate receiving a shorter path (path_len=1) within 60s
        # We'll call _process_advertisement directly with mock packet_info
        from unittest.mock import MagicMock
        from app.decoder import PacketInfo, RouteType, PayloadType, ParsedAdvertisement

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
            outgoing=True
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
            limit=10
        )
        assert len(messages) == 1
        assert messages[0].acked == 1

        # Verify broadcast format matches fixture
        ack_broadcasts = [b for b in broadcasts if b["type"] == "message_acked"]
        assert len(ack_broadcasts) == 1

        expected = FIXTURES["message_acked"]["expected_ws_event"]["data"]
        broadcast = ack_broadcasts[0]
        assert "message_id" in broadcast["data"]
        assert "ack_count" in broadcast["data"]
        assert broadcast["data"]["ack_count"] == 1


class TestCreateMessageFromDecrypted:
    """Test the shared message creation function used by both real-time and historical decryption."""

    @pytest.mark.asyncio
    async def test_creates_message_and_broadcasts(self, test_db, captured_broadcasts):
        """create_message_from_decrypted creates message and broadcasts correctly."""
        from app.packet_processor import create_message_from_decrypted

        # Create a raw packet first (required for the function)
        packet_id = await RawPacketRepository.create(b"test_packet_data", 1700000000)

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
            msg_type="CHAN",
            conversation_key="ABC123DEF456",
            limit=10
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
        assert broadcast["path_len"] is None  # Historical decryption has no path info
        assert broadcast["outgoing"] is False
        assert broadcast["acked"] == 0

    @pytest.mark.asyncio
    async def test_handles_message_without_sender(self, test_db, captured_broadcasts):
        """create_message_from_decrypted handles messages without sender prefix."""
        from app.packet_processor import create_message_from_decrypted

        packet_id = await RawPacketRepository.create(b"test_packet_data_2", 1700000000)

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
            msg_type="CHAN",
            conversation_key="ABC123DEF456",
            limit=10
        )
        assert len(messages) == 1
        assert messages[0].text == "System message"  # No "None: " prefix

    @pytest.mark.asyncio
    async def test_returns_none_for_duplicate(self, test_db, captured_broadcasts):
        """create_message_from_decrypted returns None for duplicate message."""
        from app.packet_processor import create_message_from_decrypted

        packet_id_1 = await RawPacketRepository.create(b"packet_1", 1700000000)
        packet_id_2 = await RawPacketRepository.create(b"packet_2", 1700000001)

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

        packet_id = await RawPacketRepository.create(b"test_packet", 1700000000)

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            msg_id = await create_message_from_decrypted(
                packet_id=packet_id,
                channel_key="ABC123DEF456",
                sender="Sender",
                message_text="Link test",
                timestamp=1700000000,
                received_at=1700000001,
            )

        # Verify packet is marked decrypted
        undecrypted = await RawPacketRepository.get_undecrypted(limit=100)
        packet_ids = [p[0] for p in undecrypted]
        assert packet_id not in packet_ids  # Should be marked as decrypted


class TestMessageBroadcastStructure:
    """Test that message broadcasts have the correct structure for frontend."""

    @pytest.mark.asyncio
    async def test_realtime_broadcast_includes_path_len(self, test_db, captured_broadcasts):
        """Real-time packet processing includes path_len in broadcast."""
        from app.packet_processor import process_raw_packet

        fixture = FIXTURES["channel_message"]
        packet_bytes = bytes.fromhex(fixture["raw_packet_hex"])
        channel_key_hex = fixture["channel_key_hex"].upper()

        await ChannelRepository.upsert(
            key=channel_key_hex,
            name=fixture["channel_name"],
            is_hashtag=True
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            await process_raw_packet(packet_bytes, timestamp=1700000000)

        message_broadcasts = [b for b in broadcasts if b["type"] == "message"]
        assert len(message_broadcasts) == 1

        broadcast = message_broadcasts[0]["data"]
        # Real-time processing extracts path_len from packet (flood packets have path_len=0)
        assert "path_len" in broadcast
        # The test packet is a flood packet, so path_len should be 0 or None depending on packet structure


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
            key=channel_key_hex,
            name=fixture["channel_name"],
            is_hashtag=True
        )

        broadcasts, mock_broadcast = captured_broadcasts

        with patch("app.packet_processor.broadcast_event", mock_broadcast):
            result = await process_raw_packet(packet_bytes, timestamp=1700000000)

        # Verify raw_packet broadcast was sent
        raw_broadcasts = [b for b in broadcasts if b["type"] == "raw_packet"]
        assert len(raw_broadcasts) == 1

        # Verify broadcast includes decryption info
        raw_broadcast = raw_broadcasts[0]["data"]
        assert raw_broadcast["decrypted"] is True
        assert "decrypted_info" in raw_broadcast
        assert raw_broadcast["decrypted_info"]["channel_name"] == fixture["channel_name"]
