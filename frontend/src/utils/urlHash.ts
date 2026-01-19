import type { Conversation } from '../types';

export interface ParsedHashConversation {
  type: 'channel' | 'contact' | 'raw' | 'map';
  name: string;
  /** For map view: public key prefix to focus on */
  mapFocusKey?: string;
}

// Parse URL hash to get conversation (e.g., #channel/Public or #contact/JohnDoe or #raw or #map/focus/ABCD1234)
export function parseHashConversation(): ParsedHashConversation | null {
  const hash = window.location.hash.slice(1); // Remove leading #
  if (!hash) return null;

  if (hash === 'raw') {
    return { type: 'raw', name: 'raw' };
  }

  if (hash === 'map') {
    return { type: 'map', name: 'map' };
  }

  // Check for map with focus: #map/focus/{pubkey_prefix}
  if (hash.startsWith('map/focus/')) {
    const focusKey = hash.slice('map/focus/'.length);
    if (focusKey) {
      return { type: 'map', name: 'map', mapFocusKey: decodeURIComponent(focusKey) };
    }
    return { type: 'map', name: 'map' };
  }

  const slashIndex = hash.indexOf('/');
  if (slashIndex === -1) return null;

  const type = hash.slice(0, slashIndex);
  const name = decodeURIComponent(hash.slice(slashIndex + 1));

  if ((type === 'channel' || type === 'contact') && name) {
    return { type, name };
  }
  return null;
}

/**
 * Generate a URL hash for focusing on a contact in the map view
 * @param publicKeyPrefix - The public key or prefix to focus on
 */
export function getMapFocusHash(publicKeyPrefix: string): string {
  return `#map/focus/${encodeURIComponent(publicKeyPrefix)}`;
}

// Generate URL hash from conversation
export function getConversationHash(conv: Conversation | null): string {
  if (!conv) return '';
  if (conv.type === 'raw') return '#raw';
  if (conv.type === 'map') return '#map';
  // Strip leading # from channel names for cleaner URLs
  const name =
    conv.type === 'channel' && conv.name.startsWith('#') ? conv.name.slice(1) : conv.name;
  return `#${conv.type}/${encodeURIComponent(name)}`;
}

// Update URL hash without adding to history
export function updateUrlHash(conv: Conversation | null): void {
  const newHash = getConversationHash(conv);
  if (newHash !== window.location.hash) {
    window.history.replaceState(null, '', newHash || window.location.pathname);
  }
}
