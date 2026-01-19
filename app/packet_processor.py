"""
Centralized packet processing for MeshCore messages.

This module handles:
- Storing raw packets
- Decrypting channel messages (GroupText) with stored channel keys
- Decrypting direct messages with stored contact keys (if private key available)
- Creating message entries for successfully decrypted packets
- Broadcasting updates via WebSocket

This is the primary path for message processing when channel/contact keys
are offloaded from the radio to the server.
"""

import asyncio
import logging
import time

from app.decoder import (
    PacketInfo,
    PayloadType,
    parse_advertisement,
    parse_packet,
    try_decrypt_packet_with_channel_key,
)
from app.models import CONTACT_TYPE_REPEATER, RawPacketBroadcast, RawPacketDecryptedInfo
from app.repository import (
    ChannelRepository,
    ContactRepository,
    MessageRepository,
    RawPacketRepository,
)
from app.websocket import broadcast_event

logger = logging.getLogger(__name__)


async def create_message_from_decrypted(
    packet_id: int,
    channel_key: str,
    sender: str | None,
    message_text: str,
    timestamp: int,
    received_at: int | None = None,
    path: str | None = None,
) -> int | None:
    """Create a message record from decrypted channel packet content.

    This is the shared logic for storing decrypted channel messages,
    used by both real-time packet processing and historical decryption.

    Args:
        packet_id: ID of the raw packet being processed
        channel_key: Hex string channel key
        sender: Sender name (will be prefixed to message) or None
        message_text: The decrypted message content
        timestamp: Sender timestamp from the packet
        received_at: When the packet was received (defaults to now)
        path: Hex-encoded routing path (None for historical decryption)

    Returns the message ID if created, None if duplicate.
    """
    received = received_at or int(time.time())

    # Format the message text with sender prefix if present
    text = f"{sender}: {message_text}" if sender else message_text

    # Normalize channel key to uppercase for consistency
    channel_key_normalized = channel_key.upper()

    # Try to create message - INSERT OR IGNORE handles duplicates atomically
    msg_id = await MessageRepository.create(
        msg_type="CHAN",
        text=text,
        conversation_key=channel_key_normalized,
        sender_timestamp=timestamp,
        received_at=received,
        path=path,
    )

    if msg_id is None:
        # Duplicate message detected - this happens when:
        # 1. Our own outgoing message echoes back (flood routing)
        # 2. Same message arrives via multiple paths before first is committed
        # In either case, add the path to the existing message.
        existing_msg = await MessageRepository.get_by_content(
            msg_type="CHAN",
            conversation_key=channel_key_normalized,
            text=text,
            sender_timestamp=timestamp,
        )
        if not existing_msg:
            logger.warning(
                "Duplicate message for channel %s but couldn't find existing",
                channel_key_normalized[:8],
            )
            return None

        logger.debug(
            "Duplicate message for channel %s (msg_id=%d, outgoing=%s) - adding path",
            channel_key_normalized[:8],
            existing_msg.id,
            existing_msg.outgoing,
        )

        # Add path if provided
        if path is not None:
            paths = await MessageRepository.add_path(existing_msg.id, path, received)
        else:
            # Get current paths for broadcast
            paths = existing_msg.paths or []

        # Increment ack count for outgoing messages (echo confirmation)
        if existing_msg.outgoing:
            ack_count = await MessageRepository.increment_ack_count(existing_msg.id)
        else:
            ack_count = await MessageRepository.get_ack_count(existing_msg.id)

        # Broadcast updated paths
        broadcast_event(
            "message_acked",
            {
                "message_id": existing_msg.id,
                "ack_count": ack_count,
                "paths": [p.model_dump() for p in paths] if paths else [],
            },
        )

        # Mark this packet as decrypted
        await RawPacketRepository.mark_decrypted(packet_id, existing_msg.id)

        return None

    logger.info("Stored channel message %d for channel %s", msg_id, channel_key_normalized[:8])

    # Mark the raw packet as decrypted
    await RawPacketRepository.mark_decrypted(packet_id, msg_id)

    # Build paths array for broadcast
    # Use "is not None" to include empty string (direct/0-hop messages)
    paths = [{"path": path or "", "received_at": received}] if path is not None else None

    # Broadcast new message to connected clients
    broadcast_event(
        "message",
        {
            "id": msg_id,
            "type": "CHAN",
            "conversation_key": channel_key_normalized,
            "text": text,
            "sender_timestamp": timestamp,
            "received_at": received,
            "paths": paths,
            "txt_type": 0,
            "signature": None,
            "outgoing": False,
            "acked": 0,
        },
    )

    return msg_id


