export declare const CHARS = "abcdefghijklmnopqrstuvwxyz0123456789";
export declare const CHARS_LEN: number;
export declare const CHARS_WITH_DASH: string;
export declare const PUBLIC_ROOM_NAME = "[[public room]]";
export declare const PUBLIC_KEY = "8b3387e9c5cdea6ac9e5edbaa115cd72";
/**
 * Convert room name to (length, index) for resuming/skipping.
 * Index encoding: LSB-first (first character = least significant digit).
 */
export declare function roomNameToIndex(name: string): {
    length: number;
    index: number;
} | null;
/**
 * Convert (length, index) to room name.
 * Index encoding: LSB-first (first character = least significant digit).
 */
export declare function indexToRoomName(length: number, idx: number): string | null;
/**
 * Derive 128-bit key from room name using SHA256.
 * Room names are prefixed with '#' before hashing.
 */
export declare function deriveKeyFromRoomName(roomName: string): string;
/**
 * Compute channel hash (first byte of SHA256(key)).
 */
export declare function getChannelHash(keyHex: string): string;
/**
 * Verify MAC using HMAC-SHA256 with 32-byte padded key.
 */
export declare function verifyMac(ciphertext: string, cipherMac: string, keyHex: string): boolean;
/**
 * Count valid room names for a given length.
 * Accounts for dash rules (no start/end dash, no consecutive dashes).
 */
export declare function countNamesForLength(len: number): number;
/**
 * Check if timestamp is within last month.
 */
export declare function isTimestampValid(timestamp: number, now?: number): boolean;
/**
 * Check for valid UTF-8 (no replacement characters).
 */
export declare function isValidUtf8(text: string): boolean;
/**
 * Room name generator - iterates through all valid room names.
 */
export declare class RoomNameGenerator {
    private length;
    private indices;
    private done;
    private currentInLength;
    private totalForLength;
    current(): string;
    getLength(): number;
    getCurrentInLength(): number;
    getTotalForLength(): number;
    getRemainingInLength(): number;
    isDone(): boolean;
    next(): boolean;
    private isValid;
    nextValid(): boolean;
    skipTo(targetLength: number, targetIndex: number): void;
}
//# sourceMappingURL=core.d.ts.map