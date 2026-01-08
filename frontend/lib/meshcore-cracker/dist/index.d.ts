/**
 * MeshCore Cracker - Standalone library for cracking MeshCore GroupText packets
 *
 * @example
 * ```typescript
 * import { GroupTextCracker } from 'meshcore-cracker';
 *
 * const cracker = new GroupTextCracker();
 *
 * // Optional: load wordlist for dictionary attack
 * await cracker.loadWordlist('/words_alpha.txt');
 *
 * const result = await cracker.crack(packetHex, {
 *   maxLength: 6,
 *   useTimestampFilter: true,
 *   useUtf8Filter: true,
 * }, (progress) => {
 *   console.log(`${progress.percent.toFixed(1)}% - ETA: ${progress.etaSeconds}s`);
 * });
 *
 * if (result.found) {
 *   console.log(`Room: #${result.roomName}`);
 *   console.log(`Message: ${result.decryptedMessage}`);
 * }
 *
 * cracker.destroy();
 * ```
 */
export { GroupTextCracker } from './cracker';
export type { CrackOptions, CrackResult, ProgressReport, ProgressCallback, DecodedPacket, } from './types';
export { deriveKeyFromRoomName, getChannelHash, verifyMac, isTimestampValid, isValidUtf8, indexToRoomName, roomNameToIndex, countNamesForLength, PUBLIC_ROOM_NAME, PUBLIC_KEY, } from './core';
export { isWebGpuSupported } from './gpu-bruteforce';
//# sourceMappingURL=index.d.ts.map