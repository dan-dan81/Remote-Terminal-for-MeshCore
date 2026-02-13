export type SettingsSection = 'radio' | 'identity' | 'connectivity' | 'database' | 'bot';

export const SETTINGS_SECTION_ORDER: SettingsSection[] = [
  'radio',
  'identity',
  'connectivity',
  'database',
  'bot',
];

export const SETTINGS_SECTION_LABELS: Record<SettingsSection, string> = {
  radio: '📻 Radio',
  identity: '🪪 Identity',
  connectivity: '📡 Connectivity',
  database: '🗄️ Database',
  bot: '🤖 Bot',
};
