import { useEffect, useState, useMemo } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import type { LatLngBoundsExpression } from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { Contact } from '../types';
import { formatTime } from '../utils/messageParser';
import { CONTACT_TYPE_REPEATER } from '../types';

interface MapViewProps {
  contacts: Contact[];
}

// Calculate marker color based on how recently the contact was heard
function getMarkerColor(lastSeen: number): string {
  const now = Date.now() / 1000;
  const age = now - lastSeen;
  const hour = 3600;
  const day = 86400;

  if (age < hour) return '#22c55e'; // Bright green - less than 1 hour
  if (age < day) return '#4ade80'; // Light green - less than 1 day
  if (age < 3 * day) return '#a3e635'; // Yellow-green - less than 3 days
  return '#9ca3af'; // Gray - older (up to 7 days)
}

// Component to handle map bounds fitting
function MapBoundsHandler({ contacts }: { contacts: Contact[] }) {
  const map = useMap();
  const [hasInitialized, setHasInitialized] = useState(false);

  useEffect(() => {
    if (hasInitialized) return;

    const fitToContacts = () => {
      if (contacts.length === 0) {
        // No contacts with location - show world view
        map.setView([20, 0], 2);
        setHasInitialized(true);
        return;
      }

      if (contacts.length === 1) {
        // Single contact - center on it
        map.setView([contacts[0].lat!, contacts[0].lon!], 10);
        setHasInitialized(true);
        return;
      }

      // Multiple contacts - fit bounds
      const bounds: LatLngBoundsExpression = contacts.map(
        (c) => [c.lat!, c.lon!] as [number, number]
      );
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
      setHasInitialized(true);
    };

    // Try geolocation first
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          // Success - center on user location with reasonable zoom
          map.setView([position.coords.latitude, position.coords.longitude], 8);
          setHasInitialized(true);
        },
        () => {
          // Geolocation denied/failed - fit to contacts
          fitToContacts();
        },
        { timeout: 5000, maximumAge: 300000 }
      );
    } else {
      // No geolocation support - fit to contacts
      fitToContacts();
    }
  }, [map, contacts, hasInitialized]);

  return null;
}

export function MapView({ contacts }: MapViewProps) {
  // Filter to contacts with GPS coordinates, heard within the last 7 days
  const mappableContacts = useMemo(() => {
    const sevenDaysAgo = Date.now() / 1000 - 7 * 24 * 60 * 60;
    return contacts.filter(
      (c) => c.lat != null && c.lon != null && c.last_seen != null && c.last_seen > sevenDaysAgo
    );
  }, [contacts]);

  return (
    <div className="flex flex-col h-full">
      {/* Info bar */}
      <div className="px-4 py-2 bg-muted/50 text-xs text-muted-foreground flex items-center justify-between">
        <span>
          Showing {mappableContacts.length} contact{mappableContacts.length !== 1 ? 's' : ''} heard
          in the last 7 days
        </span>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-[#22c55e]" /> &lt;1h
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-[#4ade80]" /> &lt;1d
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-[#a3e635]" /> &lt;3d
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-[#9ca3af]" /> older
          </span>
        </div>
      </div>

      {/* Map - z-index constrained to stay below modals/sheets */}
      <div className="flex-1 relative" style={{ zIndex: 0 }}>
        <MapContainer
          center={[20, 0]}
          zoom={2}
          className="h-full w-full"
          style={{ background: '#1a1a2e' }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MapBoundsHandler contacts={mappableContacts} />

          {mappableContacts.map((contact) => {
            const isRepeater = contact.type === CONTACT_TYPE_REPEATER;
            const color = getMarkerColor(contact.last_seen!);
            const displayName = contact.name || contact.public_key.slice(0, 12);

            return (
              <CircleMarker
                key={contact.public_key}
                center={[contact.lat!, contact.lon!]}
                radius={isRepeater ? 10 : 7}
                pathOptions={{
                  color: isRepeater ? color : '#000',
                  fillColor: color,
                  fillOpacity: 0.8,
                  weight: isRepeater ? 0 : 1,
                }}
              >
                <Popup>
                  <div className="text-sm">
                    <div className="font-medium flex items-center gap-1">
                      {isRepeater && <span title="Repeater">🛜</span>}
                      {displayName}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      Last heard: {formatTime(contact.last_seen!)}
                    </div>
                    <div className="text-xs text-gray-400 mt-1 font-mono">
                      {contact.lat!.toFixed(5)}, {contact.lon!.toFixed(5)}
                    </div>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>
    </div>
  );
}
