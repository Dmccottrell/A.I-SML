/* Starts the app: follows the system theme, registers the offline cache, loads. */
matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { if (S.theme === 'auto') applyTheme(); });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
load().catch(() => {});
// A click whose request failed (the PC restarting, the tunnel showing an error page instead of an answer, a lost connection) used to do nothing
// at all. Now it says so. "login" is the normal sign-in redirect, and a stopped reply is not an error.
addEventListener('unhandledrejection', (e) => {
  const err = e.reason || {}, msg = String(err.message || err);
  if (msg === 'login' || err.name === 'AbortError') return;
  const lost = err instanceof SyntaxError || /fetch|network|load failed|JSON/i.test(msg);
  toast(lost ? 'Emvryx did not answer properly. If the PC is restarting, try again in a moment.' : 'Something went wrong: ' + msg.slice(0, 120));
});
