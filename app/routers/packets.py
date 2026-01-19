import logging
from hashlib import sha256

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.database import db
from app.decoder import (
    derive_public_key,
    parse_packet,
    try_decrypt_dm,
    try_decrypt_packet_with_channel_key,
)
from app.packet_processor import create_dm_message_from_decrypted, create_message_from_decrypted
from app.repository import RawPacketRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/packets", tags=["packets"])


class DecryptRequest(BaseModel):
    key_type: str = Field(description="Type of key: 'channel' or 'contact'")
    channel_key: str | None = Field(
        default=None, description="Channel key as hex (16 bytes = 32 chars)"
    )
    channel_name: str | None = Field(
        default=None, description="Channel name (for hashtag channels, key derived from name)"
    )
    # Fields for contact (DM) decryption
    private_key: str | None = Field(
        default=None,
        description="Our private key as hex (64 bytes = 128 chars, Ed25519 seed + pubkey)",
    )
    contact_public_key: str | None = Field(
        default=None, description="Contact's public key as hex (32 bytes = 64 chars)"
    )


class DecryptResult(BaseModel):
    started: bool
    total_packets: int
    message: str


class DecryptProgress(BaseModel):
    total: int
    processed: int
    decrypted: int
    in_progress: bool


# Global state for tracking decryption progress
_decrypt_progress: DecryptProgress | None = None


async def _run_historical_decryption(channel_key_bytes: bytes, channel_key_hex: str) -> None:
    """Background task to decrypt historical packets with a channel key."""
    global _decrypt_progress

    packets = await RawPacketRepository.get_all_undecrypted()
    total = len(packets)
    processed = 0
    decrypted_count = 0

    _decrypt_progress = DecryptProgress(total=total, processed=0, decrypted=0, in_progress=True)

    logger.info("Starting historical decryption of %d packets", total)

    for packet_id, packet_data, packet_timestamp in packets:
        result = try_decrypt_packet_with_channel_key(packet_data, channel_key_bytes)

        if result is not None:
            # Successfully decrypted - use shared logic to store message
            logger.debug(
                "Decrypted packet %d: sender=%s, message=%s",
                packet_id,
                result.sender,
                result.message[:50] if result.message else "",
            )

            # Extract path from the raw packet for storage
            packet_info = parse_packet(packet_data)
            path_hex = packet_info.path.hex() if packet_info else None

            msg_id = await create_message_from_decrypted(
                packet_id=packet_id,
                channel_key=channel_key_hex,
                sender=result.sender,
                message_text=result.message,
                timestamp=result.timestamp,
                received_at=packet_timestamp,  # Use original packet timestamp for correct ordering
                path=path_hex,
            )

            if msg_id is not None:
                decrypted_count += 1

        processed += 1
        _decrypt_progress = DecryptProgress(
            total=total, processed=processed, decrypted=decrypted_count, in_progress=True
        )

    _decrypt_progress = DecryptProgress(
        total=total, processed=processed, decrypted=decrypted_count, in_progress=False
    )

    logger.info("Historical decryption complete: %d/%d packets decrypted", decrypted_count, total)


async def _run_historical_dm_decryption(
    private_key_bytes: bytes,
    contact_public_key_bytes: bytes,
    contact_public_key_hex: str,
) -> None:
    """Background task to decrypt historical DM packets with contact's key."""
    global _decrypt_progress

    # Get only TEXT_MESSAGE packets (undecrypted)
    packets = await RawPacketRepository.get_undecrypted_text_messages()
    total = len(packets)
    processed = 0
    decrypted_count = 0

    _decrypt_progress = DecryptProgress(total=total, processed=0, decrypted=0, in_progress=True)

    logger.info("Starting historical DM decryption of %d TEXT_MESSAGE packets", total)

    # Derive our public key from the private key using Ed25519 scalar multiplication.
    # Note: MeshCore stores the scalar directly (not a seed), so we use noclamp variant.
    # See derive_public_key() for details on the MeshCore key format.
    our_public_key_bytes = derive_public_key(private_key_bytes)

    for packet_id, packet_data, packet_timestamp in packets:
        # Don't pass our_public_key - we want to decrypt both incoming AND outgoing messages.
        # The our_public_key filter in try_decrypt_dm only matches incoming (dest_hash == us),
        # which would skip outgoing messages (where dest_hash == contact).
        result = try_decrypt_dm(
            packet_data,
            private_key_bytes,
            contact_public_key_bytes,
            our_public_key=None,
        )

        if result is not None:
            # Successfully decrypted - determine if inbound or outbound by checking src_hash
            src_hash = result.src_hash.lower()
            our_first_byte = format(our_public_key_bytes[0], "02x").lower()
            outgoing = src_hash == our_first_byte

            logger.debug(
                "Decrypted DM packet %d: message=%s (outgoing=%s)",
                packet_id,
                result.message[:50] if result.message else "",
                outgoing,
            )

            # Extract path from the raw packet for storage
            packet_info = parse_packet(packet_data)
            path_hex = packet_info.path.hex() if packet_info else None

            msg_id = await create_dm_message_from_decrypted(
                packet_id=packet_id,
                decrypted=result,
                their_public_key=contact_public_key_hex,
                our_public_key=our_public_key_bytes.hex(),
                received_at=packet_timestamp,
                path=path_hex,
                outgoing=outgoing,
            )

            if msg_id is not None:
                decrypted_count += 1

        processed += 1
        _decrypt_progress = DecryptProgress(
            total=total, processed=processed, decrypted=decrypted_count, in_progress=True
        )

    _decrypt_progress = DecryptProgress(
        total=total, processed=processed, decrypted=decrypted_count, in_progress=False
    )

    logger.info(
        "Historical DM decryption complete: %d/%d packets decrypted", decrypted_count, total
    )


