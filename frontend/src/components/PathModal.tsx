import type { Contact, RadioConfig } from '../types';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from './ui/dialog';
import { Button } from './ui/button';
import {
  resolvePath,
  calculateDistance,
  isValidLocation,
  type SenderInfo,
  type ResolvedPath,
  type PathHop,
} from '../utils/pathUtils';

interface PathModalProps {
  open: boolean;
  onClose: () => void;
  path: string;
  senderInfo: SenderInfo;
  contacts: Contact[];
  config: RadioConfig | null;
}

export function PathModal({ open, onClose, path, senderInfo, contacts, config }: PathModalProps) {
  const resolved = resolvePath(path, senderInfo, contacts, config);

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-w-md max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Message Path</DialogTitle>
          <DialogDescription>
            This shows <em>one route</em> that this message traveled through the mesh network. Flood
            messages may arrive via multiple paths, and routers may be incorrectly identified due to
            prefix collisions between heard and non-heard router advertisements.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto py-2">
          <PathVisualization resolved={resolved} />
        </div>

        <DialogFooter>
          <Button onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface PathVisualizationProps {
  resolved: ResolvedPath;
}

function PathVisualization({ resolved }: PathVisualizationProps) {
  // Track previous location for each hop to calculate distances
  // Returns null if previous hop was ambiguous or has invalid location
  const getPrevLocation = (hopIndex: number): { lat: number | null; lon: number | null } | null => {
    if (hopIndex === 0) {
      // Check if sender has valid location
      if (!isValidLocation(resolved.sender.lat, resolved.sender.lon)) {
        return null;
      }
      return { lat: resolved.sender.lat, lon: resolved.sender.lon };
    }
    const prevHop = resolved.hops[hopIndex - 1];
    // If previous hop was ambiguous, we can't show meaningful distances
    if (prevHop.matches.length > 1) {
      return null;
    }
    // If previous hop was unknown, we also can't calculate
    if (prevHop.matches.length === 0) {
      return null;
    }
    // Check if previous hop has valid location
    if (isValidLocation(prevHop.matches[0].lat, prevHop.matches[0].lon)) {
      return { lat: prevHop.matches[0].lat, lon: prevHop.matches[0].lon };
    }
    return null;
  };

  return (
    <div className="space-y-0">
      {/* Sender */}
      <PathNode
        label="Sender"
        name={resolved.sender.name}
        prefix={resolved.sender.prefix}
        distance={null}
        isFirst
      />

      {/* Hops */}
      {resolved.hops.map((hop, index) => (
        <HopNode
          key={index}
          hop={hop}
          hopNumber={index + 1}
          prevLocation={getPrevLocation(index)}
        />
      ))}

      {/* Receiver */}
      <PathNode
        label="Receiver (me)"
        name={resolved.receiver.name}
        prefix={resolved.receiver.prefix}
        distance={calculateReceiverDistance(resolved)}
        isLast
      />

      {/* Total distance */}
      {resolved.totalDistances && resolved.totalDistances.length > 0 && (
        <div className="pt-3 mt-3 border-t border-border">
          <span className="text-sm text-muted-foreground">
            Presumed unambiguous distance covered:{' '}
          </span>
          <span className="text-sm font-medium">{formatDistance(resolved.totalDistances[0])}</span>
        </div>
      )}
    </div>
  );
}

interface PathNodeProps {
  label: string;
  name: string;
  prefix: string;
  distance: number | null;
  isFirst?: boolean;
  isLast?: boolean;
}

function PathNode({ label, name, prefix, distance, isFirst, isLast }: PathNodeProps) {
  return (
    <div className="flex gap-3">
      {/* Vertical line and dot column */}
      <div className="flex flex-col items-center w-4 flex-shrink-0">
        {!isFirst && <div className="w-0.5 h-3 bg-border" />}
        <div className="w-3 h-3 rounded-full bg-primary flex-shrink-0" />
        {!isLast && <div className="w-0.5 flex-1 bg-border" />}
      </div>

      {/* Content */}
      <div className="pb-3 flex-1 min-w-0">
        <div className="text-xs text-muted-foreground font-medium">{label}</div>
        <div className="font-medium truncate">
          {name} <span className="text-muted-foreground font-mono text-sm">({prefix})</span>
        </div>
        {distance !== null && (
          <div className="text-xs text-muted-foreground">{formatDistance(distance)}</div>
        )}
      </div>
    </div>
  );
}

interface HopNodeProps {
  hop: PathHop;
  hopNumber: number;
  prevLocation: { lat: number | null; lon: number | null } | null;
}

function HopNode({ hop, hopNumber, prevLocation }: HopNodeProps) {
  const isAmbiguous = hop.matches.length > 1;
  const isUnknown = hop.matches.length === 0;

  // Calculate distance from previous location for a contact
  // Returns null if prev location unknown/ambiguous or contact has no valid location
  const getDistanceForContact = (contact: {
    lat: number | null;
    lon: number | null;
  }): number | null => {
    if (!prevLocation || prevLocation.lat === null || prevLocation.lon === null) {
      return null;
    }
    // Check if contact has valid location
    if (!isValidLocation(contact.lat, contact.lon)) {
      return null;
    }
    return calculateDistance(prevLocation.lat, prevLocation.lon, contact.lat, contact.lon);
  };

  return (
    <div className="flex gap-3">
      {/* Vertical line and dot column */}
      <div className="flex flex-col items-center w-4 flex-shrink-0">
        <div className="w-0.5 h-3 bg-border" />
        <div className="w-3 h-3 rounded-full bg-muted-foreground flex-shrink-0" />
        <div className="w-0.5 flex-1 bg-border" />
      </div>

      {/* Content */}
      <div className="pb-3 flex-1 min-w-0">
        <div className="text-xs text-muted-foreground font-medium">
          Hop {hopNumber}
          {isAmbiguous && <span className="text-yellow-500 ml-1">(ambiguous)</span>}
        </div>

        {isUnknown ? (
          <div className="font-medium text-muted-foreground/70">
            &lt;UNKNOWN <span className="font-mono text-sm">{hop.prefix}</span>&gt;
          </div>
        ) : isAmbiguous ? (
          <div>
            {hop.matches.map((contact) => {
              const dist = getDistanceForContact(contact);
              return (
                <div key={contact.public_key} className="font-medium truncate">
                  {contact.name || contact.public_key.slice(0, 12)}{' '}
                  <span className="text-muted-foreground font-mono text-sm">
                    ({contact.public_key.slice(0, 2).toUpperCase()})
                  </span>
                  {dist !== null && (
                    <span className="text-xs text-muted-foreground ml-1">
                      - {formatDistance(dist)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="font-medium truncate">
            {hop.matches[0].name || hop.matches[0].public_key.slice(0, 12)}{' '}
            <span className="text-muted-foreground font-mono text-sm">({hop.prefix})</span>
            {hop.distanceFromPrev !== null && (
              <span className="text-xs text-muted-foreground ml-1">
                - {formatDistance(hop.distanceFromPrev)}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function formatDistance(km: number): string {
  if (km < 1) {
    return `${Math.round(km * 1000)}m`;
  }
  return `${km.toFixed(1)}km`;
}

function calculateReceiverDistance(resolved: ResolvedPath): number | null {
  // Get last hop's location (if any)
  let prevLat: number | null = null;
  let prevLon: number | null = null;

  if (resolved.hops.length > 0) {
    const lastHop = resolved.hops[resolved.hops.length - 1];
    // Only use last hop if it's unambiguous and has valid location
    if (
      lastHop.matches.length === 1 &&
      isValidLocation(lastHop.matches[0].lat, lastHop.matches[0].lon)
    ) {
      prevLat = lastHop.matches[0].lat;
      prevLon = lastHop.matches[0].lon;
    }
  } else {
    // No hops, calculate from sender to receiver (if sender has valid location)
    if (isValidLocation(resolved.sender.lat, resolved.sender.lon)) {
      prevLat = resolved.sender.lat;
      prevLon = resolved.sender.lon;
    }
  }

  if (prevLat === null || prevLon === null) {
    return null;
  }

  // Check receiver has valid location
  if (!isValidLocation(resolved.receiver.lat, resolved.receiver.lon)) {
    return null;
  }

  return calculateDistance(prevLat, prevLon, resolved.receiver.lat, resolved.receiver.lon);
}
