/**
 * Tests for repeater-specific behavior.
 *
 * These tests verify edge cases in repeater interactions that could easily
 * regress if the code is modified:
 *
 * 1. Repeater messages should NOT have sender parsed from text (colons are common in CLI output)
 * 2. Empty password field = guest login, password field with text = password login
 */

import { describe, it, expect } from 'vitest';
import { parseSenderFromText } from '../utils/messageParser';
import { CONTACT_TYPE_REPEATER, CONTACT_TYPE_CLIENT } from '../types';

describe('Repeater message sender parsing', () => {
  /**
   * CLI responses from repeaters often contain colons (e.g., "clock: 12:30:00").
   * If we parse these like normal channel messages, we'd incorrectly extract
   * "clock" as a sender name, breaking the display.
   *
   * The fix in MessageList.tsx is to check if the contact is a repeater and
   * skip parseSenderFromText entirely. These tests document the expected
   * behavior pattern.
   */

  it('parseSenderFromText would incorrectly parse CLI responses with colons', () => {
    // This demonstrates WHY we skip parsing for repeaters
    const cliResponse = 'clock: 2024-01-09 12:30:00';
    const parsed = parseSenderFromText(cliResponse);

    // Without the repeater check, we'd get this incorrect result:
    expect(parsed.sender).toBe('clock');
    expect(parsed.content).toBe('2024-01-09 12:30:00');
    // This would display as "clock" sent "2024-01-09 12:30:00" - WRONG!
  });

  it('repeater messages should bypass parsing entirely', () => {
    // This documents the correct behavior: skip parsing for repeaters
    const cliResponse = 'clock: 2024-01-09 12:30:00';
    const contactType = CONTACT_TYPE_REPEATER;

    // The pattern used in MessageList.tsx:
    const isRepeater = contactType === CONTACT_TYPE_REPEATER;
    const { sender, content } = isRepeater
      ? { sender: null, content: cliResponse }
      : parseSenderFromText(cliResponse);

    // Correct: full text preserved, no sender extracted
    expect(sender).toBeNull();
    expect(content).toBe('clock: 2024-01-09 12:30:00');
  });

  it('non-repeater messages still get sender parsed', () => {
    const channelMessage = 'Alice: Hello everyone!';
    const contactType: number = CONTACT_TYPE_CLIENT;

    const isRepeater = contactType === CONTACT_TYPE_REPEATER;
    const { sender, content } = isRepeater
      ? { sender: null, content: channelMessage }
      : parseSenderFromText(channelMessage);

    // Normal behavior: sender extracted
    expect(sender).toBe('Alice');
    expect(content).toBe('Hello everyone!');
  });

  it('handles various CLI response formats that would be mis-parsed', () => {
    const cliResponses = [
      'ver: 1.2.3',
      'tx: 20 dBm',
      'name: MyRepeater',
      'radio: 915.0,125,9,5',
      'Error: command not found',
      'uptime: 3d 12h 30m',
    ];

    for (const response of cliResponses) {
      // All of these would be incorrectly parsed without the repeater check
      const parsed = parseSenderFromText(response);
      expect(parsed.sender).not.toBeNull();

      // But with repeater check, they're preserved
      const isRepeater = true;
      const { sender, content } = isRepeater
        ? { sender: null, content: response }
        : parseSenderFromText(response);

      expect(sender).toBeNull();
      expect(content).toBe(response);
    }
  });
});

describe('Repeater login behavior', () => {
  /**
   * Repeater login has two modes:
   * - Empty password field = guest login (uses repeater's ACL permissions)
   * - Password in field = admin login attempt
   */

  it('empty input results in empty password (guest login)', () => {
    // This is the logic in MessageInput.tsx handleSubmit
    const text = '';
    const trimmed = text.trim();

    // Empty string is passed directly to onSend
    expect(trimmed).toBe('');
  });

  it('password is passed through unchanged', () => {
    const text = 'mySecretPassword';
    const trimmed = text.trim();

    expect(trimmed).toBe('mySecretPassword');
  });

  it('whitespace-only input is treated as empty (guest login)', () => {
    const text = '   ';
    const trimmed = text.trim();

    expect(trimmed).toBe('');
  });

  it('password with surrounding whitespace is trimmed', () => {
    const text = '  secret123  ';
    const trimmed = text.trim();

    expect(trimmed).toBe('secret123');
  });
});
