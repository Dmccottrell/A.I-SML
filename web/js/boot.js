/* Starts the app: follows the system theme, registers the offline cache, loads. */
matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { if (S.theme === 'auto') applyTheme(); });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
load().catch(() => {});
