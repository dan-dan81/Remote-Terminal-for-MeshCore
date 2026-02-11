import asyncio
import logging
import time
from typing import TYPE_CHECKING

from meshcore import EventType

from app.models import CONTACT_TYPE_REPEATER, Contact
from app.packet_processor import process_raw_packet
from app.repository import ContactRepository, MessageRepository
from app.websocket import broadcast_event

if TYPE_CHECKING:
    from meshcore.events import Event, Subscription

logger = logging.getLogger(__name__)

# Track active subscriptions so we can unsubscribe before re-registering
# This prevents handler duplication after reconnects
_active_subscriptions: list["Subscription"] = []


# Track pending ACKs: expected_ack_code -> (message_id, timestamp, timeout_ms)
_pending_acks: dict[str, tuple[int, float, int]] = {}


def track_pending_ack(expected_ack: str, message_id: int, timeout_ms: int) -> None:
    """Track a pending ACK for a direct message."""
    _pending_acks[expected_ack] = (message_id, time.time(), timeout_ms)
    logger.debug(
        "Tracking pending ACK %s for message %d (timeout %dms)",
        expected_ack,
        message_id,
        timeout_ms,
    )


def _cleanup_expired_acks() -> None:
    """Remove expired pending ACKs."""
    now = time.time()
    expired = []
    for code, (_msg_id, created_at, timeout_ms) in _pending_acks.items():
        if now - created_at > (timeout_ms / 1000) * 2:  # 2x timeout as buffer
            expired.append(code)
    for code in expired:
        del _pending_acks[code]
        logger.debug("Expired pending ACK %s", code)


async def on_contact_message(event: "Event") -> None:
    """Handle incoming direct messages from MeshCore library.

    NOTE: DMs are primarily handled by the packet processor via RX_LOG_DATA,
    which decrypts using our exported private key. This handler exists as a
    fallback for cases where:
    1. The private key couldn't be exported (firmware without ENABLE_PRIVATE_KEY_EXPORT)
    2. The packet processor couldn't match the sender to a known contact

    The packet processor handles: decryption, storage, broadcast, bot trigger.
    This handler only stores if the packet processor didn't already handle it
    (detected via INSERT OR IGNORE returning None for duplicates).
    """
    payload = event.payload

    # Skip CLI command responses (txt_type=1) - these are handled by the command endpoint
    txt_type = payload.get("txt_type", 0)
    if txt_type == 1:
        logger.debug("Skipping CLI response from %s (txt_type=1)", payload.get("pubkey_prefix"))
        return

    # Get full public key if available, otherwise use prefix
    sender_pubkey = payload.get("public_key") or payload.get("pubkey_prefix", "")
    received_at = int(time.time())

    # Look up contact from database - use prefix lookup only if needed
    # (get_by_key_or_prefix does exact match first, then prefix fallback)
    contact = await ContactRepository.get_by_key_or_prefix(sender_pubkey)
    if contact:
        sender_pubkey = contact.public_key.lower()

        # Promote any prefix-stored messages to this full key
        await MessageRepository.claim_prefix_messages(sender_pubkey)

        # Skip messages from repeaters - they only send CLI responses, not chat messages.
        # CLI responses are handled by the command endpoint and txt_type filter above.
        if contact.type == CONTACT_TYPE_REPEATER:
            logger.debug(
                "Skipping message from repeater %s (not stored in chat history)",
                sender_pubkey[:12],
            )
            return

    # Try to create message - INSERT OR IGNORE handles duplicates atomically
    # If the packet processor already stored this message, this returns None
    msg_id = await MessageRepository.create(
        msg_type="PRIV",
        text=payload.get("text", ""),
        conversation_key=sender_pubkey,
        sender_timestamp=payload.get("sender_timestamp") or received_at,
        received_at=received_at,
        path=payload.get("path"),
        txt_type=txt_type,
        signature=payload.get("signature"),
    )

    if msg_id is None:
        # Already handled by packet processor (or exact duplicate) - nothing more to do
        logger.debug("DM from %s already processed by packet processor", sender_pubkey[:12])
        return

    # If we get here, the packet processor didn't handle this message
    # (likely because private key export is not available)
    logger.debug("DM from %s handled by event handler (fallback path)", sender_pubkey[:12])

    # Build paths array for broadcast
    path = payload.get("path")
    paths = [{"path": path or "", "received_at": received_at}] if path is not None else None

    # Broadcast the new message
    broadcast_event(
        "message",
        {
            "id": msg_id,
            "type": "PRIV",
            "conversation_key": sender_pubkey,
            "text": payload.get("text", ""),
            "sender_timestamp": payload.get("sender_timestamp"),
            "received_at": received_at,
            "paths": paths,
            "txt_type": txt_type,
            "signature": payload.get("signature"),
            "outgoing": False,
            "acked": 0,
        },
    )

    # Update contact last_contacted (contact was already fetched above)
    if contact:
        await ContactRepository.update_last_contacted(sender_pubkey, received_at)

    # Run bot if enabled
    from app.bot import run_bot_for_message

    asyncio.create_task(
        run_bot_for_message(
            sender_name=contact.name if contact else None,
            sender_key=sender_pubkey,
            message_text=payload.get("text", ""),
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=payload.get("sender_timestamp"),
            path=payload.get("path"),
            is_outgoing=False,
        )
    )


