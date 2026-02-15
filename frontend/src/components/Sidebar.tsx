import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CONTACT_TYPE_REPEATER,
  type Contact,
  type Channel,
  type Conversation,
  type Favorite,
} from '../types';
import { getStateKey, type ConversationTimes } from '../utils/conversationState';
import { getContactDisplayName } from '../utils/pubkey';
import { ContactAvatar } from './ContactAvatar';
import { isFavorite } from '../utils/favorites';
import { Input } from './ui/input';
import { Button } from './ui/button';
import { cn } from '@/lib/utils';

type SortOrder = 'alpha' | 'recent';

type FavoriteItem = { type: 'channel'; channel: Channel } | { type: 'contact'; contact: Contact };

type ConversationRow = {
  key: string;
  type: 'channel' | 'contact';
  id: string;
  name: string;
  unreadCount: number;
  isMention: boolean;
  contact?: Contact;
};

type CollapseState = {
  favorites: boolean;
  channels: boolean;
  contacts: boolean;
  repeaters: boolean;
};

interface SidebarProps {
  contacts: Contact[];
  channels: Channel[];
  activeConversation: Conversation | null;
  onSelectConversation: (conversation: Conversation) => void;
  onNewMessage: () => void;
  lastMessageTimes: ConversationTimes;
  unreadCounts: Record<string, number>;
  /** Tracks which conversations have unread messages that mention the user */
  mentions: Record<string, boolean>;
  showCracker: boolean;
  crackerRunning: boolean;
  onToggleCracker: () => void;
  onMarkAllRead: () => void;
  favorites: Favorite[];
  /** Sort order from server settings */
  sortOrder?: SortOrder;
  /** Callback when sort order changes */
  onSortOrderChange?: (order: SortOrder) => void;
}

