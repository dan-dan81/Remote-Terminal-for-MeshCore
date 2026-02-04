/**
 * Tests for WebSocket message parsing.
 *
 * These tests verify that WebSocket messages are correctly parsed
 * and routed to the appropriate handlers.
 */

import { describe, it, expect, vi } from 'vitest';
import type { HealthStatus, Contact, Channel, Message, MessagePath, RawPacket } from '../types';

/**
 * Parse and route a WebSocket message.
 * Extracted logic from useWebSocket.ts for testing.
 */
function parseWebSocketMessage(
  data: string,
  handlers: {
    onHealth?: (health: HealthStatus) => void;
    onContacts?: (contacts: Contact[]) => void;
    onChannels?: (channels: Channel[]) => void;
    onMessage?: (message: Message) => void;
    onContact?: (contact: Contact) => void;
    onRawPacket?: (packet: RawPacket) => void;
    onMessageAcked?: (messageId: number, ackCount: number, paths?: MessagePath[]) => void;
  }
): { type: string; handled: boolean } {
  try {
    const msg = JSON.parse(data);

    switch (msg.type) {
      case 'health':
        handlers.onHealth?.(msg.data as HealthStatus);
        return { type: msg.type, handled: !!handlers.onHealth };
      case 'contacts':
        handlers.onContacts?.(msg.data as Contact[]);
        return { type: msg.type, handled: !!handlers.onContacts };
      case 'channels':
        handlers.onChannels?.(msg.data as Channel[]);
        return { type: msg.type, handled: !!handlers.onChannels };
      case 'message':
        handlers.onMessage?.(msg.data as Message);
        return { type: msg.type, handled: !!handlers.onMessage };
      case 'contact':
        handlers.onContact?.(msg.data as Contact);
        return { type: msg.type, handled: !!handlers.onContact };
      case 'raw_packet':
        handlers.onRawPacket?.(msg.data as RawPacket);
        return { type: msg.type, handled: !!handlers.onRawPacket };
      case 'message_acked': {
        const ackData = msg.data as {
          message_id: number;
          ack_count: number;
          paths?: MessagePath[];
        };
        handlers.onMessageAcked?.(ackData.message_id, ackData.ack_count, ackData.paths);
        return { type: msg.type, handled: !!handlers.onMessageAcked };
      }
      case 'pong':
        return { type: msg.type, handled: true };
      default:
        return { type: msg.type, handled: false };
    }
  } catch {
    return { type: 'error', handled: false };
  }
}

describe('parseWebSocketMessage', () => {
  it('routes health message to onHealth handler', () => {
    const onHealth = vi.fn();
    const data = JSON.stringify({
      type: 'health',
      data: { radio_connected: true, connection_info: 'Serial: /dev/ttyUSB0' },
    });

    const result = parseWebSocketMessage(data, { onHealth });

    expect(result.type).toBe('health');
    expect(result.handled).toBe(true);
    expect(onHealth).toHaveBeenCalledWith({
      radio_connected: true,
      connection_info: 'Serial: /dev/ttyUSB0',
    });
  });

  it('routes message_acked to onMessageAcked with message ID and ack count', () => {
    const onMessageAcked = vi.fn();
    const data = JSON.stringify({
      type: 'message_acked',
      data: { message_id: 42, ack_count: 3 },
    });

    const result = parseWebSocketMessage(data, { onMessageAcked });

    expect(result.type).toBe('message_acked');
    expect(result.handled).toBe(true);
    expect(onMessageAcked).toHaveBeenCalledWith(42, 3, undefined);
  });

  it('routes message_acked with paths array', () => {
    const onMessageAcked = vi.fn();
    const paths = [
      { path: '1A2B', received_at: 1700000000 },
      { path: '1A3C', received_at: 1700000005 },
    ];
    const data = JSON.stringify({
      type: 'message_acked',
      data: { message_id: 42, ack_count: 2, paths },
    });

    const result = parseWebSocketMessage(data, { onMessageAcked });

    expect(result.type).toBe('message_acked');
    expect(result.handled).toBe(true);
    expect(onMessageAcked).toHaveBeenCalledWith(42, 2, paths);
  });

  it('routes new message to onMessage handler', () => {
    const onMessage = vi.fn();
    const messageData = {
      id: 123,
      type: 'CHAN',
      channel_idx: 0,
      text: 'Hello',
      received_at: 1700000000,
      outgoing: false,
      acked: 0,
    };
    const data = JSON.stringify({ type: 'message', data: messageData });

    const result = parseWebSocketMessage(data, { onMessage });

    expect(result.type).toBe('message');
    expect(result.handled).toBe(true);
    expect(onMessage).toHaveBeenCalledWith(messageData);
  });

  it('handles pong messages silently', () => {
    const data = JSON.stringify({ type: 'pong' });

    const result = parseWebSocketMessage(data, {});

    expect(result.type).toBe('pong');
    expect(result.handled).toBe(true);
  });

  it('returns unhandled for unknown message types', () => {
    const data = JSON.stringify({ type: 'unknown_type', data: {} });

    const result = parseWebSocketMessage(data, {});

    expect(result.type).toBe('unknown_type');
    expect(result.handled).toBe(false);
  });

  it('handles invalid JSON gracefully', () => {
    const data = 'not valid json {';

    const result = parseWebSocketMessage(data, {});

    expect(result.type).toBe('error');
    expect(result.handled).toBe(false);
  });

  it('does not call handler when not provided', () => {
    const data = JSON.stringify({
      type: 'health',
      data: { radio_connected: true },
    });

    const result = parseWebSocketMessage(data, {});

    expect(result.type).toBe('health');
    expect(result.handled).toBe(false);
  });

  it('routes raw_packet to onRawPacket handler', () => {
    const onRawPacket = vi.fn();
    const packetData = {
      id: 1,
      timestamp: 1700000000,
      data: 'deadbeef',
      payload_type: 'GROUP_TEXT',
      decrypted: true,
      decrypted_info: { channel_name: '#test', sender: 'Alice' },
    };
    const data = JSON.stringify({ type: 'raw_packet', data: packetData });

    const result = parseWebSocketMessage(data, { onRawPacket });

    expect(result.type).toBe('raw_packet');
    expect(result.handled).toBe(true);
    expect(onRawPacket).toHaveBeenCalledWith(packetData);
  });
});

