/**
 * Favorites utilities.
 *
 * Favorites are now stored server-side in the database.
 * This file provides helper functions for checking favorites
 * and loading legacy localStorage data for migration.
 */

import type { Favorite } from '../types';

const FAVORITES_KEY = 'remoteterm-favorites';

/**
 * Check if a conversation is favorited (from provided favorites array)
 */
export function isFavorite(
  favorites: Favorite[],
  type: 'channel' | 'contact',
  id: string
): boolean {
  return favorites.some((f) => f.type === type && f.id === id);
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
