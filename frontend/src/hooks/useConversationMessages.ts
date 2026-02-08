import { useState, useCallback, useEffect, useRef } from 'react';
import { toast } from '../components/ui/sonner';
import { api, isAbortError } from '../api';
import * as messageCache from '../messageCache';
import type { Conversation, Message, MessagePath } from '../types';

const MESSAGE_PAGE_SIZE = 200;

// Generate a key for deduplicating messages by content
export function getMessageContentKey(msg: Message): string {
  return `${msg.type}-${msg.conversation_key}-${msg.text}-${msg.sender_timestamp}`;
}

export interface UseConversationMessagesResult {
  messages: Message[];
  messagesLoading: boolean;
  loadingOlder: boolean;
  hasOlderMessages: boolean;
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  fetchMessages: (showLoading?: boolean) => Promise<void>;
  fetchOlderMessages: () => Promise<void>;
  addMessageIfNew: (msg: Message) => boolean;
  updateMessageAck: (messageId: number, ackCount: number, paths?: MessagePath[]) => void;
}

export function useConversationMessages(
  activeConversation: Conversation | null
): UseConversationMessagesResult {
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasOlderMessages, setHasOlderMessages] = useState(false);

  // Track seen message content for deduplication
  const seenMessageContent = useRef<Set<string>>(new Set());

  // AbortController for cancelling in-flight requests on conversation change
  const abortControllerRef = useRef<AbortController | null>(null);

  // Ref to track the conversation ID being fetched to prevent stale responses
  const fetchingConversationIdRef = useRef<string | null>(null);

  // --- Cache integration refs ---
  // Keep refs in sync with state so we can read current values in the switch effect
  const messagesRef = useRef<Message[]>([]);
  const hasOlderMessagesRef = useRef(false);
  const prevConversationIdRef = useRef<string | null>(null);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    hasOlderMessagesRef.current = hasOlderMessages;
  }, [hasOlderMessages]);

  // Fetch messages for active conversation
  // Note: This is called manually and from the useEffect. The useEffect handles
  // cancellation via AbortController; manual calls (e.g., after sending a message)
  // don't need cancellation.
  const fetchMessages = useCallback(
    async (showLoading = false, signal?: AbortSignal) => {
      if (!activeConversation || activeConversation.type === 'raw') {
        setMessages([]);
        setHasOlderMessages(false);
        return;
      }

      // Track which conversation we're fetching for
      const conversationId = activeConversation.id;

      if (showLoading) {
        setMessagesLoading(true);
        // Clear messages first so MessageList resets scroll state for new conversation
        setMessages([]);
      }
      try {
        const data = await api.getMessages(
          {
            type: activeConversation.type === 'channel' ? 'CHAN' : 'PRIV',
            conversation_key: activeConversation.id,
            limit: MESSAGE_PAGE_SIZE,
          },
          signal
        );

        // Check if this response is still for the current conversation
        // This handles the race where the conversation changed while awaiting
        if (fetchingConversationIdRef.current !== conversationId) {
          // Stale response - conversation changed while we were fetching
          return;
        }

        setMessages(data);
        // Track seen content for new messages
        seenMessageContent.current.clear();
        for (const msg of data) {
          seenMessageContent.current.add(getMessageContentKey(msg));
        }
        // If we got a full page, there might be more
        setHasOlderMessages(data.length >= MESSAGE_PAGE_SIZE);
      } catch (err) {
        // Don't show error toast for aborted requests (user switched conversations)
        if (isAbortError(err)) {
          return;
        }
        console.error('Failed to fetch messages:', err);
        toast.error('Failed to load messages', {
          description: err instanceof Error ? err.message : 'Check your connection',
        });
      } finally {
        if (showLoading) {
          setMessagesLoading(false);
        }
      }
    },
    [activeConversation]
  );

  // Fetch older messages (cursor-based pagination)
  const fetchOlderMessages = useCallback(async () => {
    if (
      !activeConversation ||
      activeConversation.type === 'raw' ||
      loadingOlder ||
      !hasOlderMessages
    )
      return;

    // Get the oldest message as cursor for the next page
    const oldestMessage = messages[messages.length - 1];
    if (!oldestMessage) return;

    setLoadingOlder(true);
    try {
      const data = await api.getMessages({
        type: activeConversation.type === 'channel' ? 'CHAN' : 'PRIV',
        conversation_key: activeConversation.id,
        limit: MESSAGE_PAGE_SIZE,
        before: oldestMessage.received_at,
        before_id: oldestMessage.id,
      });

      if (data.length > 0) {
        // Prepend older messages (they come sorted DESC, so older are at the end)
        setMessages((prev) => [...prev, ...data]);
        // Track seen content
        for (const msg of data) {
          seenMessageContent.current.add(getMessageContentKey(msg));
        }
      }
      // If we got less than a full page, no more messages
      setHasOlderMessages(data.length >= MESSAGE_PAGE_SIZE);
    } catch (err) {
      console.error('Failed to fetch older messages:', err);
      toast.error('Failed to load older messages', {
        description: err instanceof Error ? err.message : 'Check your connection',
      });
    } finally {
      setLoadingOlder(false);
    }
  }, [activeConversation, loadingOlder, hasOlderMessages, messages]);

  // Background reconciliation: silently fetch from backend after a cache restore
  // and only update state if something differs (missed WS message, stale ack, etc.).
  // No-ops on the happy path — zero rerenders when cache is already consistent.
  function reconcileFromBackend(conversation: Conversation, signal: AbortSignal) {
    const conversationId = conversation.id;
    api
      .getMessages(
        {
          type: conversation.type === 'channel' ? 'CHAN' : 'PRIV',
          conversation_key: conversationId,
          limit: MESSAGE_PAGE_SIZE,
        },
        signal
      )
      .then((data) => {
        // Stale check — conversation may have changed while awaiting
        if (fetchingConversationIdRef.current !== conversationId) return;

        const merged = messageCache.reconcile(messagesRef.current, data);
        if (!merged) return; // Cache was consistent — no rerender

        setMessages(merged);
        seenMessageContent.current.clear();
        for (const msg of merged) {
          seenMessageContent.current.add(getMessageContentKey(msg));
        }
        if (data.length >= MESSAGE_PAGE_SIZE) {
          setHasOlderMessages(true);
        }
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        // Silent failure — we already have cached data
        console.debug('Background reconciliation failed:', err);
      });
  }

  // Fetch messages when conversation changes, with proper cancellation and caching
  useEffect(() => {
    // Abort any previous in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Save outgoing conversation to cache (if it had messages loaded)
    const prevId = prevConversationIdRef.current;
    if (prevId && messagesRef.current.length > 0) {
      messageCache.set(prevId, {
        messages: messagesRef.current,
        seenContent: new Set(seenMessageContent.current),
        hasOlderMessages: hasOlderMessagesRef.current,
      });
    }

    // Track which conversation we're now on
    const newId = activeConversation?.id ?? null;
    fetchingConversationIdRef.current = newId;
    prevConversationIdRef.current = newId;

    // Clear state for new conversation
    if (!activeConversation || activeConversation.type === 'raw') {
      setMessages([]);
      setHasOlderMessages(false);
      return;
    }

    // Create AbortController for this conversation's fetch (cache reconcile or full fetch)
    const controller = new AbortController();
    abortControllerRef.current = controller;

    // Check cache for the new conversation
    const cached = messageCache.get(activeConversation.id);
    if (cached) {
      // Restore from cache instantly — no spinner
      setMessages(cached.messages);
      seenMessageContent.current = new Set(cached.seenContent);
      setHasOlderMessages(cached.hasOlderMessages);
      setMessagesLoading(false);
      // Silently reconcile with backend in case we missed a WS message
      reconcileFromBackend(activeConversation, controller.signal);
    } else {
      // Not cached — full fetch with spinner
      fetchMessages(true, controller.signal);
    }

    // Cleanup: abort request if conversation changes or component unmounts
    return () => {
      controller.abort();
    };
    // NOTE: Intentionally omitting fetchMessages and activeConversation from deps:
    // - fetchMessages is recreated when activeConversation changes, which would cause infinite loops
    // - activeConversation object identity changes on every render; we only care about id/type
    // - We use fetchingConversationIdRef and AbortController to handle stale responses safely
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConversation?.id, activeConversation?.type]);

  // Add a message if it's new (deduplication)
  // Returns true if the message was added, false if it was a duplicate
  const addMessageIfNew = useCallback((msg: Message): boolean => {
    const contentKey = getMessageContentKey(msg);
    if (seenMessageContent.current.has(contentKey)) {
      console.debug('Duplicate message content ignored:', contentKey.slice(0, 50));
      return false;
    }
    seenMessageContent.current.add(contentKey);

    // Limit set size to prevent memory issues (keep last 500)
    if (seenMessageContent.current.size > 1000) {
      const entries = Array.from(seenMessageContent.current);
      seenMessageContent.current = new Set(entries.slice(-500));
    }

    setMessages((prev) => {
      if (prev.some((m) => m.id === msg.id)) {
        return prev;
      }
      return [...prev, msg];
    });

    return true;
  }, []);

  // Update a message's ack count and paths
  const updateMessageAck = useCallback(
    (messageId: number, ackCount: number, paths?: MessagePath[]) => {
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === messageId);
        if (idx >= 0) {
          const updated = [...prev];
          updated[idx] = {
            ...prev[idx],
            acked: ackCount,
            ...(paths !== undefined && { paths }),
          };
          return updated;
        }
        return prev;
      });
    },
    []
  );

  return {
    messages,
    messagesLoading,
    loadingOlder,
    hasOlderMessages,
    setMessages,
    fetchMessages,
    fetchOlderMessages,
    addMessageIfNew,
    updateMessageAck,
  };
}
