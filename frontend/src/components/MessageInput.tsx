import {
  useState,
  useCallback,
  useImperativeHandle,
  forwardRef,
  useRef,
  useMemo,
  type FormEvent,
  type KeyboardEvent,
} from 'react';
import { Input } from './ui/input';
import { Button } from './ui/button';
import { toast } from './ui/sonner';
import { cn } from '@/lib/utils';

// MeshCore message size limits (empirically determined from LoRa packet constraints)
// Direct delivery allows ~156 bytes; multi-hop requires buffer for path growth.
// Channels include "sender: " prefix in the encrypted payload.
const DM_HARD_LIMIT = 156; // Max for direct delivery
const DM_WARNING_THRESHOLD = 140; // Conservative for multi-hop
const CHANNEL_HARD_LIMIT = 156; // Base limit before sender overhead
const CHANNEL_WARNING_THRESHOLD = 120; // Conservative for multi-hop
const CHANNEL_DANGER_BUFFER = 8; // Red zone starts this many chars before hard limit

interface MessageInputProps {
  onSend: (text: string) => Promise<void>;
  disabled: boolean;
  placeholder?: string;
  /** When true, input becomes password field for repeater telemetry */
  isRepeaterMode?: boolean;
  /** Conversation type for character limit calculation */
  conversationType?: 'contact' | 'channel' | 'raw';
  /** Sender name (radio name) for channel message limit calculation */
  senderName?: string;
}

type LimitState = 'normal' | 'warning' | 'danger' | 'error';

export interface MessageInputHandle {
  appendText: (text: string) => void;
}

export const MessageInput = forwardRef<MessageInputHandle, MessageInputProps>(function MessageInput(
  { onSend, disabled, placeholder, isRepeaterMode, conversationType, senderName },
  ref
) {
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useImperativeHandle(ref, () => ({
    appendText: (appendedText: string) => {
      setText((prev) => prev + appendedText);
      // Focus the input after appending
      inputRef.current?.focus();
    },
  }));

  // Calculate character limits based on conversation type
  const limits = useMemo(() => {
    if (conversationType === 'contact') {
      return {
        warningAt: DM_WARNING_THRESHOLD,
        dangerAt: DM_HARD_LIMIT, // Same as hard limit for DMs (no intermediate red zone)
        hardLimit: DM_HARD_LIMIT,
      };
    } else if (conversationType === 'channel') {
      // Channel hard limit = 156 - senderName.length - 2 (for ": " separator)
      const nameLen = senderName?.length ?? 10;
      const hardLimit = Math.max(1, CHANNEL_HARD_LIMIT - nameLen - 2);
      return {
        warningAt: CHANNEL_WARNING_THRESHOLD,
        dangerAt: Math.max(1, hardLimit - CHANNEL_DANGER_BUFFER),
        hardLimit,
      };
    }
    return null; // Raw/other - no limits
  }, [conversationType, senderName]);

  // Determine current limit state
  const { limitState, warningMessage } = useMemo((): {
    limitState: LimitState;
    warningMessage: string | null;
  } => {
    if (!limits) return { limitState: 'normal', warningMessage: null };

    const len = text.length;
    if (len >= limits.hardLimit) {
      return { limitState: 'error', warningMessage: 'likely truncated by radio' };
    }
    if (len >= limits.dangerAt) {
      return { limitState: 'danger', warningMessage: 'may impact multi-repeater hop delivery' };
    }
    if (len >= limits.warningAt) {
      return { limitState: 'warning', warningMessage: 'may impact multi-repeater hop delivery' };
    }
    return { limitState: 'normal', warningMessage: null };
  }, [text.length, limits]);

  const remaining = limits ? limits.hardLimit - text.length : 0;

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const trimmed = text.trim();

      // For repeater mode, allow empty password via "."
      if (isRepeaterMode) {
        if (sending || disabled) return;
        // "." means empty password
        const password = trimmed === '.' ? '' : trimmed;
        setSending(true);
        try {
          await onSend(password);
          setText('');
        } catch (err) {
          console.error('Failed to request telemetry:', err);
          toast.error('Failed to request telemetry', {
            description: err instanceof Error ? err.message : 'Check radio connection',
          });
          return;
        } finally {
          setSending(false);
        }
        // Refocus after React re-enables the input (now in CLI command mode)
        setTimeout(() => inputRef.current?.focus(), 0);
      } else {
        if (!trimmed || sending || disabled) return;
        setSending(true);
        try {
          await onSend(trimmed);
          setText('');
        } catch (err) {
          console.error('Failed to send message:', err);
          toast.error('Failed to send message', {
            description: err instanceof Error ? err.message : 'Check radio connection',
          });
          return;
        } finally {
          setSending(false);
        }
        // Refocus after React re-enables the input
        setTimeout(() => inputRef.current?.focus(), 0);
      }
    },
    [text, sending, disabled, onSend, isRepeaterMode]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit(e as unknown as FormEvent);
      }
    },
    [handleSubmit]
  );

  // For repeater mode, enable submit if there's text OR if it's just "." for empty password
  const canSubmit = isRepeaterMode
    ? text.trim().length > 0 || text === '.'
    : text.trim().length > 0;

  // Show character counter for messages (not repeater mode or raw)
  const showCharCounter = !isRepeaterMode && limits !== null;

  return (
    <form className="px-4 py-3 border-t border-border flex flex-col gap-1" onSubmit={handleSubmit}>
      <div className="flex gap-2">
        <Input
          ref={inputRef}
          type={isRepeaterMode ? 'password' : 'text'}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            placeholder ||
            (isRepeaterMode ? 'Enter password (or . for none)...' : 'Type a message...')
          }
          disabled={disabled || sending}
          className="flex-1 min-w-0"
        />
        <Button
          type="submit"
          disabled={disabled || sending || !canSubmit}
          className="flex-shrink-0"
        >
          {sending
            ? isRepeaterMode
              ? 'Fetching...'
              : 'Sending...'
            : isRepeaterMode
              ? 'Fetch'
              : 'Send'}
        </Button>
      </div>
      {showCharCounter && (
        <div className="flex items-center justify-end gap-2 text-xs">
          <span
            className={cn(
              'tabular-nums',
              limitState === 'error' || limitState === 'danger'
                ? 'text-red-500 font-medium'
                : limitState === 'warning'
                  ? 'text-yellow-500'
                  : 'text-muted-foreground'
            )}
          >
            {text.length}/{limits!.hardLimit}
            {remaining < 0 && ` (${remaining})`}
          </span>
          {warningMessage && (
            <span className={cn(limitState === 'error' ? 'text-red-500' : 'text-yellow-500')}>
              — {warningMessage}
            </span>
          )}
        </div>
      )}
    </form>
  );
});
