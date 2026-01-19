/**
 * Conversation state utilities.
 *
 * Last message times are tracked in-memory and persisted server-side.
 * This file provides helper functions for generating state keys
 * and managing conversation times.
 *
 * Read state (last_read_at) is tracked server-side for consistency
 * across devices - see useUnreadCounts hook.
 */

import { getPubkeyPrefix } from './pubkey';

const LAST_MESSAGE_KEY = 'remoteterm-lastMessageTime';
const SORT_ORDER_KEY = 'remoteterm-sortOrder';

export type ConversationTimes = Record<string, number>;
export type SortOrder = 'recent' | 'alpha';

// In-memory cache of last message times (loaded from server on init)
let lastMessageTimesCache: ConversationTimes = {};

/**
 * Initialize the last message times cache from server data
 */
export function initLastMessageTimes(times: ConversationTimes): void {
  lastMessageTimesCache = { ...times };
}

/**
 * Get all last message times from the cache
 */
export function getLastMessageTimes(): ConversationTimes {
  return { ...lastMessageTimesCache };
}

/**
 * Update a single message time in the cache and return the updated cache.
 * Note: This does NOT persist to server - caller should sync if needed.
 */
export function setLastMessageTime(key: string, timestamp: number): ConversationTimes {
  lastMessageTimesCache[key] = timestamp;
  return { ...lastMessageTimesCache };
}

/**
 * Generate a state tracking key for message times.
 *
 * This is NOT the same as Message.conversation_key (the database field).
 * This creates prefixed keys for state tracking:
 * - Channels: "channel-{channelKey}"
 * - Contacts: "contact-{12-char-pubkey-prefix}"
 *
 * The 12-char prefix for contacts ensures consistent matching regardless
 * of whether we have a full 64-char pubkey or just a prefix.
 */
export function getStateKey(type: 'channel' | 'contact', id: string): string {
  if (type === 'channel') {
    return `channel-${id}`;
  }
  // For contacts, use 12-char prefix for consistent matching
  return `contact-${getPubkeyPrefix(id)}`;
}

/**
 * Load last message times from localStorage (for migration only)
 */
export function loadLocalStorageLastMessageTimes(): ConversationTimes {
  try {
    const stored = localStorage.getItem(LAST_MESSAGE_KEY);
    return stored ? JSON.parse(stored) : {};
  } catch {
    return {};
  }
}

/**
 * Load sort order from localStorage (for migration only)
 */
export function loadLocalStorageSortOrder(): SortOrder {
  try {
    const stored = localStorage.getItem(SORT_ORDER_KEY);
    return stored === 'alpha' ? 'alpha' : 'recent';
  } catch {
    return 'recent';
  }
}

/**
 * Clear conversation state from localStorage (after migration)
 */
export function clearLocalStorageConversationState(): void {
  try {
    localStorage.removeItem(LAST_MESSAGE_KEY);
    localStorage.removeItem(SORT_ORDER_KEY);
  } catch {
    // localStorage might be disabled
  }
}
