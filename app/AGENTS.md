# Backend AGENTS.md

This document is the backend working guide for agents and developers.
Keep it aligned with `app/` source files and router behavior.

## Stack

- FastAPI
- aiosqlite
- Pydantic
- MeshCore Python library (`references/meshcore_py`)
- PyCryptodome

## Backend Map

```text
app/
├── main.py              # App startup/lifespan, router registration, static frontend mounting
├── config.py            # Env-driven runtime settings
├── database.py          # SQLite connection + base schema + migration runner
├── migrations.py        # Schema migrations (SQLite user_version)
├── models.py            # Pydantic request/response models
├── repository.py        # Data access layer
├── radio.py             # RadioManager + auto-reconnect monitor
├── radio_sync.py        # Polling, sync, periodic advertisement loop
├── decoder.py           # Packet parsing/decryption
├── packet_processor.py  # Raw packet pipeline, dedup, path handling
├── event_handlers.py    # MeshCore event subscriptions and ACK tracking
├── websocket.py         # WS manager + broadcast helpers
├── bot.py               # Bot execution and outbound bot sends
├── dependencies.py      # Shared FastAPI dependency providers
├── keystore.py          # Ephemeral private/public key storage for DM decryption
├── frontend_static.py   # Mount/serve built frontend (production)
└── routers/
    ├── health.py
    ├── radio.py
    ├── contacts.py
    ├── channels.py
    ├── messages.py
    ├── packets.py
    ├── read_state.py
    ├── settings.py
    └── ws.py
```

## Core Runtime Flows

### Incoming data

1. Radio emits events.
2. `on_rx_log_data` stores raw packet and tries decrypt/pipeline handling.
3. Decrypted messages are inserted into `messages` and broadcast over WS.
4. `CONTACT_MSG_RECV` is a fallback DM path when packet pipeline cannot decrypt.

### Outgoing messages

1. Send endpoints in `routers/messages.py` call MeshCore commands.
2. Message is persisted as outgoing.
3. Endpoint broadcasts WS `message` event so all live clients update.
4. ACK/repeat updates arrive later as `message_acked` events.

### Connection lifecycle

- `RadioManager.start_connection_monitor()` checks health every 5s.
- On reconnect, monitor runs `post_connect_setup()` before broadcasting healthy state.
- Setup includes handler registration, key export, time sync, contact/channel sync, polling/advert tasks.

## Important Behaviors

### Read/unread state

- Server is source of truth (`contacts.last_read_at`, `channels.last_read_at`).
- `GET /api/read-state/unreads` returns counts, mention flags, and `last_message_times`.

### Echo/repeat dedup

- Message uniqueness: `(type, conversation_key, text, sender_timestamp)`.
- Duplicate insert is treated as an echo/repeat; ACK count/path list is updated.

### Periodic advertisement

- Controlled by `app_settings.advert_interval` (seconds).
- `0` means disabled.
- Last send time tracked in `app_settings.last_advert_time`.

## API Surface (all under `/api`)

### Health
- `GET /health`

### Radio
- `GET /radio/config`
- `PATCH /radio/config`
- `PUT /radio/private-key`
- `POST /radio/advertise`
- `POST /radio/reboot`
- `POST /radio/reconnect`

### Contacts
- `GET /contacts`
- `GET /contacts/{public_key}`
- `POST /contacts`
- `DELETE /contacts/{public_key}`
- `POST /contacts/sync`
- `POST /contacts/{public_key}/add-to-radio`
- `POST /contacts/{public_key}/remove-from-radio`
- `POST /contacts/{public_key}/mark-read`
- `POST /contacts/{public_key}/telemetry`
- `POST /contacts/{public_key}/command`
- `POST /contacts/{public_key}/trace`

### Channels
- `GET /channels`
- `GET /channels/{key}`
- `POST /channels`
- `DELETE /channels/{key}`
- `POST /channels/sync`
- `POST /channels/{key}/mark-read`

### Messages
- `GET /messages`
- `POST /messages/direct`
- `POST /messages/channel`

### Packets
- `GET /packets/undecrypted/count`
- `POST /packets/decrypt/historical`
- `POST /packets/maintenance`

### Read state
- `GET /read-state/unreads`
- `POST /read-state/mark-all-read`

### Settings
- `GET /settings`
- `PATCH /settings`
- `POST /settings/favorites/toggle`
- `POST /settings/migrate`

### WebSocket
- `WS /ws`

## WebSocket Events

- `health`
- `contact`
- `message`
- `message_acked`
- `raw_packet`
- `error`
- `success`

Initial WS connect sends `health` only. Contacts/channels are loaded by REST.
Note: the frontend WS hook also registers handlers for `contacts` and `channels` events, but the backend never emits them.

## Data Model Notes

Main tables:
- `contacts`
- `channels`
- `messages`
- `raw_packets`
- `app_settings`

`app_settings` fields in active model:
- `max_radio_contacts`
- `experimental_channel_double_send`
- `favorites`
- `auto_decrypt_dm_on_advert`
- `sidebar_sort_order`
- `last_message_times`
- `preferences_migrated`
- `advert_interval`
- `last_advert_time`
- `bots`

## Security Posture (intentional)

- No authn/authz.
- No CORS restriction (`*`).
- Bot code executes user-provided Python via `exec()`.

These are product decisions for trusted-network deployments; do not flag as accidental vulnerabilities.

## Testing

Run backend tests:

```bash
PYTHONPATH=. uv run pytest tests/ -v
```

High-signal suites:
- `tests/test_packet_pipeline.py`
- `tests/test_event_handlers.py`
- `tests/test_send_messages.py`
- `tests/test_radio.py`
- `tests/test_api.py`
- `tests/test_migrations.py`

## Editing Checklist

When changing backend behavior:
1. Update/add router and repository tests.
2. Confirm WS event contracts when payload shape changes.
3. Run `PYTHONPATH=. uv run pytest tests/ -v`.
4. If API contract changed, update frontend types and AGENTS docs.
