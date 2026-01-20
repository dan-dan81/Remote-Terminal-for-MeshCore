import { useEffect, useRef, useMemo } from 'react';
import { MeshCoreDecoder, PayloadType, Utils } from '@michaelhart/meshcore-decoder';
import type { RawPacket } from '../types';

interface RawPacketListProps {
  packets: RawPacket[];
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatSignalInfo(packet: RawPacket): string {
  const parts: string[] = [];
  if (packet.snr !== null && packet.snr !== undefined) {
    parts.push(`SNR: ${packet.snr.toFixed(1)} dB`);
  }
  if (packet.rssi !== null && packet.rssi !== undefined) {
    parts.push(`RSSI: ${packet.rssi} dBm`);
  }
  return parts.join(' | ');
}

// Decrypted info from the packet (validated by backend)
interface DecryptedInfo {
  channel_name: string | null;
  sender: string | null;
}

// Decode a packet and generate a human-readable summary
// Uses backend's decrypted_info when available (validated), falls back to decoder
function decodePacketSummary(
  hexData: string,
  decryptedInfo: DecryptedInfo | null
): {
  summary: string;
  routeType: string;
  details?: string;
} {
  try {
    const decoded = MeshCoreDecoder.decode(hexData);

    if (!decoded.isValid) {
      return { summary: 'Invalid packet', routeType: 'Unknown' };
    }

    const routeType = Utils.getRouteTypeName(decoded.routeType);
    const payloadTypeName = Utils.getPayloadTypeName(decoded.payloadType);

    // Build path string if available
    const pathStr = decoded.path && decoded.path.length > 0 ? ` via ${decoded.path.join('-')}` : '';

    // Generate summary based on payload type
    let summary = payloadTypeName;
    let details: string | undefined;

    switch (decoded.payloadType) {
      case PayloadType.TextMessage: {
        const payload = decoded.payload.decoded as {
          destinationHash?: string;
          sourceHash?: string;
        } | null;
        if (payload?.sourceHash && payload?.destinationHash) {
          summary = `DM from ${payload.sourceHash} to ${payload.destinationHash}${pathStr}`;
        } else {
          summary = `DM${pathStr}`;
        }
        break;
      }

      case PayloadType.GroupText: {
        const payload = decoded.payload.decoded as {
          channelHash?: string;
        } | null;
        // Use backend's validated decrypted_info when available
        if (decryptedInfo?.channel_name) {
          if (decryptedInfo.sender) {
            summary = `GT from ${decryptedInfo.sender} in ${decryptedInfo.channel_name}${pathStr}`;
          } else {
            summary = `GT in ${decryptedInfo.channel_name}${pathStr}`;
          }
        } else if (payload?.channelHash) {
          // Fallback to showing channel hash when not decrypted
          summary = `GT ch:${payload.channelHash}${pathStr}`;
        } else {
          summary = `GroupText${pathStr}`;
        }
        break;
      }

      case PayloadType.Advert: {
        const payload = decoded.payload.decoded as {
          publicKey?: string;
          appData?: { name?: string; deviceRole?: number };
        } | null;
        if (payload?.appData?.name) {
          const role =
            payload.appData.deviceRole !== undefined
              ? Utils.getDeviceRoleName(payload.appData.deviceRole)
              : '';
          summary = `Advert: ${payload.appData.name}${role ? ` (${role})` : ''}${pathStr}`;
        } else if (payload?.publicKey) {
          summary = `Advert: ${payload.publicKey.slice(0, 8)}...${pathStr}`;
        } else {
          summary = `Advert${pathStr}`;
        }
        break;
      }

      case PayloadType.Ack: {
        summary = `ACK${pathStr}`;
        break;
      }

      case PayloadType.Request: {
        summary = `Request${pathStr}`;
        break;
      }

      case PayloadType.Response: {
        summary = `Response${pathStr}`;
        break;
      }

      case PayloadType.Trace: {
        summary = `Trace${pathStr}`;
        break;
      }

      case PayloadType.Path: {
        summary = `Path${pathStr}`;
        break;
      }

      default:
        summary = `${payloadTypeName}${pathStr}`;
    }

    return { summary, routeType, details };
  } catch {
    return { summary: 'Decode error', routeType: 'Unknown' };
  }
}

// Get route type badge color
function getRouteTypeColor(routeType: string): string {
  switch (routeType) {
    case 'Flood':
      return 'bg-blue-500/20 text-blue-400';
    case 'Direct':
      return 'bg-green-500/20 text-green-400';
    case 'Transport Flood':
      return 'bg-purple-500/20 text-purple-400';
    case 'Transport Direct':
      return 'bg-orange-500/20 text-orange-400';
    default:
      return 'bg-gray-500/20 text-gray-400';
  }
}

// Get short route type label
function getRouteTypeLabel(routeType: string): string {
  switch (routeType) {
    case 'Flood':
      return 'F';
    case 'Direct':
      return 'D';
    case 'Transport Flood':
      return 'TF';
    case 'Transport Direct':
      return 'TD';
    default:
      return '?';
  }
}

export function RawPacketList({ packets }: RawPacketListProps) {
  const listRef = useRef<HTMLDivElement>(null);

  // Decode all packets (memoized to avoid re-decoding on every render)
  const decodedPackets = useMemo(() => {
    return packets.map((packet) => ({
      packet,
      decoded: decodePacketSummary(packet.data, packet.decrypted_info),
    }));
  }, [packets]);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [packets]);

  if (packets.length === 0) {
    return (
      <div className="h-full overflow-y-auto p-5 text-center text-muted-foreground">
        No packets received yet. Packets will appear here in real-time.
      </div>
    );
  }

  // Sort packets by timestamp ascending (oldest first)
  const sortedPackets = [...decodedPackets].sort((a, b) => a.packet.timestamp - b.packet.timestamp);

  return (
    <div className="h-full overflow-y-auto p-4 flex flex-col gap-3" ref={listRef}>
      {sortedPackets.map(({ packet, decoded }) => (
        <div key={packet.id} className="py-2 px-3 bg-muted rounded">
          <div className="flex items-center gap-2">
            {/* Route type badge */}
            <span
              className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${getRouteTypeColor(decoded.routeType)}`}
              title={decoded.routeType}
            >
              {getRouteTypeLabel(decoded.routeType)}
            </span>

            {/* Encryption status */}
            {!packet.decrypted && <span title="Encrypted">🔒</span>}

            {/* Summary */}
            <span className={packet.decrypted ? 'text-primary' : 'text-foreground'}>
              {decoded.summary}
            </span>

            {/* Time */}
            <span className="text-muted-foreground ml-auto text-sm">
              {formatTime(packet.timestamp)}
            </span>
          </div>

          {/* Signal info */}
          {(packet.snr !== null || packet.rssi !== null) && (
            <div className="text-[11px] text-muted-foreground mt-0.5">
              {formatSignalInfo(packet)}
            </div>
          )}

          {/* Raw hex data (always visible) */}
          <div className="font-mono text-[10px] break-all text-muted-foreground/70 mt-1 p-1 bg-background/50 rounded">
            {packet.data.toUpperCase()}
          </div>
        </div>
      ))}
    </div>
  );
}
