/**
 * Consume prefetched API promises started in index.html before React loaded.
 *
 * Each key is consumed at most once — the first caller gets the promise,
 * subsequent callers get undefined and should fall back to a normal fetch.
 */

import type { AppSettings, Channel, Contact, RadioConfig, UnreadCounts } from './types';

interface PrefetchMap {
  config?: Promise<RadioConfig>;
  settings?: Promise<AppSettings>;
  channels?: Promise<Channel[]>;
  contacts?: Promise<Contact[]>;
  unreads?: Promise<UnreadCounts>;
  undecryptedCount?: Promise<{ count: number }>;
}

const store: PrefetchMap = (window as unknown as { __prefetch?: PrefetchMap }).__prefetch ?? {};

/** Take a prefetched promise (consumed once, then gone). */
export function takePrefetch<K extends keyof PrefetchMap>(key: K): PrefetchMap[K] {
  const p = store[key];
  delete store[key];
  return p;
}
