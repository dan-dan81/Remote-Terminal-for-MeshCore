import logging
from hashlib import sha256

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.database import db
from app.decoder import extract_payload, try_decrypt_packet_with_channel_key
from app.packet_processor import create_message_from_decrypted
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

            msg_id = await create_message_from_decrypted(
                packet_id=packet_id,
                channel_key=channel_key_hex,
                sender=result.sender,
                message_text=result.message,
                timestamp=result.timestamp,
                received_at=packet_timestamp,  # Use original packet timestamp for correct ordering
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
    else:
        # Contact decryption not yet supported (requires Ed25519 shared secret)
        return DecryptResult(
            started=False,
            total_packets=0,
            message="Contact key decryption not yet supported",
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


class DedupProgress(BaseModel):
    total: int
    processed: int
    duplicates_removed: int
    in_progress: bool


class DedupResult(BaseModel):
    started: bool
    total_packets: int
    message: str


# Global state for tracking dedup progress
_dedup_progress: DedupProgress | None = None


async def _run_payload_dedup() -> None:
    """Background task to remove duplicate-payload packets."""
    global _dedup_progress

    # Get all undecrypted packets
    packets = await RawPacketRepository.get_all_undecrypted()
    total = len(packets)

    _dedup_progress = DedupProgress(
        total=total, processed=0, duplicates_removed=0, in_progress=True
    )

    logger.info("Starting payload deduplication of %d packets", total)

    # Group packets by payload hash
    payload_groups: dict[str, list[int]] = {}  # hash -> list of packet IDs

    for packet_id, packet_data, _timestamp in packets:
        payload = extract_payload(packet_data)
        if payload is None:
            continue

        payload_hash = sha256(payload).hexdigest()

        if payload_hash not in payload_groups:
            payload_groups[payload_hash] = []
        payload_groups[payload_hash].append(packet_id)

        _dedup_progress = DedupProgress(
            total=total,
            processed=_dedup_progress.processed + 1,
            duplicates_removed=_dedup_progress.duplicates_removed,
            in_progress=True,
        )

    # Delete duplicates (keep the first/oldest packet in each group)
    duplicates_removed = 0
    for packet_ids in payload_groups.values():
        if len(packet_ids) > 1:
            # Keep the first one, delete the rest
            ids_to_delete = packet_ids[1:]
            for packet_id in ids_to_delete:
                await db.conn.execute("DELETE FROM raw_packets WHERE id = ?", (packet_id,))
                duplicates_removed += 1

            _dedup_progress = DedupProgress(
                total=total,
                processed=_dedup_progress.processed,
                duplicates_removed=duplicates_removed,
                in_progress=True,
            )

    await db.conn.commit()

    # Run VACUUM to reclaim space (must be outside transaction, use executescript)
    await db.conn.executescript("VACUUM;")

    _dedup_progress = DedupProgress(
        total=total,
        processed=total,
        duplicates_removed=duplicates_removed,
        in_progress=False,
    )

    logger.info("Payload deduplication complete: removed %d duplicates", duplicates_removed)


@router.post("/dedup", response_model=DedupResult)
async def deduplicate_packets(background_tasks: BackgroundTasks) -> DedupResult:
    """
    Remove packets with duplicate payloads (keeps one copy of each unique payload).

    This operation runs in the background and may take a long time for large databases.
    Use GET /packets/dedup/progress to check status.

    Note: This only affects undecrypted packets. Packets that arrive through different
    repeater paths have different full data but the same payload - this removes those duplicates.
    """
    global _dedup_progress

    # Check if dedup is already in progress
    if _dedup_progress and _dedup_progress.in_progress:
        return DedupResult(
            started=False,
            total_packets=_dedup_progress.total,
            message=f"Deduplication already in progress: {_dedup_progress.processed}/{_dedup_progress.total}",
        )

    # Get count of undecrypted packets
    count = await RawPacketRepository.get_undecrypted_count()
    if count == 0:
        return DedupResult(
            started=False, total_packets=0, message="No undecrypted packets to process"
        )

    # Start background dedup
    background_tasks.add_task(_run_payload_dedup)

    return DedupResult(
        started=True,
        total_packets=count,
        message=f"Started deduplication of {count} packets in background. This may take a while.",
    )


@router.get("/dedup/progress", response_model=DedupProgress | None)
async def get_dedup_progress() -> DedupProgress | None:
    """Get the current progress of payload deduplication."""
    return _dedup_progress
