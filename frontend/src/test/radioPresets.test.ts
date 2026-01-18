import { describe, it, expect } from 'vitest';

// Radio presets - duplicated from SettingsModal for testing
// In a real app, these would be in a shared constants file
interface RadioPreset {
  name: string;
  freq: number;
  bw: number;
  sf: number;
  cr: number;
}

const RADIO_PRESETS: RadioPreset[] = [
  { name: 'USA/Canada', freq: 910.525, bw: 62.5, sf: 7, cr: 5 },
  { name: 'Australia', freq: 915.8, bw: 250, sf: 10, cr: 5 },
  { name: 'Australia (narrow)', freq: 916.575, bw: 62.5, sf: 7, cr: 8 },
  { name: 'Australia SA, WA', freq: 923.125, bw: 62.5, sf: 8, cr: 8 },
  { name: 'Australia QLD', freq: 923.125, bw: 62.5, sf: 8, cr: 5 },
  { name: 'New Zealand', freq: 917.375, bw: 250, sf: 11, cr: 5 },
  { name: 'New Zealand (narrow)', freq: 917.375, bw: 62.5, sf: 7, cr: 5 },
  { name: 'EU/UK/Switzerland Long Range', freq: 869.525, bw: 250, sf: 11, cr: 5 },
  { name: 'EU/UK/Switzerland Medium Range', freq: 869.525, bw: 250, sf: 10, cr: 5 },
  { name: 'EU/UK/Switzerland Narrow', freq: 869.618, bw: 62.5, sf: 8, cr: 8 },
  { name: 'Czech Republic (Narrow)', freq: 869.432, bw: 62.5, sf: 7, cr: 5 },
  { name: 'EU 433MHz Long Range', freq: 433.65, bw: 250, sf: 11, cr: 5 },
  { name: 'Portugal 433MHz', freq: 433.375, bw: 62.5, sf: 9, cr: 6 },
  { name: 'Portugal 868MHz', freq: 869.618, bw: 62.5, sf: 7, cr: 6 },
  { name: 'Vietnam', freq: 920.25, bw: 250, sf: 11, cr: 5 },
];

// Preset detection function - matches the logic in SettingsModal
function detectPreset(freq: number, bw: number, sf: number, cr: number): string {
  for (const preset of RADIO_PRESETS) {
    if (preset.freq === freq && preset.bw === bw && preset.sf === sf && preset.cr === cr) {
      return preset.name;
    }
  }
  return 'custom';
}

// Find preset by name
function findPreset(name: string): RadioPreset | undefined {
  return RADIO_PRESETS.find((p) => p.name === name);
}

describe('Radio Presets', () => {
  describe('detectPreset', () => {
    it('detects USA/Canada preset', () => {
      expect(detectPreset(910.525, 62.5, 7, 5)).toBe('USA/Canada');
    });

    it('detects Australia preset', () => {
      expect(detectPreset(915.8, 250, 10, 5)).toBe('Australia');
    });

    it('detects Australia (narrow) preset', () => {
      expect(detectPreset(916.575, 62.5, 7, 8)).toBe('Australia (narrow)');
    });

    it('detects EU/UK/Switzerland Long Range preset', () => {
      expect(detectPreset(869.525, 250, 11, 5)).toBe('EU/UK/Switzerland Long Range');
    });

    it('detects EU/UK/Switzerland Medium Range preset', () => {
      expect(detectPreset(869.525, 250, 10, 5)).toBe('EU/UK/Switzerland Medium Range');
    });

    it('detects EU/UK/Switzerland Narrow preset', () => {
      expect(detectPreset(869.618, 62.5, 8, 8)).toBe('EU/UK/Switzerland Narrow');
    });

    it('returns custom for non-matching values', () => {
      expect(detectPreset(900, 250, 10, 5)).toBe('custom');
    });

    it('returns custom when one value differs', () => {
      // Same as USA/Canada but with different SF
      expect(detectPreset(910.525, 62.5, 8, 5)).toBe('custom');
    });

    it('returns custom when bandwidth differs', () => {
      // Same as USA/Canada but with different BW
      expect(detectPreset(910.525, 125, 7, 5)).toBe('custom');
    });

    it('returns custom when coding rate differs', () => {
      // Same as USA/Canada but with different CR
      expect(detectPreset(910.525, 62.5, 7, 6)).toBe('custom');
    });
  });

  describe('findPreset', () => {
    it('finds preset by exact name', () => {
      const preset = findPreset('USA/Canada');
      expect(preset).toBeDefined();
      expect(preset?.freq).toBe(910.525);
      expect(preset?.bw).toBe(62.5);
      expect(preset?.sf).toBe(7);
      expect(preset?.cr).toBe(5);
    });

    it('returns undefined for unknown preset', () => {
      expect(findPreset('Unknown Preset')).toBeUndefined();
    });

    it('returns undefined for custom', () => {
      expect(findPreset('custom')).toBeUndefined();
    });
  });

  describe('preset round-trip', () => {
    it('all presets can be detected after being applied', () => {
      for (const preset of RADIO_PRESETS) {
        const detected = detectPreset(preset.freq, preset.bw, preset.sf, preset.cr);
        expect(detected).toBe(preset.name);
      }
    });
  });

  describe('preset values are valid LoRa parameters', () => {
    it('all frequencies are in valid ISM bands', () => {
      for (const preset of RADIO_PRESETS) {
        // 433 MHz: 433.05-434.79, EU 868: 863-870, US/AU/NZ/VN 900: 902-928
        const valid433 = preset.freq >= 433 && preset.freq <= 435;
        const validEU = preset.freq >= 863 && preset.freq <= 870;
        const valid900 = preset.freq >= 902 && preset.freq <= 928;
        expect(valid433 || validEU || valid900).toBe(true);
      }
    });

    it('all spreading factors are valid (7-12)', () => {
      for (const preset of RADIO_PRESETS) {
        expect(preset.sf).toBeGreaterThanOrEqual(7);
        expect(preset.sf).toBeLessThanOrEqual(12);
      }
    });

    it('all coding rates are valid (5-8 for 4/5 to 4/8)', () => {
      for (const preset of RADIO_PRESETS) {
        expect(preset.cr).toBeGreaterThanOrEqual(5);
        expect(preset.cr).toBeLessThanOrEqual(8);
      }
    });

    it('all bandwidths are standard LoRa values', () => {
      const validBandwidths = [7.8, 10.4, 15.6, 20.8, 31.25, 41.7, 62.5, 125, 250, 500];
      for (const preset of RADIO_PRESETS) {
        expect(validBandwidths).toContain(preset.bw);
      }
    });
  });
});
