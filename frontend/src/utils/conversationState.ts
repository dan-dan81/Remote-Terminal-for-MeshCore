/**
 * localStorage utilities for tracking conversation message times.
 *
 * Stores when each conversation last received a message, used for
 * sorting conversations by recency in the sidebar.
 *
 * Read state (last_read_at) is tracked server-side for consistency
 * across devices - see useUnreadCounts hook.
 */

import { getPubkeyPrefix } from './pubkey';

const LAST_MESSAGE_KEY = 'remoteterm-lastMessageTime';

export type ConversationTimes = Record<string, number>;

function loadTimes(key: string): ConversationTimes {
  try {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored) : {};
  } catch {
    return {};
  }
}

function saveTimes(key: string, times: ConversationTimes): void {
  try {
    localStorage.setItem(key, JSON.stringify(times));
  } catch {
    // localStorage might be full or disabled
  }
}

export function getLastMessageTimes(): ConversationTimes {
  return loadTimes(LAST_MESSAGE_KEY);
}

export function setLastMessageTime(stateKey: string, timestamp: number): ConversationTimes {
  const times = loadTimes(LAST_MESSAGE_KEY);
  // Only update if this is a newer message
  if (!times[stateKey] || timestamp > times[stateKey]) {
    times[stateKey] = timestamp;
    saveTimes(LAST_MESSAGE_KEY, times);
  }
  return times;
}

/**
 * Generate a state tracking key for message times.
 *
 * This is NOT the same as Message.conversation_key (the database field).
 * This creates prefixed keys for localStorage/state tracking:
 * - Channels: "channel-{channelKey}"
 * - Contacts: "contact-{12-char-pubkey-prefix}"
 *
 * The 12-char prefix for contacts ensures consistent matching regardless
 * of whether we have a full 64-char pubkey or just a prefix.
 */
export function getStateKey(
  type: 'channel' | 'contact',
  id: string
): string {
  if (type === 'channel') {
    return `channel-${id}`;
  }
  // For contacts, use 12-char prefix for consistent matching
  return `contact-${getPubkeyPrefix(id)}`;
}
