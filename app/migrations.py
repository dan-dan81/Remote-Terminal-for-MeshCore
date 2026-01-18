"""
Database migrations using SQLite's user_version pragma.

Migrations run automatically on startup. The user_version pragma tracks
which migrations have been applied (defaults to 0 for existing databases).

This approach is safe for existing users - their databases have user_version=0,
so all migrations run in order on first startup after upgrade.
"""

import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def get_version(conn: aiosqlite.Connection) -> int:
    """Get current schema version from SQLite user_version pragma."""
    cursor = await conn.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    return row[0] if row else 0


async def set_version(conn: aiosqlite.Connection, version: int) -> None:
    """Set schema version using SQLite user_version pragma."""
    await conn.execute(f"PRAGMA user_version = {version}")


async def run_migrations(conn: aiosqlite.Connection) -> int:
    """
    Run all pending migrations.

    Returns the number of migrations applied.
    """
    version = await get_version(conn)
    applied = 0

    # Migration 1: Add last_read_at columns for server-side read tracking
    if version < 1:
        logger.info("Applying migration 1: add last_read_at columns")
        await _migrate_001_add_last_read_at(conn)
        await set_version(conn, 1)
        applied += 1

    # Migration 2: Drop unused decrypt_attempts and last_attempt columns
    if version < 2:
        logger.info("Applying migration 2: drop decrypt_attempts and last_attempt columns")
        await _migrate_002_drop_decrypt_attempt_columns(conn)
        await set_version(conn, 2)
        applied += 1

    # Migration 3: Drop decrypted column (redundant with message_id), update index
    if version < 3:
        logger.info("Applying migration 3: drop decrypted column, add message_id index")
        await _migrate_003_drop_decrypted_column(conn)
        await set_version(conn, 3)
        applied += 1

    if applied > 0:
        logger.info(
            "Applied %d migration(s), schema now at version %d", applied, await get_version(conn)
        )
    else:
        logger.debug("Schema up to date at version %d", version)

    return applied


async def _migrate_001_add_last_read_at(conn: aiosqlite.Connection) -> None:
    """
    Add last_read_at column to contacts and channels tables.

    This enables server-side read state tracking, replacing the localStorage
    approach for consistent read state across devices.

    ALTER TABLE ADD COLUMN is safe - it preserves existing data and handles
    the "column already exists" case gracefully.
    """
    # Add to contacts table
    try:
        await conn.execute("ALTER TABLE contacts ADD COLUMN last_read_at INTEGER")
        logger.debug("Added last_read_at to contacts table")
    except aiosqlite.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            logger.debug("contacts.last_read_at already exists, skipping")
        else:
            raise

    # Add to channels table
    try:
        await conn.execute("ALTER TABLE channels ADD COLUMN last_read_at INTEGER")
        logger.debug("Added last_read_at to channels table")
    except aiosqlite.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            logger.debug("channels.last_read_at already exists, skipping")
        else:
            raise

    await conn.commit()


async def _migrate_002_drop_decrypt_attempt_columns(conn: aiosqlite.Connection) -> None:
    """
    Drop unused decrypt_attempts and last_attempt columns from raw_packets.

    These columns were added for a retry-limiting feature that was never implemented.
    They are written to but never read, so we can safely remove them.

    SQLite 3.35.0+ supports ALTER TABLE DROP COLUMN. For older versions,
    we silently skip (the columns will remain but are harmless).
    """
    for column in ["decrypt_attempts", "last_attempt"]:
        try:
            await conn.execute(f"ALTER TABLE raw_packets DROP COLUMN {column}")
            logger.debug("Dropped %s from raw_packets table", column)
        except aiosqlite.OperationalError as e:
            error_msg = str(e).lower()
            if "no such column" in error_msg:
                logger.debug("raw_packets.%s already dropped, skipping", column)
            elif "syntax error" in error_msg or "drop column" in error_msg:
                # SQLite version doesn't support DROP COLUMN - harmless, column stays
                logger.debug("SQLite doesn't support DROP COLUMN, %s column will remain", column)
            else:
                raise

    await conn.commit()


async def _migrate_003_drop_decrypted_column(conn: aiosqlite.Connection) -> None:
    """
    Drop the decrypted column and update indexes.

    The decrypted column is redundant with message_id - a packet is decrypted
    iff message_id IS NOT NULL. We replace the decrypted index with a message_id index.

    SQLite 3.35.0+ supports ALTER TABLE DROP COLUMN. For older versions,
    we silently skip the column drop but still update the index.
    """
    # First, drop the old index on decrypted (safe even if it doesn't exist)
    try:
        await conn.execute("DROP INDEX IF EXISTS idx_raw_packets_decrypted")
        logger.debug("Dropped idx_raw_packets_decrypted index")
    except aiosqlite.OperationalError:
        pass  # Index didn't exist

    # Create new index on message_id for efficient undecrypted packet queries
    try:
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_raw_packets_message_id ON raw_packets(message_id)"
        )
        logger.debug("Created idx_raw_packets_message_id index")
    except aiosqlite.OperationalError as e:
        if "already exists" not in str(e).lower():
            raise

    # Try to drop the decrypted column
    try:
        await conn.execute("ALTER TABLE raw_packets DROP COLUMN decrypted")
        logger.debug("Dropped decrypted from raw_packets table")
    except aiosqlite.OperationalError as e:
        error_msg = str(e).lower()
        if "no such column" in error_msg:
            logger.debug("raw_packets.decrypted already dropped, skipping")
        elif "syntax error" in error_msg or "drop column" in error_msg:
            # SQLite version doesn't support DROP COLUMN - harmless, column stays
            logger.debug("SQLite doesn't support DROP COLUMN, decrypted column will remain")
        else:
            raise

    await conn.commit()
