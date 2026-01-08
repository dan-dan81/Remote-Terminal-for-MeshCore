/**
 * GroupTextCracker - Standalone MeshCore GroupText packet cracker
 *
 * Cracks encrypted GroupText packets by trying room names until the
 * correct encryption key is found.
 */
import { MeshCorePacketDecoder, ChannelCrypto } from '@michaelhart/meshcore-decoder';
import { GpuBruteForce, isWebGpuSupported } from './gpu-bruteforce';
import { PUBLIC_ROOM_NAME, PUBLIC_KEY, indexToRoomName, roomNameToIndex, deriveKeyFromRoomName, getChannelHash, verifyMac, countNamesForLength, isTimestampValid, isValidUtf8, } from './core';
// Valid room name characters (for wordlist filtering)
const VALID_CHARS = /^[a-z0-9-]+$/;
const NO_DASH_AT_ENDS = /^[a-z0-9].*[a-z0-9]$|^[a-z0-9]$/;
const NO_CONSECUTIVE_DASHES = /--/;
function isValidRoomName(name) {
    if (!name || name.length === 0)
        return false;
    if (!VALID_CHARS.test(name))
        return false;
    if (name.length > 1 && !NO_DASH_AT_ENDS.test(name))
        return false;
    if (NO_CONSECUTIVE_DASHES.test(name))
        return false;
    return true;
}
/**
 * Main cracker class for MeshCore GroupText packets.
 */