async def on_rx_log_data(event: "Event") -> None:
    """Store raw RF packet data and process via centralized packet processor.

    This is the unified entry point for all RF packets. The packet processor
    handles channel messages (GROUP_TEXT) and advertisements (ADVERT).
    """
    payload = event.payload
    logger.debug("Received RX log data packet")

    if "payload" not in payload:
        logger.warning("RX_LOG_DATA event missing 'payload' field")
        return

    raw_hex = payload["payload"]
    raw_bytes = bytes.fromhex(raw_hex)

    await process_raw_packet(
        raw_bytes=raw_bytes,
        snr=payload.get("snr"),
        rssi=payload.get("rssi"),
    )


async def on_path_update(event: "Event") -> None:
    """Handle path update events."""
    payload = event.payload
    logger.debug("Path update for %s", payload.get("pubkey_prefix"))

    pubkey_prefix = payload.get("pubkey_prefix", "")
    path = payload.get("path", "")
    path_len = payload.get("path_len", -1)

    existing = await ContactRepository.get_by_key_prefix(pubkey_prefix)
    if existing:
        await ContactRepository.update_path(existing.public_key, path, path_len)


async def on_new_contact(event: "Event") -> None:
    """Handle new contact from radio's internal contact database.

    This is different from RF advertisements - these are contacts synced
    from the radio's stored contact list.
    """
    payload = event.payload
    public_key = payload.get("public_key", "")

    if not public_key:
        logger.warning("Received new contact event with no public_key, skipping")
        return

    logger.debug("New contact: %s", public_key[:12])

    contact_data = {
        **Contact.from_radio_dict(public_key, payload, on_radio=True),
        "last_seen": int(time.time()),
    }
    await ContactRepository.upsert(contact_data)

    broadcast_event("contact", contact_data)


async def on_ack(event: "Event") -> None:
    """Handle ACK events for direct messages."""
    payload = event.payload
    ack_code = payload.get("code", "")

    if not ack_code:
        logger.debug("Received ACK with no code")
        return

    logger.debug("Received ACK with code %s", ack_code)

    _cleanup_expired_acks()

    if ack_code in _pending_acks:
        message_id, _, _ = _pending_acks.pop(ack_code)
        logger.info("ACK received for message %d", message_id)

        ack_count = await MessageRepository.increment_ack_count(message_id)
        broadcast_event("message_acked", {"message_id": message_id, "ack_count": ack_count})
    else:
        logger.debug("ACK code %s does not match any pending messages", ack_code)


def register_event_handlers(meshcore) -> None:
    """Register event handlers with the MeshCore instance.

    Note: CHANNEL_MSG_RECV and ADVERTISEMENT events are NOT subscribed.
    These are handled by the packet processor via RX_LOG_DATA to avoid
    duplicate processing and ensure consistent handling.

    This function is safe to call multiple times (e.g., after reconnect).
    Existing handlers are unsubscribed before new ones are registered.
    """
    global _active_subscriptions

    # Unsubscribe existing handlers to prevent duplication after reconnects.
    # Try/except handles the case where the old dispatcher is in a bad state
    # (e.g., after reconnect with a new MeshCore instance).
    for sub in _active_subscriptions:
        try:
            sub.unsubscribe()
        except Exception:
            pass  # Old dispatcher may be gone, that's fine
    _active_subscriptions.clear()

    # Register handlers and track subscriptions
    _active_subscriptions.append(meshcore.subscribe(EventType.CONTACT_MSG_RECV, on_contact_message))
    _active_subscriptions.append(meshcore.subscribe(EventType.RX_LOG_DATA, on_rx_log_data))
    _active_subscriptions.append(meshcore.subscribe(EventType.PATH_UPDATE, on_path_update))
    _active_subscriptions.append(meshcore.subscribe(EventType.NEW_CONTACT, on_new_contact))
    _active_subscriptions.append(meshcore.subscribe(EventType.ACK, on_ack))
    logger.info("Event handlers registered")
