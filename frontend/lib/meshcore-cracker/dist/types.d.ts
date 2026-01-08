/**
 * Options for configuring the cracking process.
 */
export interface CrackOptions {
    /**
     * Maximum room name length to search (default: 8).
     * Longer names exponentially increase search time.
     */
    maxLength?: number;
    /**
     * Filter results by timestamp validity (default: true).
     * When enabled, rejects results where the decrypted timestamp
     * is more than 30 days old.
     */
    useTimestampFilter?: boolean;
    /**
     * Filter results by UTF-8 validity (default: true).
     * When enabled, rejects results containing invalid UTF-8 sequences.
     */
    useUtf8Filter?: boolean;
    /**
     * Resume cracking from a specific room name position.
     * Useful for resuming interrupted searches.
     */
    startFrom?: string;
}
/**
 * Progress information reported during cracking.
 */
export interface ProgressReport {
    /** Total candidates checked so far */
    checked: number;
    /** Total candidates to check */
    total: number;
    /** Progress percentage (0-100) */
    percent: number;
    /** Current cracking rate in keys/second */
    rateKeysPerSec: number;
    /** Estimated time remaining in seconds */
    etaSeconds: number;
    /** Time elapsed since start in seconds */
    elapsedSeconds: number;
    /** Current room name length being tested */
    currentLength: number;
    /** Current room name position being tested */
    currentPosition: string;
    /** Current phase of cracking */
    phase: 'public-key' | 'wordlist' | 'bruteforce';
}
/**
 * Callback function for progress updates.
 * Called approximately 5 times per second during cracking.
 */
export type ProgressCallback = (report: ProgressReport) => void;
/**
 * Result of a cracking operation.
 */
export interface CrackResult {
    /** Whether a matching room name was found */
    found: boolean;
    /** The room name (without '#' prefix) if found */
    roomName?: string;
    /** The derived encryption key (hex) if found */
    key?: string;
    /** The decrypted message content if found */
    decryptedMessage?: string;
    /** Whether the operation was aborted */
    aborted?: boolean;
    /** Position to resume from if aborted or failed */
    resumeFrom?: string;
    /** Error message if an error occurred */
    error?: string;
}
/**
 * Decoded packet information extracted from a MeshCore GroupText packet.
 */
export interface DecodedPacket {
    /** Channel hash (1 byte, hex) */
    channelHash: string;
    /** Encrypted ciphertext (hex) */
    ciphertext: string;
    /** MAC for verification (2 bytes, hex) */
    cipherMac: string;
    /** Whether this is a GroupText packet */
    isGroupText: boolean;
}
//# sourceMappingURL=types.d.ts.map