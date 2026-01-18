/**
 * Airtime/duty cycle tracking for repeaters.
 *
 * When "dutycycle_start" command is issued, this captures baseline telemetry
 * and polls every 5 minutes to display rolling airtime/duty cycle statistics.
 */

import { useRef, useCallback, useEffect } from 'react';
import { api } from '../api';
import type { Message, TelemetryResponse } from '../types';

// Baseline telemetry snapshot for airtime tracking
interface AirtimeBaseline {
  startTime: number; // epoch seconds
  uptime: number;
  txAirtime: number;
  rxAirtime: number;
  sentFlood: number;
  sentDirect: number;
  recvFlood: number;
  recvDirect: number;
  conversationId: string;
}

// Polling interval: 5 minutes
const AIRTIME_POLL_INTERVAL_MS = 5 * 60 * 1000;

// Format duration in XhXmXs format
function formatAirtimeDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  return `${hours}h${mins}m${secs}s`;
}

// Get emoji indicator for TX duty cycle percentage
function getTxDutyCycleEmoji(pct: number): string {
  if (pct <= 5) return '✅';
  if (pct <= 10) return '🟢';
  if (pct <= 25) return '🟡';
  if (pct <= 50) return '🔴';
  return '🚨';
}

// Format airtime statistics comparing current telemetry to baseline
function formatAirtimeStats(baseline: AirtimeBaseline, current: TelemetryResponse): string {
  const now = Math.floor(Date.now() / 1000);
  const wallDuration = now - baseline.startTime;

  // Compute deltas
  const deltaUptime = current.uptime_seconds - baseline.uptime;
  const deltaTxAirtime = current.airtime_seconds - baseline.txAirtime;
  const deltaRxAirtime = current.rx_airtime_seconds - baseline.rxAirtime;
  const deltaSentFlood = current.sent_flood - baseline.sentFlood;
  const deltaSentDirect = current.sent_direct - baseline.sentDirect;
  const deltaRecvFlood = current.recv_flood - baseline.recvFlood;
  const deltaRecvDirect = current.recv_direct - baseline.recvDirect;

  // Calculate airtime percentages
  const txPct = deltaUptime > 0 ? (deltaTxAirtime / deltaUptime) * 100 : 0;
  const rxPct = deltaUptime > 0 ? (deltaRxAirtime / deltaUptime) * 100 : 0;

  // Estimate flood/direct airtime breakdown based on packet proportions
  const totalSent = deltaSentFlood + deltaSentDirect;
  const totalRecv = deltaRecvFlood + deltaRecvDirect;

  const txFloodPct = totalSent > 0 ? txPct * (deltaSentFlood / totalSent) : 0;
  const txDirectPct = totalSent > 0 ? txPct * (deltaSentDirect / totalSent) : 0;
  const rxFloodPct = totalRecv > 0 ? rxPct * (deltaRecvFlood / totalRecv) : 0;
  const rxDirectPct = totalRecv > 0 ? rxPct * (deltaRecvDirect / totalRecv) : 0;

  const txEmoji = getTxDutyCycleEmoji(txPct);
  const idlePct = Math.max(0, 100 - txPct - rxPct);

  const lines = [
    `Airtime/Duty Cycle Statistics`,
    `Duration: ${formatAirtimeDuration(wallDuration)} (uptime delta: ${formatAirtimeDuration(deltaUptime)})`,
    ``,
    `${txEmoji} TX Airtime: ${txPct.toFixed(3)}% (${totalSent.toLocaleString()} pkts)`,
    `  Flood: ${txFloodPct.toFixed(3)}% (${deltaSentFlood.toLocaleString()} pkts)`,
    `  Direct: ${txDirectPct.toFixed(3)}% (${deltaSentDirect.toLocaleString()} pkts)`,
    ``,
    `RX Airtime: ${rxPct.toFixed(3)}% (${totalRecv.toLocaleString()} pkts)`,
    `  Flood: ${rxFloodPct.toFixed(3)}% (${deltaRecvFlood.toLocaleString()} pkts)`,
    `  Direct: ${rxDirectPct.toFixed(3)}% (${deltaRecvDirect.toLocaleString()} pkts)`,
    ``,
    `Idle: ${idlePct.toFixed(3)}%`,
  ];

  return lines.join('\n');
}

// Create a local message object (not persisted to database)
function createLocalMessage(conversationKey: string, text: string, outgoing: boolean): Message {
  const now = Math.floor(Date.now() / 1000);
  return {
    id: -Date.now(),
    type: 'PRIV',
    conversation_key: conversationKey,
    text,
    sender_timestamp: now,
    received_at: now,
    path_len: null,
    txt_type: 0,
    signature: null,
    outgoing,
    acked: 1,
  };
}

