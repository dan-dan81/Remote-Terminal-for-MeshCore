# Frontend AGENTS.md

This document is the frontend working guide for agents and developers.
Keep it aligned with `frontend/src` source code.

## Stack

- React 18 + TypeScript
- Vite
- Vitest + Testing Library
- shadcn/ui primitives
- Tailwind utility classes + local CSS (`index.css`, `styles.css`)
- Sonner (toasts)
- Leaflet / react-leaflet (map)
- `meshcore-hashtag-cracker` + `nosleep.js` (channel cracker)

## Frontend Map

```text
frontend/src/
├── App.tsx                 # App shell and orchestration
├── api.ts                  # Typed REST client
├── types.ts                # Shared TS contracts
├── useWebSocket.ts         # WS lifecycle + event dispatch
├── messageCache.ts         # Conversation-scoped cache
├── index.css               # Global styles/utilities
├── styles.css              # Additional global app styles
├── hooks/
│   ├── useConversationMessages.ts
│   ├── useUnreadCounts.ts
│   ├── useRepeaterMode.ts
│   └── useAirtimeTracking.ts
├── utils/
│   ├── urlHash.ts
│   ├── conversationState.ts
│   ├── favorites.ts
│   ├── messageParser.ts
│   ├── pathUtils.ts
│   ├── pubkey.ts
│   └── contactAvatar.ts
├── components/
│   ├── StatusBar.tsx
│   ├── Sidebar.tsx
│   ├── MessageList.tsx
│   ├── MessageInput.tsx
│   ├── NewMessageModal.tsx
│   ├── SettingsModal.tsx
│   ├── RawPacketList.tsx
│   ├── MapView.tsx
│   ├── VisualizerView.tsx
│   ├── PacketVisualizer.tsx
│   ├── PathModal.tsx
│   ├── CrackerPanel.tsx
│   ├── BotCodeEditor.tsx
│   ├── ContactAvatar.tsx
│   └── ui/
└── test/
    ├── api.test.ts
    ├── appFavorites.test.tsx
    ├── appStartupHash.test.tsx
    ├── contactAvatar.test.ts
    ├── integration.test.ts
    ├── messageCache.test.ts
    ├── messageParser.test.ts
    ├── pathUtils.test.ts
    ├── radioPresets.test.ts
    ├── repeaterMode.test.ts
    ├── settingsModal.test.tsx
    ├── unreadCounts.test.ts
    ├── urlHash.test.ts
    ├── useConversationMessages.test.ts
    ├── useRepeaterMode.test.ts
    ├── useWebSocket.lifecycle.test.ts
    ├── websocket.test.ts
    └── setup.ts
```

## Architecture Notes

### State ownership

`App.tsx` orchestrates high-level state (health, config, contacts/channels, active conversation, UI flags).
Specialized logic is delegated to hooks:
- `useConversationMessages`: fetch, pagination, dedup/update helpers
- `useUnreadCounts`: unread counters, mention tracking, recent-sort timestamps
- `useRepeaterMode`: repeater login/command workflow

### Initial load + realtime

- Initial data: REST fetches (`api.ts`) for config/settings/channels/contacts/unreads.
- WebSocket: realtime deltas/events.
- On WS connect, backend sends `health` only; contacts/channels still come from REST.

### Message behavior

- Outgoing sends are optimistic in UI and persisted server-side.
- Backend also emits WS `message` for outgoing sends so other clients stay in sync.
- ACK/repeat updates arrive as `message_acked` events.
- Outgoing channel messages show a 30-second resend control; resend calls `POST /api/messages/channel/{message_id}/resend`.

## WebSocket (`useWebSocket.ts`)

- Auto reconnect (3s) with cleanup guard on unmount.
- Heartbeat ping every 30s.
- Event handlers: `health`, `message`, `contact`, `raw_packet`, `message_acked`, `error`, `success`, `pong` (ignored).

## URL Hash Navigation (`utils/urlHash.ts`)

Supported routes:
- `#raw`
- `#map`
- `#map/focus/{pubkey_or_prefix}`
- `#visualizer`
- `#channel/{channelKey}`
- `#channel/{channelKey}/{label}`
- `#contact/{publicKey}`
- `#contact/{publicKey}/{label}`

Legacy name-based hashes are still accepted for compatibility.

## Conversation State Keys (`utils/conversationState.ts`)

`getStateKey(type, id)` produces:
- channels: `channel-{channelKey}`
- contacts: `contact-{publicKey}`

Use full contact public key here (not 12-char prefix).

`conversationState.ts` keeps an in-memory cache and localStorage helpers used for migration/compatibility.
Canonical persistence for unread and sort metadata is server-side (`app_settings` + read-state endpoints).

## Utilities

### `utils/pubkey.ts`

Current public export:
- `getContactDisplayName(name, pubkey)`

It falls back to a 12-char prefix when `name` is missing.

### `utils/pathUtils.ts`

Distance/validation helpers used by path + map UI.

### `utils/favorites.ts`

LocalStorage migration helpers for favorites; canonical favorites are server-side.

## Types and Contracts (`types.ts`)

`AppSettings` currently includes:
- `max_radio_contacts`
- `favorites`
- `auto_decrypt_dm_on_advert`
- `sidebar_sort_order`
- `last_message_times`
- `preferences_migrated`
- `advert_interval`
- `last_advert_time`
- `bots`

## Repeater Mode

For repeater contacts (`type=2`):
1. Telemetry/login phase (`POST /api/contacts/{key}/telemetry`)
2. Command phase (`POST /api/contacts/{key}/command`)

CLI responses are rendered as local-only messages (not persisted to DB).

## Styling

UI styling is mostly utility-class driven (Tailwind-style classes in JSX) plus shared globals in `index.css` and `styles.css`.
Do not rely on old class-only layout assumptions.

## Security Posture (intentional)

- No authentication UI.
- Frontend assumes trusted network usage.
- Bot editor intentionally allows arbitrary backend bot code configuration.

## Testing

```bash
cd frontend
npm run test:run
npm run build
```

When touching cross-layer contracts, also run backend tests from repo root:

```bash
PYTHONPATH=. uv run pytest tests/ -v
```

## Editing Checklist

1. If API/WS payloads change, update `types.ts`, handlers, and tests.
2. If URL/hash behavior changes, update `utils/urlHash.ts` tests.
3. If read/unread semantics change, update `useUnreadCounts` tests.
4. Keep this file concise; prefer source links over speculative detail.
