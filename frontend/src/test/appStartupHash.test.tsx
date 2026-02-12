import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  api: {
    getRadioConfig: vi.fn(),
    getSettings: vi.fn(),
    getUndecryptedPacketCount: vi.fn(),
    getChannels: vi.fn(),
    getContacts: vi.fn(),
    migratePreferences: vi.fn(),
  },
}));

vi.mock('../api', () => ({
  api: mocks.api,
}));

vi.mock('../useWebSocket', () => ({
  useWebSocket: vi.fn(),
}));

vi.mock('../hooks', () => ({
  useConversationMessages: () => ({
    messages: [],
    messagesLoading: false,
    loadingOlder: false,
    hasOlderMessages: false,
    setMessages: vi.fn(),
    fetchMessages: vi.fn(async () => {}),
    fetchOlderMessages: vi.fn(async () => {}),
    addMessageIfNew: vi.fn(),
    updateMessageAck: vi.fn(),
  }),
  useUnreadCounts: () => ({
    unreadCounts: {},
    mentions: {},
    lastMessageTimes: {},
    incrementUnread: vi.fn(),
    markAllRead: vi.fn(),
    trackNewMessage: vi.fn(),
  }),
  useRepeaterMode: () => ({
    repeaterLoggedIn: false,
    activeContactIsRepeater: false,
    handleTelemetryRequest: vi.fn(),
    handleRepeaterCommand: vi.fn(),
  }),
  getMessageContentKey: () => 'content-key',
}));

vi.mock('../messageCache', () => ({
  addMessage: vi.fn(),
  updateAck: vi.fn(),
  remove: vi.fn(),
}));

vi.mock('../components/StatusBar', () => ({
  StatusBar: () => <div data-testid="status-bar" />,
}));

vi.mock('../components/Sidebar', () => ({
  Sidebar: ({
    activeConversation,
  }: {
    activeConversation: { type: string; id: string; name: string } | null;
  }) => (
    <div data-testid="active-conversation">
      {activeConversation
        ? `${activeConversation.type}:${activeConversation.id}:${activeConversation.name}`
        : 'none'}
    </div>
  ),
}));

vi.mock('../components/MessageList', () => ({
  MessageList: () => <div data-testid="message-list" />,
}));

vi.mock('../components/MessageInput', () => ({
  MessageInput: React.forwardRef((_props, ref) => {
    React.useImperativeHandle(ref, () => ({ appendText: vi.fn() }));
    return <div data-testid="message-input" />;
  }),
}));

vi.mock('../components/NewMessageModal', () => ({
  NewMessageModal: () => null,
}));

vi.mock('../components/SettingsModal', () => ({
  SettingsModal: () => null,
  SETTINGS_SECTION_ORDER: ['radio', 'identity', 'connectivity', 'database', 'bot'],
  SETTINGS_SECTION_LABELS: {
    radio: 'Radio',
    identity: 'Identity',
    connectivity: 'Connectivity',
    database: 'Database',
    bot: 'Bot',
  },
}));

vi.mock('../components/RawPacketList', () => ({
  RawPacketList: () => null,
}));

vi.mock('../components/MapView', () => ({
  MapView: () => null,
}));

vi.mock('../components/VisualizerView', () => ({
  VisualizerView: () => null,
}));

vi.mock('../components/CrackerPanel', () => ({
  CrackerPanel: () => null,
}));

vi.mock('../components/ui/sheet', () => ({
  Sheet: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetTitle: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('../components/ui/sonner', () => ({
  Toaster: () => null,
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { App } from '../App';

const publicChannel = {
  key: '8B3387E9C5CDEA6AC9E5EDBAA115CD72',
  name: 'Public',
  is_hashtag: false,
  on_radio: false,
  last_read_at: null,
};

describe('App startup hash resolution', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = `#contact/${'a'.repeat(64)}/Alice`;

    mocks.api.getRadioConfig.mockResolvedValue({
      public_key: 'aa'.repeat(32),
      name: 'TestNode',
      lat: 0,
      lon: 0,
      tx_power: 17,
      max_tx_power: 22,
      radio: { freq: 910.525, bw: 62.5, sf: 7, cr: 5 },
    });
    mocks.api.getSettings.mockResolvedValue({
      max_radio_contacts: 200,
      experimental_channel_double_send: false,
      favorites: [],
      auto_decrypt_dm_on_advert: false,
      sidebar_sort_order: 'recent',
      last_message_times: {},
      preferences_migrated: true,
      advert_interval: 0,
      last_advert_time: 0,
      bots: [],
    });
    mocks.api.getUndecryptedPacketCount.mockResolvedValue({ count: 0 });
    mocks.api.getChannels.mockResolvedValue([publicChannel]);
    mocks.api.getContacts.mockResolvedValue([]);
  });

  afterEach(() => {
    window.location.hash = '';
  });

  it('falls back to Public when contact hash is unresolvable and contacts are empty', async () => {
    render(<App />);

    await waitFor(() => {
      for (const node of screen.getAllByTestId('active-conversation')) {
        expect(node).toHaveTextContent(`channel:${publicChannel.key}:Public`);
      }
    });
  });
});
