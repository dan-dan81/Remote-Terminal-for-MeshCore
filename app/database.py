import logging
from pathlib import Path

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
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
    last_contacted INTEGER
);

CREATE TABLE IF NOT EXISTS channels (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    is_hashtag INTEGER DEFAULT 0,
    on_radio INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    conversation_key TEXT NOT NULL,
    text TEXT NOT NULL,
    sender_timestamp INTEGER,
    received_at INTEGER NOT NULL,
    path TEXT,
    txt_type INTEGER DEFAULT 0,
    signature TEXT,
    outgoing INTEGER DEFAULT 0,
    acked INTEGER DEFAULT 0,
    UNIQUE(type, conversation_key, text, sender_timestamp)
);

CREATE TABLE IF NOT EXISTS raw_packets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    data BLOB NOT NULL,
    message_id INTEGER,
    payload_hash TEXT,
    FOREIGN KEY (message_id) REFERENCES messages(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(type, conversation_key);
CREATE INDEX IF NOT EXISTS idx_messages_received ON messages(received_at);
CREATE INDEX IF NOT EXISTS idx_raw_packets_message_id ON raw_packets(message_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_packets_payload_hash ON raw_packets(payload_hash);
CREATE INDEX IF NOT EXISTS idx_contacts_on_radio ON contacts(on_radio);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        logger.info("Connecting to database at %s", self.db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()
        logger.debug("Database schema initialized")

        # Run any pending migrations
        from app.migrations import run_migrations

        await run_migrations(self._connection)

    async def disconnect(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.debug("Database connection closed")

    @property
    def conn(self) -> aiosqlite.Connection:
        if not self._connection:
            raise RuntimeError("Database not connected")
        return self._connection


db = Database(settings.database_path)