async def process_raw_packet(
    raw_bytes: bytes,
    timestamp: int | None = None,
    snr: float | None = None,
    rssi: int | None = None,
) -> dict:
    """
    Process an incoming raw packet.

    This is the main entry point for all incoming RF packets.

    Note: Packets are deduplicated by payload hash in the database. If we receive
    a duplicate packet (same payload, different path), we still broadcast it to
    the frontend (for the real-time packet feed) but skip decryption processing
    since the original packet was already processed.
    """
    ts = timestamp or int(time.time())

    packet_id, is_new_packet = await RawPacketRepository.create(raw_bytes, ts)
    raw_hex = raw_bytes.hex()

    # Parse packet to get type
    packet_info = parse_packet(raw_bytes)
    payload_type = packet_info.payload_type if packet_info else None
    payload_type_name = payload_type.name if payload_type else "Unknown"

    # Log packet arrival at debug level
    path_hex = packet_info.path.hex() if packet_info and packet_info.path else ""
    logger.debug(
        "Packet received: type=%s, is_new=%s, packet_id=%d, path='%s'",
        payload_type_name,
        is_new_packet,
        packet_id,
        path_hex[:8] if path_hex else "(direct)",
    )

    result = {
        "packet_id": packet_id,
        "timestamp": ts,
        "raw_hex": raw_hex,
        "payload_type": payload_type_name,
        "snr": snr,
        "rssi": rssi,
        "decrypted": False,
        "message_id": None,
        "channel_name": None,
        "sender": None,
    }

    # Process packets based on payload type
    # For GROUP_TEXT, we always try to decrypt even for duplicate packets - the message
    # deduplication in create_message_from_decrypted handles adding paths to existing messages.
    # This is more reliable than trying to look up the message via raw packet linking.
    if payload_type == PayloadType.GROUP_TEXT:
        decrypt_result = await _process_group_text(raw_bytes, packet_id, ts, packet_info)
        if decrypt_result:
            result.update(decrypt_result)

    elif payload_type == PayloadType.ADVERT and is_new_packet:
        # Only process new advertisements (duplicates don't add value)
        await _process_advertisement(raw_bytes, ts, packet_info)

    # TODO: Add TEXT_MESSAGE (direct message) decryption when private key is available
    # elif payload_type == PayloadType.TEXT_MESSAGE:
    #     decrypt_result = await _process_direct_message(raw_bytes, packet_id, ts, packet_info)
    #     if decrypt_result:
    #         result.update(decrypt_result)

    # Always broadcast raw packet for the packet feed UI (even duplicates)
    # This enables the frontend cracker to see all incoming packets in real-time
    broadcast_payload = RawPacketBroadcast(
        id=packet_id,
        timestamp=ts,
        data=raw_hex,
        payload_type=payload_type_name,
        snr=snr,
        rssi=rssi,
        decrypted=result["decrypted"],
        decrypted_info=RawPacketDecryptedInfo(
            channel_name=result["channel_name"],
            sender=result["sender"],
        )
        if result["decrypted"]
        else None,
    )
    broadcast_event("raw_packet", broadcast_payload.model_dump())

    return result


async def _process_group_text(
    raw_bytes: bytes,
    packet_id: int,
    timestamp: int,
    packet_info: PacketInfo | None,
) -> dict | None:
    """
    Process a GroupText (channel message) packet.

    Tries all known channel keys to decrypt.
    Creates a message entry if successful (or adds path to existing if duplicate).
    """
    # Try to decrypt with all known channel keys
    channels = await ChannelRepository.get_all()

    for channel in channels:
        # Convert hex key to bytes for decryption
        try:
            channel_key_bytes = bytes.fromhex(channel.key)
        except ValueError:
            continue

        decrypted = try_decrypt_packet_with_channel_key(raw_bytes, channel_key_bytes)
        if not decrypted:
            continue

        # Successfully decrypted!
        logger.debug("Decrypted GroupText for channel %s: %s", channel.name, decrypted.message[:50])

        # Create message (or add path to existing if duplicate)
        # This handles both new messages and echoes of our own outgoing messages
        msg_id = await create_message_from_decrypted(
            packet_id=packet_id,
            channel_key=channel.key,
            sender=decrypted.sender,
            message_text=decrypted.message,
            timestamp=decrypted.timestamp,
            received_at=timestamp,
            path=packet_info.path.hex() if packet_info else None,
        )

        return {
            "decrypted": True,
            "channel_name": channel.name,
            "sender": decrypted.sender,
            "message_id": msg_id,  # None if duplicate, msg_id if new
        }

    # Couldn't decrypt with any known key
    return None


