import { useState, useCallback, useEffect, useRef } from 'react';
import { api, UNREAD_FETCH_LIMIT } from '../api';
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
  markConversationRead: (conv: Conversation) => void;
  trackNewMessage: (msg: Message) => void;
}

/** Check if a message text contains a mention of the given name in @[name] format */
function messageContainsMention(text: string, name: string | null): boolean {
  if (!name) return false;
  // Escape special regex characters in the name
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const mentionPattern = new RegExp(`@\\[${escaped}\\]`, 'i');
  return mentionPattern.test(text);
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

  // Track which channels/contacts we've already fetched unreads for
  const fetchedChannels = useRef<Set<string>>(new Set());
  const fetchedContacts = useRef<Set<string>>(new Set());

  // Fetch messages and count unreads for new channels/contacts
  // Uses server-side last_read_at for consistent read state across devices
  useEffect(() => {
    const newChannels = channels.filter((c) => !fetchedChannels.current.has(c.key));
    const newContacts = contacts.filter(
      (c) => c.public_key && !fetchedContacts.current.has(c.public_key)
    );

    if (newChannels.length === 0 && newContacts.length === 0) return;

    // Mark as fetched before starting (to avoid duplicate fetches if effect re-runs)
    newChannels.forEach((c) => fetchedChannels.current.add(c.key));
    newContacts.forEach((c) => fetchedContacts.current.add(c.public_key));

    const fetchAndCountUnreads = async () => {
      const conversations: Array<{ type: 'PRIV' | 'CHAN'; conversation_key: string }> = [
        ...newChannels.map((c) => ({ type: 'CHAN' as const, conversation_key: c.key })),
        ...newContacts.map((c) => ({ type: 'PRIV' as const, conversation_key: c.public_key })),
      ];

      if (conversations.length === 0) return;

      try {
        const bulkMessages = await api.getMessagesBulk(conversations, UNREAD_FETCH_LIMIT);
        const newUnreadCounts: Record<string, number> = {};
        const newMentions: Record<string, boolean> = {};
        const newLastMessageTimes: Record<string, number> = {};

        // Process channel messages - use server-side last_read_at
        for (const channel of newChannels) {
          const msgs = bulkMessages[`CHAN:${channel.key}`] || [];
          if (msgs.length > 0) {
            const key = getStateKey('channel', channel.key);
            // Use server-side last_read_at, fallback to 0 if never read
            const lastRead = channel.last_read_at || 0;

            const unreadMsgs = msgs.filter((m) => !m.outgoing && m.received_at > lastRead);
            if (unreadMsgs.length > 0) {
              newUnreadCounts[key] = unreadMsgs.length;
              // Check if any unread message mentions the user
              if (unreadMsgs.some((m) => messageContainsMention(m.text, myNameRef.current))) {
                newMentions[key] = true;
              }
            }

            const latestTime = Math.max(...msgs.map((m) => m.received_at));
            newLastMessageTimes[key] = latestTime;
            setLastMessageTime(key, latestTime);
          }
        }

        // Process contact messages - use server-side last_read_at
        for (const contact of newContacts) {
          const msgs = bulkMessages[`PRIV:${contact.public_key}`] || [];
          if (msgs.length > 0) {
            const key = getStateKey('contact', contact.public_key);
            // Use server-side last_read_at, fallback to 0 if never read
            const lastRead = contact.last_read_at || 0;

            const unreadMsgs = msgs.filter((m) => !m.outgoing && m.received_at > lastRead);
            if (unreadMsgs.length > 0) {
              newUnreadCounts[key] = unreadMsgs.length;
              // Check if any unread message mentions the user
              if (unreadMsgs.some((m) => messageContainsMention(m.text, myNameRef.current))) {
                newMentions[key] = true;
              }
            }

            const latestTime = Math.max(...msgs.map((m) => m.received_at));
            newLastMessageTimes[key] = latestTime;
            setLastMessageTime(key, latestTime);
          }
        }

        if (Object.keys(newUnreadCounts).length > 0) {
          setUnreadCounts((prev) => ({ ...prev, ...newUnreadCounts }));
        }
        if (Object.keys(newMentions).length > 0) {
          setMentions((prev) => ({ ...prev, ...newMentions }));
        }
        setLastMessageTimes(getLastMessageTimes());
      } catch (err) {
        console.error('Failed to fetch messages bulk:', err);
      }
    };

    fetchAndCountUnreads();
  }, [channels, contacts]);

  // Mark conversation as read when user views it
  // Calls server API to persist read state across devices
  useEffect(() => {
    if (
      activeConversation &&
      activeConversation.type !== 'raw' &&
      activeConversation.type !== 'map'
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

  // Mark a specific conversation as read
  // Calls server API to persist read state across devices
  const markConversationRead = useCallback((conv: Conversation) => {
    if (conv.type === 'raw' || conv.type === 'map') return;

    const key = getStateKey(conv.type as 'channel' | 'contact', conv.id);

    // Update local state immediately
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

    // Persist to server (fire-and-forget)
    if (conv.type === 'channel') {
      api.markChannelRead(conv.id).catch((err) => {
        console.error('Failed to mark channel as read on server:', err);
      });
    } else if (conv.type === 'contact') {
      api.markContactRead(conv.id).catch((err) => {
        console.error('Failed to mark contact as read on server:', err);
      });
    }
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
    markConversationRead,
    trackNewMessage,
  };
}
