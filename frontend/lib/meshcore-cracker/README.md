# MeshCore Cracker

Standalone library for cracking MeshCore GroupText packets using WebGPU-accelerated brute force.

## Features

- WebGPU-accelerated brute force (100M+ keys/second on modern GPUs)
- Dictionary attack support with external wordlist
- Configurable timestamp and UTF-8 filters
- Progress callbacks with ETA
- Resume support for interrupted searches
- Clean ESM API

## Installation

```bash
npm install meshcore-cracker
```

## Usage

### Basic Usage

```typescript
import { GroupTextCracker } from 'meshcore-cracker';

const cracker = new GroupTextCracker();

const result = await cracker.crack(packetHex, {
  maxLength: 6,
});

if (result.found) {
  console.log(`Room: #${result.roomName}`);
  console.log(`Key: ${result.key}`);
  console.log(`Message: ${result.decryptedMessage}`);
}

cracker.destroy();
```

### With Progress Callback

```typescript
const result = await cracker.crack(packetHex, {
  maxLength: 8,
  useTimestampFilter: true,
  useUtf8Filter: true,
}, (progress) => {
  console.log(`Progress: ${progress.percent.toFixed(1)}%`);
  console.log(`Rate: ${(progress.rateKeysPerSec / 1e6).toFixed(2)} Mkeys/s`);
  console.log(`ETA: ${progress.etaSeconds.toFixed(0)}s`);
  console.log(`Phase: ${progress.phase}`);
});
```

### With Dictionary Attack

```typescript
const cracker = new GroupTextCracker();

// Load wordlist from URL
await cracker.loadWordlist('/words_alpha.txt');

// Or set wordlist directly
cracker.setWordlist(['test', 'hello', 'world']);

const result = await cracker.crack(packetHex, { maxLength: 6 });
```

### Aborting and Resuming

```typescript
const cracker = new GroupTextCracker();

// Start cracking (in background)
const crackPromise = cracker.crack(packetHex, { maxLength: 8 }, (progress) => {
  // Abort after 10 seconds
  if (progress.elapsedSeconds > 10) {
    cracker.abort();
  }
});

const result = await crackPromise;

if (result.aborted && result.resumeFrom) {
  // Resume later from where we left off
  const resumed = await cracker.crack(packetHex, {
    maxLength: 8,
    startFrom: result.resumeFrom,
  });
}
```

## API Reference

### GroupTextCracker

Main class for cracking GroupText packets.

#### Methods

##### `crack(packetHex, options?, onProgress?): Promise<CrackResult>`

Crack a GroupText packet to find the room name and decrypt the message.

**Parameters:**
- `packetHex: string` - The packet data as a hex string
- `options?: CrackOptions` - Cracking options
- `onProgress?: ProgressCallback` - Optional progress callback

**Returns:** `Promise<CrackResult>`

##### `loadWordlist(url: string): Promise<void>`

Load a wordlist from a URL for dictionary attacks.

##### `setWordlist(words: string[]): void`

Set the wordlist directly from an array.

##### `abort(): void`

Abort the current cracking operation.

##### `isGpuAvailable(): boolean`

Check if WebGPU is available.

##### `destroy(): void`

Clean up GPU resources.

### CrackOptions

```typescript
interface CrackOptions {
  maxLength?: number;           // Max room name length (default: 8)
  useTimestampFilter?: boolean; // Filter old timestamps (default: true)
  useUtf8Filter?: boolean;      // Filter invalid UTF-8 (default: true)
  startFrom?: string;           // Resume from position
}
```

### CrackResult

```typescript
interface CrackResult {
  found: boolean;
  roomName?: string;          // Room name without '#'
  key?: string;               // Encryption key (hex)
  decryptedMessage?: string;  // Decrypted message
  aborted?: boolean;          // Was operation aborted
  resumeFrom?: string;        // Position for resume
  error?: string;             // Error message
}
```

### ProgressReport

```typescript
interface ProgressReport {
  checked: number;           // Candidates checked
  total: number;             // Total candidates
  percent: number;           // Progress 0-100
  rateKeysPerSec: number;    // Current rate
  etaSeconds: number;        // Estimated time remaining
  elapsedSeconds: number;    // Time elapsed
  currentLength: number;     // Current room name length
  currentPosition: string;   // Current position
  phase: 'public-key' | 'wordlist' | 'bruteforce';
}
```

## Utility Functions

For advanced usage, the library also exports utility functions:

```typescript
import {
  deriveKeyFromRoomName,  // Derive key from room name
  getChannelHash,         // Get channel hash from key
  verifyMac,              // Verify MAC
  isTimestampValid,       // Check timestamp validity
  isValidUtf8,            // Check UTF-8 validity
  indexToRoomName,        // Convert index to room name
  roomNameToIndex,        // Convert room name to index
  countNamesForLength,    // Count names for a length
  isWebGpuSupported,      // Check WebGPU support
  PUBLIC_ROOM_NAME,       // "[[public room]]"
  PUBLIC_KEY,             // Public room key
} from 'meshcore-cracker';
```

## Browser Requirements

- WebGPU support (Chrome 113+, Edge 113+, or other Chromium-based browsers)
- Falls back gracefully with an error if WebGPU is not available

## Performance

Typical performance on modern hardware:
- **GPU (RTX 3080)**: ~500M keys/second
- **GPU (integrated)**: ~50M keys/second

Search space by room name length:
| Length | Candidates | Time @ 100M/s |
|--------|------------|---------------|
| 1 | 36 | instant |
| 2 | 1,296 | instant |
| 3 | 47,952 | instant |
| 4 | 1,774,224 | <1s |
| 5 | 65,646,288 | <1s |
| 6 | 2,428,912,656 | ~24s |
| 7 | 89,869,768,272 | ~15min |
| 8 | 3,325,181,426,064 | ~9h |

## License

MIT
