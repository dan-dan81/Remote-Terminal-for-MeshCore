/**
 * Tests for URL hash utilities.
 *
 * These tests verify the URL hash parsing and generation
 * for deep linking to conversations.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { parseHashConversation, getConversationHash, getMapFocusHash } from '../utils/urlHash';
import type { Conversation } from '../types';

describe('parseHashConversation', () => {
  let originalHash: string;

  beforeEach(() => {
    originalHash = window.location.hash;
  });

  afterEach(() => {
    window.location.hash = originalHash;
  });

  it('returns null for empty hash', () => {
    window.location.hash = '';

    const result = parseHashConversation();

    expect(result).toBeNull();
  });

  it('parses #raw as raw type', () => {
    window.location.hash = '#raw';

    const result = parseHashConversation();

    expect(result).toEqual({ type: 'raw', name: 'raw' });
  });

  it('parses #map as map type', () => {
    window.location.hash = '#map';

    const result = parseHashConversation();

    expect(result).toEqual({ type: 'map', name: 'map' });
  });

  it('parses #map/focus/PUBKEY with focus key', () => {
    window.location.hash = '#map/focus/ABCD1234';

    const result = parseHashConversation();

    expect(result).toEqual({ type: 'map', name: 'map', mapFocusKey: 'ABCD1234' });
  });

  it('parses #map/focus/ with empty focus as plain map', () => {
    window.location.hash = '#map/focus/';

    const result = parseHashConversation();

    expect(result).toEqual({ type: 'map', name: 'map' });
  });

  it('decodes URL-encoded map focus key', () => {
    window.location.hash = '#map/focus/AB%20CD';

    const result = parseHashConversation();

    expect(result).toEqual({ type: 'map', name: 'map', mapFocusKey: 'AB CD' });
  });

  it('parses channel hash', () => {
    window.location.hash = '#channel/Public';

    const result = parseHashConversation();

    expect(result).toEqual({ type: 'channel', name: 'Public' });
  });

  it('parses contact hash', () => {
    window.location.hash = '#contact/Alice';

    const result = parseHashConversation();

    expect(result).toEqual({ type: 'contact', name: 'Alice' });
  });

  it('decodes URL-encoded names', () => {
    window.location.hash = '#contact/John%20Doe';

    const result = parseHashConversation();

    expect(result).toEqual({ type: 'contact', name: 'John Doe' });
  });

  it('returns null for invalid type', () => {
    window.location.hash = '#invalid/Test';

    const result = parseHashConversation();

    expect(result).toBeNull();
  });

  it('returns null for hash without slash', () => {
    window.location.hash = '#channelPublic';

    const result = parseHashConversation();

    expect(result).toBeNull();
  });

  it('returns null for hash with empty name', () => {
    window.location.hash = '#channel/';

    const result = parseHashConversation();

    expect(result).toBeNull();
  });

  it('handles channel names with special characters', () => {
    window.location.hash = '#channel/Test%20Channel%21';

    const result = parseHashConversation();

    expect(result).toEqual({ type: 'channel', name: 'Test Channel!' });
  });
});

describe('getConversationHash', () => {
  it('returns empty string for null conversation', () => {
    const result = getConversationHash(null);

    expect(result).toBe('');
  });

  it('returns #raw for raw conversation', () => {
    const conv: Conversation = { type: 'raw', id: 'raw', name: 'Raw Packet Feed' };

    const result = getConversationHash(conv);

    expect(result).toBe('#raw');
  });

  it('returns #map for map conversation', () => {
    const conv: Conversation = { type: 'map', id: 'map', name: 'Node Map' };

    const result = getConversationHash(conv);

    expect(result).toBe('#map');
  });

  it('generates channel hash', () => {
    const conv: Conversation = { type: 'channel', id: 'key123', name: 'Public' };

    const result = getConversationHash(conv);

    expect(result).toBe('#channel/Public');
  });

  it('generates contact hash', () => {
    const conv: Conversation = { type: 'contact', id: 'pubkey123', name: 'Alice' };

    const result = getConversationHash(conv);

    expect(result).toBe('#contact/Alice');
  });

  it('strips leading # from channel names', () => {
    const conv: Conversation = { type: 'channel', id: 'key123', name: '#TestChannel' };

    const result = getConversationHash(conv);

    expect(result).toBe('#channel/TestChannel');
  });

  it('encodes special characters in names', () => {
    const conv: Conversation = { type: 'contact', id: 'key', name: 'John Doe' };

    const result = getConversationHash(conv);

    expect(result).toBe('#contact/John%20Doe');
  });

  it('does not strip # from contact names', () => {
    const conv: Conversation = { type: 'contact', id: 'key', name: '#Hashtag' };

    const result = getConversationHash(conv);

    expect(result).toBe('#contact/%23Hashtag');
  });
});

describe('parseHashConversation and getConversationHash roundtrip', () => {
  let originalHash: string;

  beforeEach(() => {
    originalHash = window.location.hash;
  });

  afterEach(() => {
    window.location.hash = originalHash;
  });

  it('channel roundtrip preserves data', () => {
    const conv: Conversation = { type: 'channel', id: 'key123', name: 'Test Channel' };

    const hash = getConversationHash(conv);
    window.location.hash = hash;
    const parsed = parseHashConversation();

    expect(parsed).toEqual({ type: 'channel', name: 'Test Channel' });
  });

  it('contact roundtrip preserves data', () => {
    const conv: Conversation = { type: 'contact', id: 'pubkey', name: 'Alice Bob' };

    const hash = getConversationHash(conv);
    window.location.hash = hash;
    const parsed = parseHashConversation();

    expect(parsed).toEqual({ type: 'contact', name: 'Alice Bob' });
  });

  it('raw roundtrip preserves type', () => {
    const conv: Conversation = { type: 'raw', id: 'raw', name: 'Raw Packet Feed' };

    const hash = getConversationHash(conv);
    window.location.hash = hash;
    const parsed = parseHashConversation();

    expect(parsed).toEqual({ type: 'raw', name: 'raw' });
  });

  it('map roundtrip preserves type', () => {
    const conv: Conversation = { type: 'map', id: 'map', name: 'Node Map' };

    const hash = getConversationHash(conv);
    window.location.hash = hash;
    const parsed = parseHashConversation();

    expect(parsed).toEqual({ type: 'map', name: 'map' });
  });
});

describe('getMapFocusHash', () => {
  it('generates hash with focus key', () => {
    const result = getMapFocusHash('ABCD1234');

    expect(result).toBe('#map/focus/ABCD1234');
  });

  it('encodes special characters in key', () => {
    const result = getMapFocusHash('AB CD/12');

    expect(result).toBe('#map/focus/AB%20CD%2F12');
  });
});