export interface UseAirtimeTrackingResult {
  /** Returns true if this was an airtime command that was handled */
  handleAirtimeCommand: (command: string, conversationId: string) => Promise<boolean>;
  /** Stop any active airtime tracking */
  stopTracking: () => void;
}

export function useAirtimeTracking(
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
): UseAirtimeTrackingResult {
  const baselineRef = useRef<AirtimeBaseline | null>(null);
  const intervalRef = useRef<number | null>(null);

  // Stop tracking and clear interval
  const stopTracking = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    baselineRef.current = null;
  }, []);

  // Poll for airtime stats with one retry on failure
  const pollAirtimeStats = useCallback(async () => {
    const baseline = baselineRef.current;
    if (!baseline) return;

    let telemetry: TelemetryResponse | null = null;
    let lastError: Error | null = null;

    // Try up to 2 times (initial + 1 retry)
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        telemetry = await api.requestTelemetry(baseline.conversationId, '');
        break; // Success, exit loop
      } catch (err) {
        lastError = err instanceof Error ? err : new Error('Unknown error');
        // Wait a moment before retry
        if (attempt === 0) {
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      }
    }

    if (telemetry) {
      const statsMessage = createLocalMessage(
        baseline.conversationId,
        formatAirtimeStats(baseline, telemetry),
        false
      );
      setMessages((prev) => [...prev, statsMessage]);
    } else {
      const errorMessage = createLocalMessage(
        baseline.conversationId,
        `Duty cycle poll failed after retry: ${lastError?.message ?? 'Unknown error'}`,
        false
      );
      setMessages((prev) => [...prev, errorMessage]);
    }
  }, [setMessages]);

  // Handle airtime commands
  const handleAirtimeCommand = useCallback(
    async (command: string, conversationId: string): Promise<boolean> => {
      const cmd = command.trim().toLowerCase();

      if (cmd === 'dutycycle_start') {
        // Stop any existing tracking
        stopTracking();

        // Fetch initial telemetry with one retry
        let telemetry: TelemetryResponse | null = null;
        let lastError: Error | null = null;

        for (let attempt = 0; attempt < 2; attempt++) {
          try {
            telemetry = await api.requestTelemetry(conversationId, '');
            break;
          } catch (err) {
            lastError = err instanceof Error ? err : new Error('Unknown error');
            if (attempt === 0) {
              await new Promise((resolve) => setTimeout(resolve, 2000));
            }
          }
        }

        if (!telemetry) {
          const errorMessage = createLocalMessage(
            conversationId,
            `Failed to start duty cycle tracking after retry: ${lastError?.message ?? 'Unknown error'}`,
            false
          );
          setMessages((prev) => [...prev, errorMessage]);
          return true;
        }

        // Store baseline
        const now = Math.floor(Date.now() / 1000);
        baselineRef.current = {
          startTime: now,
          uptime: telemetry.uptime_seconds,
          txAirtime: telemetry.airtime_seconds,
          rxAirtime: telemetry.rx_airtime_seconds,
          sentFlood: telemetry.sent_flood,
          sentDirect: telemetry.sent_direct,
          recvFlood: telemetry.recv_flood,
          recvDirect: telemetry.recv_direct,
          conversationId,
        };

        // Add start message
        const startMessage = createLocalMessage(
          conversationId,
          `Airtime/duty cycle statistics gathering begins at ${now}. Logs will follow every 5 minutes. To stop, run dutycycle_stop or navigate away from this conversation.`,
          false
        );
        setMessages((prev) => [...prev, startMessage]);

        // Start polling interval
        intervalRef.current = window.setInterval(pollAirtimeStats, AIRTIME_POLL_INTERVAL_MS);

        return true;
      }

      if (cmd === 'dutycycle_stop') {
        if (baselineRef.current && baselineRef.current.conversationId === conversationId) {
          // Do one final poll before stopping
          await pollAirtimeStats();

          stopTracking();

          const stopMessage = createLocalMessage(
            conversationId,
            'Airtime/duty cycle statistics gathering stopped.',
            false
          );
          setMessages((prev) => [...prev, stopMessage]);
        } else {
          const notRunningMessage = createLocalMessage(
            conversationId,
            'Duty cycle tracking is not active.',
            false
          );
          setMessages((prev) => [...prev, notRunningMessage]);
        }
        return true;
      }

      return false; // Not an airtime command
    },
    [setMessages, stopTracking, pollAirtimeStats]
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  return {
    handleAirtimeCommand,
    stopTracking,
  };
}
