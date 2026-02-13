import { useState, useCallback, useEffect, useRef } from 'react';
import { api } from '../api';
import {
  getLastMessageTimes,
  setLastMessageTime,
  getStateKey,
  type ConversationTimes,
} from '../utils/conversationState';
import type { Channel, Contact, Conversation, Message } from '../types';

export interface UseUnreadCountsResult {
  unreadCounts: Record<string, number>;
  /** Tracks which conversations have unread messages that mention the user */
  mentions: Record<string, boolean>;
  lastMessageTimes: ConversationTimes;
  incrementUnread: (stateKey: string, hasMention?: boolean) => void;
  markAllRead: () => void;
  trackNewMessage: (msg: Message) => void;
}

export function useUnreadCounts(
  channels: Channel[],
  contacts: Contact[],
  activeConversation: Conversation | null,
  myName: string | null = null
): UseUnreadCountsResult {
  const [unreadCounts, setUnreadCounts] = useState<Record<string, number>>({});
  const [mentions, setMentions] = useState<Record<string, boolean>>({});
  const [lastMessageTimes, setLastMessageTimes] = useState<ConversationTimes>(getLastMessageTimes);

  // Keep myName in a ref so callbacks always have current value
  const myNameRef = useRef(myName);
  useEffect(() => {
    myNameRef.current = myName;
  }, [myName]);

  // Fetch unreads from the server-side endpoint
  const fetchUnreads = useCallback(async () => {
    try {
      const data = await api.getUnreads(myNameRef.current ?? undefined);

      // Replace (not merge) — server counts are authoritative
      setUnreadCounts(data.counts);
      setMentions(data.mentions);

      if (Object.keys(data.last_message_times).length > 0) {
        // Update in-memory cache and state
        for (const [key, ts] of Object.entries(data.last_message_times)) {
          setLastMessageTime(key, ts);
        }
        setLastMessageTimes(getLastMessageTimes());
      }
    } catch (err) {
      console.error('Failed to fetch unreads:', err);
    }
  }, []);

  // Fetch when the number of channels/contacts changes (e.g. initial load,
  // sync, create/delete).  Using .length avoids refiring on every WebSocket
  // contact-update that merely mutates an existing entry's fields.
  const channelsLen = channels.length;
  const contactsLen = contacts.length;
  useEffect(() => {
    if (channelsLen === 0 && contactsLen === 0) return;
    fetchUnreads();
  }, [channelsLen, contactsLen, fetchUnreads]);

  // Mark conversation as read when user views it
  // Calls server API to persist read state across devices
  useEffect(() => {
    if (
      activeConversation &&
      activeConversation.type !== 'raw' &&
      activeConversation.type !== 'map' &&
      activeConversation.type !== 'visualizer'
    ) {
      const key = getStateKey(
        activeConversation.type as 'channel' | 'contact',
        activeConversation.id
      );

      // Update local state immediately for responsive UI
      setUnreadCounts((prev) => {
        if (prev[key]) {
          const next = { ...prev };
          delete next[key];
          return next;
        }
        return prev;
      });

      // Also clear mentions for this conversation
      setMentions((prev) => {
        if (prev[key]) {
          const next = { ...prev };
          delete next[key];
          return next;
        }
        return prev;
      });

      // Persist to server (fire-and-forget, errors logged but not blocking)
      if (activeConversation.type === 'channel') {
        api.markChannelRead(activeConversation.id).catch((err) => {
          console.error('Failed to mark channel as read on server:', err);
        });
      } else if (activeConversation.type === 'contact') {
        api.markContactRead(activeConversation.id).catch((err) => {
          console.error('Failed to mark contact as read on server:', err);
        });
      }
    }
  }, [activeConversation]);

  // Increment unread count for a conversation
  const incrementUnread = useCallback((stateKey: string, hasMention?: boolean) => {
    setUnreadCounts((prev) => ({
      ...prev,
      [stateKey]: (prev[stateKey] || 0) + 1,
    }));
    if (hasMention) {
      setMentions((prev) => ({
        ...prev,
        [stateKey]: true,
      }));
    }
  }, []);

  // Mark all conversations as read
  // Calls single bulk API endpoint to persist read state
  const markAllRead = useCallback(() => {
    // Update local state immediately
    setUnreadCounts({});
    setMentions({});

    // Persist to server with single bulk request
    api.markAllRead().catch((err) => {
      console.error('Failed to mark all as read on server:', err);
    });
  }, []);

  // Track a new incoming message for unread counts
  const trackNewMessage = useCallback((msg: Message) => {
    let conversationKey: string | null = null;
    if (msg.type === 'CHAN' && msg.conversation_key) {
      conversationKey = getStateKey('channel', msg.conversation_key);
    } else if (msg.type === 'PRIV' && msg.conversation_key) {
      conversationKey = getStateKey('contact', msg.conversation_key);
    }

    if (conversationKey) {
      const timestamp = msg.received_at || Math.floor(Date.now() / 1000);
      const updated = setLastMessageTime(conversationKey, timestamp);
      setLastMessageTimes(updated);
    }
  }, []);

  return {
    unreadCounts,
    mentions,
    lastMessageTimes,
    incrementUnread,
    markAllRead,
    trackNewMessage,
  };
}