export function Sidebar({
  contacts,
  channels,
  activeConversation,
  onSelectConversation,
  onNewMessage,
  lastMessageTimes,
  unreadCounts,
  mentions,
  showCracker,
  crackerRunning,
  onToggleCracker,
  onMarkAllRead,
  favorites,
  sortOrder: sortOrderProp = 'recent',
  onSortOrderChange,
}: SidebarProps) {
  const sortOrder = sortOrderProp;
  const [searchQuery, setSearchQuery] = useState('');
  const [favoritesCollapsed, setFavoritesCollapsed] = useState(false);
  const [channelsCollapsed, setChannelsCollapsed] = useState(false);
  const [contactsCollapsed, setContactsCollapsed] = useState(false);
  const [repeatersCollapsed, setRepeatersCollapsed] = useState(false);
  const collapseSnapshotRef = useRef<CollapseState | null>(null);

  const handleSortToggle = () => {
    const newOrder = sortOrder === 'alpha' ? 'recent' : 'alpha';
    onSortOrderChange?.(newOrder);
  };

  const handleSelectConversation = (conversation: Conversation) => {
    setSearchQuery('');
    onSelectConversation(conversation);
  };

  const isActive = (type: 'contact' | 'channel' | 'raw' | 'map' | 'visualizer', id: string) =>
    activeConversation?.type === type && activeConversation?.id === id;

  // Get unread count for a conversation
  const getUnreadCount = (type: 'channel' | 'contact', id: string): number => {
    const key = getStateKey(type, id);
    return unreadCounts[key] || 0;
  };

  // Check if a conversation has a mention
  const hasMention = (type: 'channel' | 'contact', id: string): boolean => {
    const key = getStateKey(type, id);
    return mentions[key] || false;
  };

  const getLastMessageTime = useCallback(
    (type: 'channel' | 'contact', id: string) => {
      const key = getStateKey(type, id);
      return lastMessageTimes[key] || 0;
    },
    [lastMessageTimes]
  );

  // Deduplicate channels by name, keeping the first (lowest index)
  const uniqueChannels = useMemo(
    () =>
      channels.reduce<Channel[]>((acc, channel) => {
        if (!acc.some((c) => c.name === channel.name)) {
          acc.push(channel);
        }
        return acc;
      }, []),
    [channels]
  );

  // Deduplicate contacts by public key, preferring ones with names
  // Also filter out any contacts with empty public keys
  const uniqueContacts = useMemo(
    () =>
      contacts
        .filter((c) => c.public_key && c.public_key.length > 0)
        .sort((a, b) => {
          // Sort contacts with names first
          if (a.name && !b.name) return -1;
          if (!a.name && b.name) return 1;
          return (a.name || '').localeCompare(b.name || '');
        })
        .reduce<Contact[]>((acc, contact) => {
          if (!acc.some((c) => c.public_key === contact.public_key)) {
            acc.push(contact);
          }
          return acc;
        }, []),
    [contacts]
  );

  // Sort channels based on sort order, with Public always first
  const sortedChannels = useMemo(
    () =>
      [...uniqueChannels].sort((a, b) => {
        // Public channel always sorts to the top
        if (a.name === 'Public') return -1;
        if (b.name === 'Public') return 1;

        if (sortOrder === 'recent') {
          const timeA = getLastMessageTime('channel', a.key);
          const timeB = getLastMessageTime('channel', b.key);
          if (timeA && timeB) return timeB - timeA;
          if (timeA && !timeB) return -1;
          if (!timeA && timeB) return 1;
        }
        return a.name.localeCompare(b.name);
      }),
    [uniqueChannels, sortOrder, getLastMessageTime]
  );

  const sortContactsByOrder = useCallback(
    (items: Contact[]) =>
      [...items].sort((a, b) => {
        if (sortOrder === 'recent') {
          const timeA = getLastMessageTime('contact', a.public_key);
          const timeB = getLastMessageTime('contact', b.public_key);
          if (timeA && timeB) return timeB - timeA;
          if (timeA && !timeB) return -1;
          if (!timeA && timeB) return 1;
        }
        return (a.name || a.public_key).localeCompare(b.name || b.public_key);
      }),
    [sortOrder, getLastMessageTime]
  );

  // Split non-repeater contacts and repeater contacts into separate sorted lists
  const sortedNonRepeaterContacts = useMemo(
    () => sortContactsByOrder(uniqueContacts.filter((c) => c.type !== CONTACT_TYPE_REPEATER)),
    [uniqueContacts, sortContactsByOrder]
  );

  const sortedRepeaters = useMemo(
    () => sortContactsByOrder(uniqueContacts.filter((c) => c.type === CONTACT_TYPE_REPEATER)),
    [uniqueContacts, sortContactsByOrder]
  );

  // Filter by search query
  const query = searchQuery.toLowerCase().trim();
  const isSearching = query.length > 0;

  const filteredChannels = useMemo(
    () =>
      query
        ? sortedChannels.filter(
            (c) => c.name.toLowerCase().includes(query) || c.key.toLowerCase().includes(query)
          )
        : sortedChannels,
    [sortedChannels, query]
  );

  const filteredNonRepeaterContacts = useMemo(
    () =>
      query
        ? sortedNonRepeaterContacts.filter(
            (c) =>
              c.name?.toLowerCase().includes(query) || c.public_key.toLowerCase().includes(query)
          )
        : sortedNonRepeaterContacts,
    [sortedNonRepeaterContacts, query]
  );

  const filteredRepeaters = useMemo(
    () =>
      query
        ? sortedRepeaters.filter(
            (c) =>
              c.name?.toLowerCase().includes(query) || c.public_key.toLowerCase().includes(query)
          )
        : sortedRepeaters,
    [sortedRepeaters, query]
  );

  // Expand sections while searching; restore prior collapse state when search ends.
  useEffect(() => {
    if (isSearching) {
      if (!collapseSnapshotRef.current) {
        collapseSnapshotRef.current = {
          favorites: favoritesCollapsed,
          channels: channelsCollapsed,
          contacts: contactsCollapsed,
          repeaters: repeatersCollapsed,
        };
      }

      if (favoritesCollapsed || channelsCollapsed || contactsCollapsed || repeatersCollapsed) {
        setFavoritesCollapsed(false);
        setChannelsCollapsed(false);
        setContactsCollapsed(false);
        setRepeatersCollapsed(false);
      }
      return;
    }

    if (collapseSnapshotRef.current) {
      const prev = collapseSnapshotRef.current;
      collapseSnapshotRef.current = null;
      setFavoritesCollapsed(prev.favorites);
      setChannelsCollapsed(prev.channels);
      setContactsCollapsed(prev.contacts);
      setRepeatersCollapsed(prev.repeaters);
    }
  }, [
    isSearching,
    favoritesCollapsed,
    channelsCollapsed,
    contactsCollapsed,
    repeatersCollapsed,
  ]);

  // Separate favorites from regular items, and build combined favorites list
  const { favoriteItems, nonFavoriteChannels, nonFavoriteContacts, nonFavoriteRepeaters } = useMemo(() => {
    const favChannels = filteredChannels.filter((c) => isFavorite(favorites, 'channel', c.key));
    const favContacts = [...filteredNonRepeaterContacts, ...filteredRepeaters].filter((c) =>
      isFavorite(favorites, 'contact', c.public_key)
    );
    const nonFavChannels = filteredChannels.filter((c) => !isFavorite(favorites, 'channel', c.key));
    const nonFavContacts = filteredNonRepeaterContacts.filter(
      (c) => !isFavorite(favorites, 'contact', c.public_key)
    );
    const nonFavRepeaters = filteredRepeaters.filter(
      (c) => !isFavorite(favorites, 'contact', c.public_key)
    );

    const items: FavoriteItem[] = [
      ...favChannels.map((channel) => ({ type: 'channel' as const, channel })),
      ...favContacts.map((contact) => ({ type: 'contact' as const, contact })),
    ].sort((a, b) => {
      const timeA =
        a.type === 'channel'
          ? getLastMessageTime('channel', a.channel.key)
          : getLastMessageTime('contact', a.contact.public_key);
      const timeB =
        b.type === 'channel'
          ? getLastMessageTime('channel', b.channel.key)
          : getLastMessageTime('contact', b.contact.public_key);
      if (timeA && timeB) return timeB - timeA;
      if (timeA && !timeB) return -1;
      if (!timeA && timeB) return 1;
      const nameA = a.type === 'channel' ? a.channel.name : a.contact.name || a.contact.public_key;
      const nameB = b.type === 'channel' ? b.channel.name : b.contact.name || b.contact.public_key;
      return nameA.localeCompare(nameB);
    });

    return {
      favoriteItems: items,
      nonFavoriteChannels: nonFavChannels,
      nonFavoriteContacts: nonFavContacts,
      nonFavoriteRepeaters: nonFavRepeaters,
    };
  }, [
    filteredChannels,
    filteredNonRepeaterContacts,
    filteredRepeaters,
    favorites,
    getLastMessageTime,
  ]);

  const buildChannelRow = (channel: Channel, keyPrefix: string): ConversationRow => ({
    key: `${keyPrefix}-${channel.key}`,
    type: 'channel',
    id: channel.key,
    name: channel.name,
    unreadCount: getUnreadCount('channel', channel.key),
    isMention: hasMention('channel', channel.key),
  });

  const buildContactRow = (contact: Contact, keyPrefix: string): ConversationRow => ({
    key: `${keyPrefix}-${contact.public_key}`,
    type: 'contact',
    id: contact.public_key,
    name: getContactDisplayName(contact.name, contact.public_key),
    unreadCount: getUnreadCount('contact', contact.public_key),
    isMention: hasMention('contact', contact.public_key),
    contact,
  });

  const renderConversationRow = (row: ConversationRow) => (
    <div
      key={row.key}
      className={cn(
        'px-3 py-2.5 cursor-pointer flex items-center gap-2 border-l-2 border-transparent hover:bg-accent',
        isActive(row.type, row.id) && 'bg-accent border-l-primary',
        row.unreadCount > 0 && '[&_.name]:font-bold [&_.name]:text-foreground'
      )}
      onClick={() =>
        handleSelectConversation({
          type: row.type,
          id: row.id,
          name: row.name,
        })
      }
    >
      {row.type === 'contact' && row.contact && (
        <ContactAvatar
          name={row.contact.name}
          publicKey={row.contact.public_key}
          size={24}
          contactType={row.contact.type}
        />
      )}
      <span className="name flex-1 truncate">{row.name}</span>
      {row.unreadCount > 0 && (
        <span
          className={cn(
            'text-[10px] font-semibold px-1.5 py-0.5 rounded-full min-w-[18px] text-center',
            row.isMention
              ? 'bg-destructive text-destructive-foreground'
              : 'bg-primary text-primary-foreground'
          )}
        >
          {row.unreadCount}
        </span>
      )}
    </div>
  );

  const renderSectionHeader = (
    title: string,
    collapsed: boolean,
    onToggle: () => void,
    showSortToggle = false
  ) => {
    const effectiveCollapsed = isSearching ? false : collapsed;

    return (
      <div className="flex justify-between items-center px-3 py-2 pt-3">
        <button
          className={cn(
            'flex items-center gap-1 text-[11px] uppercase text-muted-foreground hover:text-foreground',
            isSearching && 'cursor-default'
          )}
          onClick={() => {
            if (!isSearching) onToggle();
          }}
          title={effectiveCollapsed ? `Expand ${title}` : `Collapse ${title}`}
        >
          <span className="text-[10px]">{effectiveCollapsed ? '▸' : '▾'}</span>
          <span>{title}</span>
        </button>
        {showSortToggle && (
          <button
            className="bg-transparent border border-border text-muted-foreground px-1.5 py-0.5 text-[10px] rounded hover:bg-accent hover:text-foreground"
            onClick={handleSortToggle}
            title={sortOrder === 'alpha' ? 'Sort by recent' : 'Sort alphabetically'}
          >
            {sortOrder === 'alpha' ? 'A-Z' : '⏱'}
          </button>
        )}
      </div>
    );
  };

  return (
    <div className="sidebar w-60 h-full min-h-0 bg-card border-r border-border flex flex-col">
      {/* Header */}
      <div className="flex justify-between items-center px-3 py-3 border-b border-border">
        <h2 className="text-xs uppercase text-muted-foreground font-medium">Conversations</h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={onNewMessage}
          title="New Message"
          className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
        >
          +
        </Button>
      </div>

      {/* Search */}
      <div className="relative px-3 py-2 border-b border-border">
        <Input
          type="text"
          placeholder="Search..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="h-8 text-sm pr-8"
        />
        {searchQuery && (
          <button
            className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-lg leading-none"
            onClick={() => setSearchQuery('')}
            title="Clear search"
          >
            ×
          </button>
        )}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {/* Raw Packet Feed */}
        {!query && (
          <div
            className={cn(
              'px-3 py-2.5 cursor-pointer flex items-center gap-2 border-l-2 border-transparent hover:bg-accent',
              isActive('raw', 'raw') && 'bg-accent border-l-primary'
            )}
            onClick={() =>
              handleSelectConversation({
                type: 'raw',
                id: 'raw',
                name: 'Raw Packet Feed',
              })
            }
          >
            <span className="text-muted-foreground text-xs">📡</span>
            <span className="flex-1 truncate">Packet Feed</span>
          </div>
        )}

        {/* Node Map */}
        {!query && (
          <div
            className={cn(
              'px-3 py-2.5 cursor-pointer flex items-center gap-2 border-l-2 border-transparent hover:bg-accent',
              isActive('map', 'map') && 'bg-accent border-l-primary'
            )}
            onClick={() =>
              handleSelectConversation({
                type: 'map',
                id: 'map',
                name: 'Node Map',
              })
            }
          >
            <span className="text-muted-foreground text-xs">🗺️</span>
            <span className="flex-1 truncate">Node Map</span>
          </div>
        )}

        {/* Mesh Visualizer */}
        {!query && (
          <div
            className={cn(
              'px-3 py-2.5 cursor-pointer flex items-center gap-2 border-l-2 border-transparent hover:bg-accent',
              isActive('visualizer', 'visualizer') && 'bg-accent border-l-primary'
            )}
            onClick={() =>
              handleSelectConversation({
                type: 'visualizer',
                id: 'visualizer',
                name: 'Mesh Visualizer',
              })
            }
          >
            <span className="text-muted-foreground text-xs">✨</span>
            <span className="flex-1 truncate">Mesh Visualizer</span>
          </div>
        )}

        {/* Cracker Toggle */}
        {!query && (
          <div
            className={cn(
              'px-3 py-2.5 cursor-pointer flex items-center gap-2 border-l-2 border-transparent hover:bg-accent',
              showCracker && 'bg-accent border-l-primary'
            )}
            onClick={onToggleCracker}
          >
            <span className="text-muted-foreground text-xs">🔓</span>
            <span className="flex-1 truncate">
              {showCracker ? 'Hide' : 'Show'} Room Finder
              <span
                className={cn(
                  'ml-1 text-xs',
                  crackerRunning ? 'text-green-500' : 'text-muted-foreground'
                )}
              >
                ({crackerRunning ? 'running' : 'idle'})
              </span>
            </span>
          </div>
        )}

        {/* Mark All Read */}
        {!query && Object.keys(unreadCounts).length > 0 && (
          <div
            className="px-3 py-2.5 cursor-pointer flex items-center gap-2 border-l-2 border-transparent hover:bg-accent"
            onClick={onMarkAllRead}
          >
            <span className="text-muted-foreground text-xs">✓</span>
            <span className="flex-1 truncate text-muted-foreground">Mark all as read</span>
          </div>
        )}

        {/* Favorites */}
        {favoriteItems.length > 0 && (
          <>
            {renderSectionHeader(
              'Favorites',
              favoritesCollapsed,
              () => setFavoritesCollapsed((prev) => !prev),
              false
            )}
            {(isSearching || !favoritesCollapsed) &&
              favoriteItems.map((item) =>
                item.type === 'channel'
                  ? renderConversationRow(buildChannelRow(item.channel, 'fav-chan'))
                  : renderConversationRow(buildContactRow(item.contact, 'fav-contact'))
              )}
          </>
        )}

        {/* Channels */}
        {nonFavoriteChannels.length > 0 && (
          <>
            {renderSectionHeader(
              'Channels',
              channelsCollapsed,
              () => setChannelsCollapsed((prev) => !prev),
              true
            )}
            {(isSearching || !channelsCollapsed) &&
              nonFavoriteChannels.map((channel) =>
                renderConversationRow(buildChannelRow(channel, 'chan'))
              )}
          </>
        )}

        {/* Contacts */}
        {nonFavoriteContacts.length > 0 && (
          <>
            {renderSectionHeader(
              'Contacts',
              contactsCollapsed,
              () => setContactsCollapsed((prev) => !prev),
              true
            )}
            {(isSearching || !contactsCollapsed) &&
              nonFavoriteContacts.map((contact) =>
                renderConversationRow(buildContactRow(contact, 'contact'))
              )}
          </>
        )}

        {/* Repeaters */}
        {nonFavoriteRepeaters.length > 0 && (
          <>
            {renderSectionHeader(
              'Repeaters',
              repeatersCollapsed,
              () => setRepeatersCollapsed((prev) => !prev),
              true
            )}
            {(isSearching || !repeatersCollapsed) &&
              nonFavoriteRepeaters.map((contact) =>
                renderConversationRow(buildContactRow(contact, 'repeater'))
              )}
          </>
        )}

        {/* Empty state */}
        {nonFavoriteContacts.length === 0 &&
          nonFavoriteChannels.length === 0 &&
          nonFavoriteRepeaters.length === 0 &&
          favoriteItems.length === 0 && (
            <div className="p-5 text-center text-muted-foreground">
              {query ? 'No matches found' : 'No conversations yet'}
            </div>
          )}
      </div>
    </div>
  );
}
