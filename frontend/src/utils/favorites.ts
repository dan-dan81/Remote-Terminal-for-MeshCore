/**
 * Favorites utilities.
 *
 * Favorites are now stored server-side in the database.
 * This file provides helper functions for checking favorites
 * and loading legacy localStorage data for migration.
 */

import type { Favorite } from '../types';
import { pubkeysMatch } from './pubkey';

const FAVORITES_KEY = 'remoteterm-favorites';

/**
 * Check if a conversation is favorited (from provided favorites array)
 *
 * For contacts, uses prefix matching to handle full pubkeys vs 12-char prefixes.
 */
export function isFavorite(
  favorites: Favorite[],
  type: 'channel' | 'contact',
  id: string
): boolean {
  return favorites.some((f) => {
    if (f.type !== type) return false;
    // For contacts, use prefix matching (handles full keys vs prefixes)
    if (type === 'contact') return pubkeysMatch(f.id, id);
    // For channels, exact match
    return f.id === id;
  });
}

/**
 * Load favorites from localStorage (for migration only)
 */
export function loadLocalStorageFavorites(): Favorite[] {
  try {
    const stored = localStorage.getItem(FAVORITES_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

/**
 * Clear favorites from localStorage (after migration)
 */
export function clearLocalStorageFavorites(): void {
  try {
    localStorage.removeItem(FAVORITES_KEY);
  } catch {
    // localStorage might be disabled
  }
}

// Re-export the Favorite type for convenience
export type { Favorite };