describe('useWebSocket ref-based handler pattern', () => {
  /**
   * These tests verify the pattern used in useWebSocket to avoid stale closures.
   * The hook stores handlers in a ref and accesses them through the ref in callbacks.
   * This ensures that when handlers are updated, the WebSocket still calls the latest version.
   */

  it('demonstrates ref pattern prevents stale closure', () => {
    // Simulate the ref pattern used in useWebSocket
    interface Handlers {
      onMessage?: (msg: string) => void;
    }

    // This simulates what the hook does: store handlers in a ref
    const handlersRef: { current: Handlers } = { current: {} };

    // First handler version
    const firstHandler = vi.fn();
    handlersRef.current = { onMessage: firstHandler };

    // Simulate what onmessage does: access handlers through ref
    const processMessage = (data: string) => {
      // This is the pattern: access through ref.current, not closed-over variable
      handlersRef.current.onMessage?.(data);
    };

    // Send first message
    processMessage('message1');
    expect(firstHandler).toHaveBeenCalledWith('message1');

    // Update handler (simulates React re-render with new handler)
    const secondHandler = vi.fn();
    handlersRef.current = { onMessage: secondHandler };

    // Send second message
    processMessage('message2');

    // First handler should NOT be called again (would happen with stale closure)
    expect(firstHandler).toHaveBeenCalledTimes(1);
    // Second handler should be called (ref pattern works)
    expect(secondHandler).toHaveBeenCalledWith('message2');
  });

  it('demonstrates stale closure problem without ref pattern', () => {
    // This demonstrates the bug we fixed - without refs, handlers become stale
    interface Handlers {
      onMessage?: (msg: string) => void;
    }

    // First handler version
    const firstHandler = vi.fn();
    let handlers: Handlers = { onMessage: firstHandler };

    // BAD PATTERN: capture handlers in closure (this is what we fixed)
    const capturedHandlers = handlers;
    const processMessageBad = (data: string) => {
      // This captures `capturedHandlers` at creation time - STALE!
      capturedHandlers.onMessage?.(data);
    };

    // Send first message
    processMessageBad('message1');
    expect(firstHandler).toHaveBeenCalledWith('message1');

    // Update handler
    const secondHandler = vi.fn();
    handlers = { onMessage: secondHandler };

    // Send second message - BUG: still calls first handler!
    processMessageBad('message2');

    // This demonstrates the stale closure bug
    expect(firstHandler).toHaveBeenCalledTimes(2); // Called twice - bug!
    expect(secondHandler).not.toHaveBeenCalled(); // Never called - bug!
  });
});