export class GroupTextCracker {
    constructor() {
        this.gpuInstance = null;
        this.wordlist = [];
        this.abortFlag = false;
        this.useTimestampFilter = true;
        this.useUtf8Filter = true;
    }
    /**
     * Load a wordlist from a URL for dictionary attacks.
     * The wordlist should be a text file with one word per line.
     *
     * @param url - URL to fetch the wordlist from
     */
    async loadWordlist(url) {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Failed to load wordlist: ${response.status} ${response.statusText}`);
        }
        const text = await response.text();
        const allWords = text
            .split('\n')
            .map((w) => w.trim().toLowerCase())
            .filter((w) => w.length > 0);
        // Filter to valid room names only
        this.wordlist = allWords.filter(isValidRoomName);
    }
    /**
     * Set the wordlist directly from an array of words.
     *
     * @param words - Array of room names to try
     */
    setWordlist(words) {
        this.wordlist = words
            .map((w) => w.trim().toLowerCase())
            .filter(isValidRoomName);
    }
    /**
     * Abort the current cracking operation.
     * The crack() method will return with aborted: true.
     */
    abort() {
        this.abortFlag = true;
    }
    /**
     * Check if WebGPU is available in the current environment.
     */
    isGpuAvailable() {
        return isWebGpuSupported();
    }
    /**
     * Decode a packet and extract the information needed for cracking.
     *
     * @param packetHex - The packet data as a hex string
     * @returns Decoded packet info or null if not a GroupText packet
     */
    async decodePacket(packetHex) {
        const cleanHex = packetHex.trim().replace(/\s+/g, '').replace(/^0x/i, '');
        if (!cleanHex || !/^[0-9a-fA-F]+$/.test(cleanHex)) {
            return null;
        }
        try {
            const decoded = await MeshCorePacketDecoder.decodeWithVerification(cleanHex, {});
            const payload = decoded.payload?.decoded;
            if (!payload?.channelHash || !payload?.ciphertext || !payload?.cipherMac) {
                return null;
            }
            return {
                channelHash: payload.channelHash,
                ciphertext: payload.ciphertext,
                cipherMac: payload.cipherMac,
                isGroupText: true,
            };
        }
        catch {
            return null;
        }
    }
    /**
     * Crack a GroupText packet to find the room name and decrypt the message.
     *
     * @param packetHex - The packet data as a hex string
     * @param options - Cracking options
     * @param onProgress - Optional callback for progress updates
     * @returns The cracking result
     */
    async crack(packetHex, options, onProgress) {
        this.abortFlag = false;
        this.useTimestampFilter = options?.useTimestampFilter ?? true;
        this.useUtf8Filter = options?.useUtf8Filter ?? true;
        const maxLength = options?.maxLength ?? 8;
        // Decode packet
        const decoded = await this.decodePacket(packetHex);
        if (!decoded) {
            return { found: false, error: 'Invalid packet or not a GroupText packet' };
        }
        const { channelHash, ciphertext, cipherMac } = decoded;
        const targetHashByte = parseInt(channelHash, 16);
        // Initialize GPU if not already done
        if (!this.gpuInstance) {
            this.gpuInstance = new GpuBruteForce();
            const gpuOk = await this.gpuInstance.init();
            if (!gpuOk) {
                return { found: false, error: 'WebGPU not available' };
            }
        }
        const startTime = performance.now();
        let totalChecked = 0;
        let lastProgressUpdate = performance.now();
        // Determine starting position
        let startFromLength = 1;
        let startFromOffset = 0;
        if (options?.startFrom) {
            const pos = roomNameToIndex(options.startFrom);
            if (pos) {
                startFromLength = pos.length;
                startFromOffset = pos.index + 1; // Start after the given position
                if (startFromOffset >= countNamesForLength(startFromLength)) {
                    startFromLength++;
                    startFromOffset = 0;
                }
            }
        }
        // Calculate total candidates for progress
        let totalCandidates = 0;
        for (let l = startFromLength; l <= maxLength; l++) {
            totalCandidates += countNamesForLength(l);
        }
        totalCandidates -= startFromOffset;
        // Helper to report progress
        const reportProgress = (phase, currentLength, currentPosition) => {
            if (!onProgress)
                return;
            const now = performance.now();
            const elapsed = (now - startTime) / 1000;
            const rate = elapsed > 0 ? Math.round(totalChecked / elapsed) : 0;
            const remaining = totalCandidates - totalChecked;
            const eta = rate > 0 ? remaining / rate : 0;
            onProgress({
                checked: totalChecked,
                total: totalCandidates,
                percent: totalCandidates > 0 ? Math.min(100, (totalChecked / totalCandidates) * 100) : 0,
                rateKeysPerSec: rate,
                etaSeconds: eta,
                elapsedSeconds: elapsed,
                currentLength,
                currentPosition,
                phase,
            });
        };
        // Helper to verify MAC and filters
        const verifyMacAndFilters = (key) => {
            if (!verifyMac(ciphertext, cipherMac, key)) {
                return { valid: false };
            }
            const result = ChannelCrypto.decryptGroupTextMessage(ciphertext, cipherMac, key);
            if (!result.success || !result.data) {
                return { valid: false };
            }
            if (this.useTimestampFilter && !isTimestampValid(result.data.timestamp)) {
                return { valid: false };
            }
            if (this.useUtf8Filter && !isValidUtf8(result.data.message)) {
                return { valid: false };
            }
            return { valid: true, message: result.data.message };
        };
        // Phase 1: Try public key
        if (startFromLength === 1 && startFromOffset === 0) {
            reportProgress('public-key', 0, PUBLIC_ROOM_NAME);
            const publicChannelHash = getChannelHash(PUBLIC_KEY);
            if (channelHash === publicChannelHash) {
                const result = verifyMacAndFilters(PUBLIC_KEY);
                if (result.valid) {
                    return {
                        found: true,
                        roomName: PUBLIC_ROOM_NAME,
                        key: PUBLIC_KEY,
                        decryptedMessage: result.message,
                    };
                }
            }
        }
        // Phase 2: Dictionary attack
        if (this.wordlist.length > 0 && startFromLength === 1 && startFromOffset === 0) {
            for (let i = 0; i < this.wordlist.length; i++) {
                if (this.abortFlag) {
                    return {
                        found: false,
                        aborted: true,
                        resumeFrom: this.wordlist[i],
                    };
                }
                const word = this.wordlist[i];
                const key = deriveKeyFromRoomName('#' + word);
                const wordChannelHash = getChannelHash(key);
                if (parseInt(wordChannelHash, 16) === targetHashByte) {
                    const result = verifyMacAndFilters(key);
                    if (result.valid) {
                        return {
                            found: true,
                            roomName: word,
                            key,
                            decryptedMessage: result.message,
                        };
                    }
                }
                // Progress update
                const now = performance.now();
                if (now - lastProgressUpdate >= 200) {
                    reportProgress('wordlist', word.length, word);
                    lastProgressUpdate = now;
                    await new Promise((resolve) => setTimeout(resolve, 0));
                }
            }
        }
        // Phase 3: GPU brute force
        const INITIAL_BATCH_SIZE = 32768;
        const TARGET_DISPATCH_MS = 1000;
        let currentBatchSize = INITIAL_BATCH_SIZE;
        let batchSizeTuned = false;
        for (let length = startFromLength; length <= maxLength; length++) {
            if (this.abortFlag) {
                const resumePos = indexToRoomName(length, 0);
                return {
                    found: false,
                    aborted: true,
                    resumeFrom: resumePos || undefined,
                };
            }
            const totalForLength = countNamesForLength(length);
            let offset = length === startFromLength ? startFromOffset : 0;
            while (offset < totalForLength) {
                if (this.abortFlag) {
                    const resumePos = indexToRoomName(length, offset);
                    return {
                        found: false,
                        aborted: true,
                        resumeFrom: resumePos || undefined,
                    };
                }
                const batchSize = Math.min(currentBatchSize, totalForLength - offset);
                const dispatchStart = performance.now();
                const matches = await this.gpuInstance.runBatch(targetHashByte, length, offset, batchSize, ciphertext, cipherMac);
                const dispatchTime = performance.now() - dispatchStart;
                totalChecked += batchSize;
                // Auto-tune batch size
                if (!batchSizeTuned && batchSize >= INITIAL_BATCH_SIZE && dispatchTime > 0) {
                    const scaleFactor = TARGET_DISPATCH_MS / dispatchTime;
                    const optimalBatchSize = Math.round(batchSize * scaleFactor);
                    const rounded = Math.pow(2, Math.round(Math.log2(Math.max(INITIAL_BATCH_SIZE, optimalBatchSize))));
                    currentBatchSize = Math.max(INITIAL_BATCH_SIZE, rounded);
                    batchSizeTuned = true;
                }
                // Check matches
                for (const matchIdx of matches) {
                    const roomName = indexToRoomName(length, matchIdx);
                    if (!roomName)
                        continue;
                    const key = deriveKeyFromRoomName('#' + roomName);
                    const result = verifyMacAndFilters(key);
                    if (result.valid) {
                        return {
                            found: true,
                            roomName,
                            key,
                            decryptedMessage: result.message,
                        };
                    }
                }
                offset += batchSize;
                // Progress update
                const now = performance.now();
                if (now - lastProgressUpdate >= 200) {
                    const currentPos = indexToRoomName(length, Math.min(offset, totalForLength - 1)) || '';
                    reportProgress('bruteforce', length, currentPos);
                    lastProgressUpdate = now;
                    await new Promise((resolve) => setTimeout(resolve, 0));
                }
            }
        }
        // Not found
        const lastPos = indexToRoomName(maxLength, countNamesForLength(maxLength) - 1);
        return {
            found: false,
            resumeFrom: lastPos || undefined,
        };
    }
    /**
     * Clean up GPU resources.
     * Call this when you're done using the cracker.
     */
    destroy() {
        if (this.gpuInstance) {
            this.gpuInstance.destroy();
            this.gpuInstance = null;
        }
    }
}
//# sourceMappingURL=cracker.js.map