@router.get("/undecrypted/count")
async def get_undecrypted_count() -> dict:
    """Get the count of undecrypted packets."""
    count = await RawPacketRepository.get_undecrypted_count()
    return {"count": count}


@router.post("/decrypt/historical", response_model=DecryptResult)
async def decrypt_historical_packets(
    request: DecryptRequest, background_tasks: BackgroundTasks
) -> DecryptResult:
    """
    Attempt to decrypt historical packets with the provided key.
    Runs in the background to avoid blocking.
    """
    global _decrypt_progress

    # Check if decryption is already in progress
    if _decrypt_progress and _decrypt_progress.in_progress:
        return DecryptResult(
            started=False,
            total_packets=_decrypt_progress.total,
            message=f"Decryption already in progress: {_decrypt_progress.processed}/{_decrypt_progress.total}",
        )

    # Determine the channel key
    channel_key_bytes: bytes | None = None
    channel_key_hex: str | None = None

    if request.key_type == "channel":
        if request.channel_key:
            # Direct key provided
            try:
                channel_key_bytes = bytes.fromhex(request.channel_key)
                if len(channel_key_bytes) != 16:
                    return DecryptResult(
                        started=False,
                        total_packets=0,
                        message="Channel key must be 16 bytes (32 hex chars)",
                    )
                channel_key_hex = request.channel_key.upper()
            except ValueError:
                return DecryptResult(
                    started=False,
                    total_packets=0,
                    message="Invalid hex string for channel key",
                )
        elif request.channel_name:
            # Derive key from channel name (hashtag channel)
            channel_key_bytes = sha256(request.channel_name.encode("utf-8")).digest()[:16]
            channel_key_hex = channel_key_bytes.hex().upper()
        else:
            return DecryptResult(
                started=False,
                total_packets=0,
                message="Must provide channel_key or channel_name",
            )
    elif request.key_type == "contact":
        # Validate required fields for contact decryption
        if not request.private_key:
            return DecryptResult(
                started=False,
                total_packets=0,
                message="Must provide private_key for contact decryption",
            )
        if not request.contact_public_key:
            return DecryptResult(
                started=False,
                total_packets=0,
                message="Must provide contact_public_key for contact decryption",
            )

        # Parse private key
        try:
            private_key_bytes = bytes.fromhex(request.private_key)
            if len(private_key_bytes) != 64:
                return DecryptResult(
                    started=False,
                    total_packets=0,
                    message="Private key must be 64 bytes (128 hex chars)",
                )
        except ValueError:
            return DecryptResult(
                started=False,
                total_packets=0,
                message="Invalid hex string for private key",
            )

        # Parse contact public key
        try:
            contact_public_key_bytes = bytes.fromhex(request.contact_public_key)
            if len(contact_public_key_bytes) != 32:
                return DecryptResult(
                    started=False,
                    total_packets=0,
                    message="Contact public key must be 32 bytes (64 hex chars)",
                )
            contact_public_key_hex = request.contact_public_key.lower()
        except ValueError:
            return DecryptResult(
                started=False,
                total_packets=0,
                message="Invalid hex string for contact public key",
            )

        # Get count of undecrypted TEXT_MESSAGE packets
        packets = await RawPacketRepository.get_undecrypted_text_messages()
        count = len(packets)
        if count == 0:
            return DecryptResult(
                started=False,
                total_packets=0,
                message="No undecrypted TEXT_MESSAGE packets to process",
            )

        # Start background decryption
        background_tasks.add_task(
            _run_historical_dm_decryption,
            private_key_bytes,
            contact_public_key_bytes,
            contact_public_key_hex,
        )

        return DecryptResult(
            started=True,
            total_packets=count,
            message=f"Started DM decryption of {count} TEXT_MESSAGE packets in background",
        )
    else:
        return DecryptResult(
            started=False,
            total_packets=0,
            message="key_type must be 'channel' or 'contact'",
        )

    # Get count of undecrypted packets
    count = await RawPacketRepository.get_undecrypted_count()
    if count == 0:
        return DecryptResult(
            started=False, total_packets=0, message="No undecrypted packets to process"
        )

    # Start background decryption
    background_tasks.add_task(_run_historical_decryption, channel_key_bytes, channel_key_hex)

    return DecryptResult(
        started=True,
        total_packets=count,
        message=f"Started decryption of {count} packets in background",
    )


@router.get("/decrypt/progress", response_model=DecryptProgress | None)
async def get_decrypt_progress() -> DecryptProgress | None:
    """Get the current progress of historical decryption."""
    return _decrypt_progress


class MaintenanceRequest(BaseModel):
    prune_undecrypted_days: int = Field(
        ge=1, description="Delete undecrypted packets older than this many days"
    )


class MaintenanceResult(BaseModel):
    packets_deleted: int
    vacuumed: bool


@router.post("/maintenance", response_model=MaintenanceResult)
async def run_maintenance(request: MaintenanceRequest) -> MaintenanceResult:
    """
    Clean up old undecrypted packets and reclaim disk space.

    - Deletes undecrypted packets older than the specified number of days
    - Runs VACUUM to reclaim disk space
    """
    logger.info(
        "Running maintenance: pruning packets older than %d days", request.prune_undecrypted_days
    )

    # Prune old undecrypted packets
    deleted = await RawPacketRepository.prune_old_undecrypted(request.prune_undecrypted_days)
    logger.info("Deleted %d old undecrypted packets", deleted)

    # Run VACUUM to reclaim space (must be outside transaction, use executescript)
    await db.conn.executescript("VACUUM;")
    logger.info("Database vacuumed")

    return MaintenanceResult(packets_deleted=deleted, vacuumed=True)
