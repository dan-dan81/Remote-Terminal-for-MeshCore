/**
 * localStorage utilities for managing favorite conversations.
 *
 * Favorites are stored client-side and displayed in a dedicated section
 * above channels in the sidebar, always sorted by most recent message.
 */

const FAVORITES_KEY = 'remoteterm-favorites';

export interface Favorite {
  type: 'channel' | 'contact';
  id: string; // channel key or contact public key
}

/**
 * Load favorites from localStorage
 */
export function loadFavorites(): Favorite[] {
  try {
    const stored = localStorage.getItem(FAVORITES_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

/**
 * Save favorites to localStorage
 */
function saveFavorites(favorites: Favorite[]): void {
  try {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(favorites));
  } catch {
    // localStorage might be full or disabled
  }
}

/**
 * Add a conversation to favorites
 */
export function addFavorite(type: 'channel' | 'contact', id: string): Favorite[] {
  const favorites = loadFavorites();
  // Check if already favorited
  if (favorites.some((f) => f.type === type && f.id === id)) {
    return favorites;
  }
  const updated = [...favorites, { type, id }];
  saveFavorites(updated);
  return updated;
}

/**
 * Remove a conversation from favorites
 */
export function removeFavorite(type: 'channel' | 'contact', id: string): Favorite[] {
  const favorites = loadFavorites();
  const updated = favorites.filter((f) => !(f.type === type && f.id === id));
  saveFavorites(updated);
  return updated;
}

/**
 * Check if a conversation is favorited
 */
export function isFavorite(
  favorites: Favorite[],
  type: 'channel' | 'contact',
  id: string
): boolean {
  return favorites.some((f) => f.type === type && f.id === id);
}

/**
 * Toggle a conversation's favorite status
 */
export function toggleFavorite(type: 'channel' | 'contact', id: string): Favorite[] {
  const favorites = loadFavorites();
  if (favorites.some((f) => f.type === type && f.id === id)) {
    return removeFavorite(type, id);
  }
  return addFavorite(type, id);
}