async def _process_advertisement(
    raw_bytes: bytes,
    timestamp: int,
    packet_info: PacketInfo | None = None,
) -> None:
    """
    Process an advertisement packet.

    Extracts contact info and updates the database/broadcasts to clients.
    For non-repeater contacts, triggers sync of recent contacts to radio for DM ACK support.
    """
    # Parse packet to get path info if not already provided
    if packet_info is None:
        packet_info = parse_packet(raw_bytes)
    if packet_info is None:
        logger.debug("Failed to parse advertisement packet")
        return

    advert = parse_advertisement(packet_info.payload)
    if not advert:
        logger.debug("Failed to parse advertisement payload")
        return

    # Extract path info from packet
    new_path_len = packet_info.path_length
    new_path_hex = packet_info.path.hex() if packet_info.path else ""

    # Try to find existing contact
    existing = await ContactRepository.get_by_key(advert.public_key)

    # Determine which path to use: keep shorter path if heard recently (within 60s)
    # This handles advertisement echoes through different routes
    PATH_FRESHNESS_SECONDS = 60
    use_existing_path = False

    if existing and existing.last_seen:
        path_age = timestamp - existing.last_seen
        existing_path_len = existing.last_path_len if existing.last_path_len >= 0 else float("inf")

        # Keep existing path if it's fresh and shorter (or equal)
        if path_age <= PATH_FRESHNESS_SECONDS and existing_path_len <= new_path_len:
            use_existing_path = True
            logger.debug(
                "Keeping existing shorter path for %s (existing=%d, new=%d, age=%ds)",
                advert.public_key[:12],
                existing_path_len,
                new_path_len,
                path_age,
            )

    if use_existing_path:
        assert existing is not None  # Guaranteed by the conditions that set use_existing_path
        path_len = existing.last_path_len if existing.last_path_len is not None else -1
        path_hex = existing.last_path or ""
    else:
        path_len = new_path_len
        path_hex = new_path_hex

    logger.debug(
        "Parsed advertisement from %s: %s (role=%d, lat=%s, lon=%s, path_len=%d)",
        advert.public_key[:12],
        advert.name,
        advert.device_role,
        advert.lat,
        advert.lon,
        path_len,
    )

    # Use device_role from advertisement for contact type (1=Chat, 2=Repeater, 3=Room, 4=Sensor)
    # Use advert.timestamp for last_advert (sender's timestamp), receive timestamp for last_seen
    contact_type = (
        advert.device_role if advert.device_role > 0 else (existing.type if existing else 0)
    )

    contact_data = {
        "public_key": advert.public_key,
        "name": advert.name,
        "type": contact_type,
        "lat": advert.lat,
        "lon": advert.lon,
        "last_advert": advert.timestamp if advert.timestamp > 0 else timestamp,
        "last_seen": timestamp,
        "last_path": path_hex,
        "last_path_len": path_len,
    }

    await ContactRepository.upsert(contact_data)

    # Broadcast contact update to connected clients
    broadcast_event(
        "contact",
        {
            "public_key": advert.public_key,
            "name": advert.name,
            "type": contact_type,
            "flags": existing.flags if existing else 0,
            "last_path": path_hex,
            "last_path_len": path_len,
            "last_advert": advert.timestamp if advert.timestamp > 0 else timestamp,
            "lat": advert.lat,
            "lon": advert.lon,
            "last_seen": timestamp,
            "on_radio": existing.on_radio if existing else False,
        },
    )

    # If this is not a repeater, trigger recent contacts sync to radio
    # This ensures we can auto-ACK DMs from recent contacts
    if contact_type != CONTACT_TYPE_REPEATER:
        # Import here to avoid circular import
        from app.radio_sync import sync_recent_contacts_to_radio

        asyncio.create_task(sync_recent_contacts_to_radio())
