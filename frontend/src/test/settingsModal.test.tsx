import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SettingsModal } from '../components/SettingsModal';
import type { AppSettings, AppSettingsUpdate, HealthStatus, RadioConfig } from '../types';

const baseConfig: RadioConfig = {
  public_key: 'aa'.repeat(32),
  name: 'TestNode',
  lat: 1,
  lon: 2,
  tx_power: 17,
  max_tx_power: 22,
  radio: {
    freq: 910.525,
    bw: 62.5,
    sf: 7,
    cr: 5,
  },
};

const baseHealth: HealthStatus = {
  status: 'connected',
  radio_connected: true,
  connection_info: 'Serial: /dev/ttyUSB0',
  database_size_mb: 1.2,
  oldest_undecrypted_timestamp: null,
};

const baseSettings: AppSettings = {
  max_radio_contacts: 200,
  experimental_channel_double_send: false,
  favorites: [],
  auto_decrypt_dm_on_advert: false,
  sidebar_sort_order: 'recent',
  last_message_times: {},
  preferences_migrated: false,
  advert_interval: 0,
  bots: [],
};

function renderModal(overrides?: {
  appSettings?: AppSettings;
  onSaveAppSettings?: (update: AppSettingsUpdate) => Promise<void>;
  onRefreshAppSettings?: () => Promise<void>;
}) {
  const onSaveAppSettings = overrides?.onSaveAppSettings ?? vi.fn(async () => {});
  const onRefreshAppSettings = overrides?.onRefreshAppSettings ?? vi.fn(async () => {});

  render(
    <SettingsModal
      open
      config={baseConfig}
      health={baseHealth}
      appSettings={overrides?.appSettings ?? baseSettings}
      onClose={vi.fn()}
      onSave={vi.fn(async () => {})}
      onSaveAppSettings={onSaveAppSettings}
      onSetPrivateKey={vi.fn(async () => {})}
      onReboot={vi.fn(async () => {})}
      onAdvertise={vi.fn(async () => {})}
      onHealthRefresh={vi.fn(async () => {})}
      onRefreshAppSettings={onRefreshAppSettings}
    />
  );

  return { onSaveAppSettings, onRefreshAppSettings };
}

function openConnectivityTab() {
  const connectivityTab = screen.getByRole('tab', { name: 'Connectivity' });
  fireEvent.mouseDown(connectivityTab);
  fireEvent.click(connectivityTab);
}

describe('SettingsModal', () => {
  it('refreshes app settings when opened', async () => {
    const { onRefreshAppSettings } = renderModal();

    await waitFor(() => {
      expect(onRefreshAppSettings).toHaveBeenCalledTimes(1);
    });
  });

  it('shows favorite-first contact sync helper text in connectivity tab', async () => {
    renderModal();

    openConnectivityTab();

    expect(
      screen.getByText(
        /Favorite contacts load first, then recent non-repeater contacts until this\s+limit is reached/i
      )
    ).toBeInTheDocument();
  });

  it('saves changed max contacts value through onSaveAppSettings', async () => {
    const { onSaveAppSettings } = renderModal();

    openConnectivityTab();

    const maxContactsInput = screen.getByLabelText('Max Contacts on Radio');
    fireEvent.change(maxContactsInput, { target: { value: '250' } });

    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    await waitFor(() => {
      expect(onSaveAppSettings).toHaveBeenCalledWith({ max_radio_contacts: 250 });
    });
  });

  it('does not save max contacts when unchanged', async () => {
    const { onSaveAppSettings } = renderModal({
      appSettings: { ...baseSettings, max_radio_contacts: 200 },
    });

    openConnectivityTab();
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    await waitFor(() => {
      expect(onSaveAppSettings).not.toHaveBeenCalled();
    });
  });

  it('saves experimental channel double-send toggle through onSaveAppSettings', async () => {
    const { onSaveAppSettings } = renderModal({
      appSettings: { ...baseSettings, experimental_channel_double_send: false },
    });

    openConnectivityTab();

    const toggle = screen.getByLabelText('Always send channel messages twice');
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    await waitFor(() => {
      expect(onSaveAppSettings).toHaveBeenCalledWith({
        experimental_channel_double_send: true,
      });
    });
  });
});
