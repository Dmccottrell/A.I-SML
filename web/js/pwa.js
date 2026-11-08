/* The installed app (PWA), each part behind its own feature flag: Install and "new version" (pwa_install), reading chats and writing messages with
   no connection (pwa_offline), notifications when the app is closed (pwa_push, server side web_push.py), and sharing to Emvryx, opening files with
   it and the long-press shortcuts (pwa_share, the manifest's share_target, file_handlers and shortcuts). */
// PWA remembers the browser's "install" offer and the signed-in user's name.
const PWA = {install: null, user: null};
// pwaOn: is a feature switched on? (false if it cannot be checked)
const pwaOn = (id) => { try { return featureOn(id); } catch (e) { return false; } };
// pwaStore: read and write small values on this device only; it never throws, because private windows can refuse storage.
const pwaStore = {   // this device only; never throws (private windows can refuse storage)
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } },
};

// ---------------------------------------------------------------- pwa_install: Install Emvryx, and "a new version is ready"
// The browser offers an install button; we keep its offer so our own Install button can use it.
addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); PWA.install = e; pwaButtons(); });
// standalone: is the app running as an installed app (not in a browser tab)?
const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
// isIos: is this an iPhone or iPad? (installing works differently there)
const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent);
// pwaButtons: show the Install Emvryx button (when the feature is on, the app is not installed yet, and installing is possible).
function pwaButtons() {
  const old = $('pwaInstall'); if (old) old.remove();
  if (!S.state || !pwaOn('pwa_install') || standalone() || (!PWA.install && !isIos())) return;
  const b = el('button', {class: 'chip', id: 'pwaInstall', style: 'margin:6px 12px 0', title: 'Put Emvryx on your home screen as an app'}, '⬇ Install Emvryx');
  b.onclick = async () => {
    if (PWA.install) { PWA.install.prompt(); const r = await PWA.install.userChoice.catch(() => ({})); if (r.outcome === 'accepted') { PWA.install = null; b.remove(); } return; }
    dialog([el('h2', {}, 'Install Emvryx'), el('p', {}, 'In Safari, tap the Share button (the square with an arrow), then Add to Home Screen. Emvryx then opens like an app, full screen.')], 'Got it');
  };
  $('chatSearchBox').after(b);
}
// The version of the page's files, as the server says right now; empty when the server cannot be asked (offline or restarting).
// The version of the page's files, as the server says it right now ("" when it cannot be asked: offline, the server restarting).
async function pwaShellVersion() { try { const r = await fetch('/api/status', {cache: 'no-store'}); return r.ok ? String((await r.json()).shell || '') : ''; } catch (e) { return ''; } }
// pwaRestart: "Update now": ask the browser to fetch the newest files, then reload the page.
// "Update now": ask the browser to fetch the newest files, then reload the page (the installed app and the Windows app are this same page).
function pwaRestart() {
  const go = () => location.reload();
  if (!('serviceWorker' in navigator)) return go();
  navigator.serviceWorker.getRegistration().then((reg) => (reg ? reg.update().catch(() => {}) : null)).then(go, go);
}
// pwaWatchUpdates: show "A new version is ready" when the server's version differs from the one this page started with (checked every minute and when you come back) or when the browser has new files.
function pwaWatchUpdates() {
  // The notice: shown once, anywhere in the app. Later hides it until the next update.
  const ready = () => { if (!pwaOn('pwa_install') || $('pwaUpdate')) return;
    document.body.append(el('div', {class: 'pwa-update', id: 'pwaUpdate', role: 'status'}, el('span', {}, 'A new version of Emvryx is ready.'),
      el('button', {class: 'btn small', onclick: pwaRestart}, 'Update now'), el('button', {class: 'icon', 'aria-label': 'Later', onclick: () => $('pwaUpdate').remove()}, '\u00d7'))); };
  // The page remembers the version it started with; when the server's differs, the server was updated: say so at once (checked every minute and when you come back to the page).
  let base = null;
  const look = async () => { const v = await pwaShellVersion(); if (!v) return; if (base === null) base = v; else if (v !== base) ready(); };
  window.pwaCheckUpdate = look;
  look(); setInterval(look, 60 * 1000); document.addEventListener('visibilitychange', () => { if (!document.hidden) look(); });
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.getRegistration().then((reg) => {
    if (!reg) return;
    reg.addEventListener('updatefound', () => { const w = reg.installing; if (w) w.addEventListener('statechange', () => { if (w.state === 'activated' && navigator.serviceWorker.controller) ready(); }); });
    setInterval(() => reg.update().catch(() => {}), 30 * 60 * 1000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) reg.update().catch(() => {}); });
  });
}

// Offline mode: the last chats are kept on this device and messages written offline wait in an outbox.
// ---------------------------------------------------------------- pwa_offline: the last chats kept on this device, and an outbox
// The storage names include the user's name, so two people on one device do not mix.
const PWA_KEPT = () => 'emvryx_offline:' + (PWA.user || pwaStore.get('emvryx_pwa_user', ''));
const PWA_OUTBOX = () => 'emvryx_outbox:' + (PWA.user || pwaStore.get('emvryx_pwa_user', ''));
// pwaKeep: after a chat is drawn, keep it (and the chat list) for reading offline: at most 20 chats of 60 messages; private chats are never kept.
function pwaKeep() {   // after a chat is drawn: keep it (and the chat list) for reading offline. Private chats are never kept.
  if (!S.state || !pwaOn('pwa_offline') || S.chatId == null || S.chatId < 0 || S.busy) return;
  const box = pwaStore.get(PWA_KEPT(), {chats: []});
  box.list = (S.state.chats || []).slice(0, 40).map((c) => ({id: c.id, title: c.title}));
  box.chats = [{id: S.chatId, title: S.title, at: Date.now(), messages: S.messages.filter((m) => m.content).slice(-60).map((m) => ({role: m.role, content: m.content}))},
    ...(box.chats || []).filter((c) => c.id !== S.chatId)].slice(0, 20);
  // If the phone's storage is full, keep fewer chats until it fits.
  while (!pwaStore.set(PWA_KEPT(), box) && box.chats.length > 1) box.chats.pop();      // the phone's storage is full: keep fewer
}
// pwaOffline: shown when the app cannot load: the kept chats to read, a box to write messages, and a retry that reloads when the server is back.
function pwaOffline(err) {   // load() failed: no connection, or the PC is off. Show what is kept, and let them write.
  if (err && err.message === 'login') return;
  if (!pwaStore.get('emvryx_pwa_flags', {}).pwa_offline) return;
  const box = pwaStore.get(PWA_KEPT(), {chats: [], list: []}), out = pwaStore.get(PWA_OUTBOX(), []);
  const root = el('div', {class: 'pwa-off', role: 'main'});
  const draw = (chat) => {
    const ta = el('textarea', {rows: 3, placeholder: chat ? 'Write a reply: it is sent when Emvryx is back' : 'Write a new message: it is sent when Emvryx is back', 'aria-label': 'Message for later', style: 'width:100%'});
    root.replaceChildren(el('div', {class: 'pwa-offbar'}, el('b', {}, 'Offline'), el('span', {}, 'Emvryx can’t be reached right now (no internet, or the PC is off). You can read your recent chats.'),
        el('button', {class: 'chip', onclick: () => location.reload()}, 'Try again')),
      chat ? el('button', {class: 'chip', onclick: () => draw(null)}, '← All chats') : el('h2', {}, 'Recent chats'),
      ...(chat ? chat.messages.map((m) => el('div', {class: 'msg ' + (m.role === 'user' ? 'user' : 'ai')}, el('div', {class: 'bubble'}, m.role === 'user' ? m.content : richText(m.content))))
        : (box.chats || []).map((c) => el('button', {class: 'opt', onclick: () => draw(c)}, el('span', {class: 'grow'}, el('b', {}, c.title || 'Chat'), el('small', {}, 'Kept ' + new Date(c.at).toLocaleString())))).concat(
          (box.chats || []).length ? [] : [el('p', {style: 'color:var(--muted)'}, 'No chats are kept on this device yet: open one while you are online.')])),
      el('div', {class: 'pwa-outbox'}, ta, el('button', {class: 'btn', onclick: () => { const t = ta.value.trim(); if (!t) return;
        out.push({chat: chat ? chat.id : null, text: t, at: Date.now()}); pwaStore.set(PWA_OUTBOX(), out); ta.value = ''; toast('Saved. It is sent as soon as Emvryx is back.'); draw(chat); }}, 'Send when back'),
        out.length ? el('small', {style: 'color:var(--muted)'}, out.length + (out.length === 1 ? ' message is' : ' messages are') + ' waiting to be sent.') : ''));
  };
  draw(null);
  document.querySelectorAll('.pwa-off').forEach((n) => n.remove());
  document.body.append(root);
  const retry = setInterval(async () => { try { const r = await fetch('/api/state', {credentials: 'same-origin'}); if (r.ok) { clearInterval(retry); location.reload(); } } catch (e) { /* still offline */ } }, 20000);
  addEventListener('online', () => setTimeout(() => location.reload(), 1500), {once: true});
}
// pwaFlush: back online: send the messages written offline one by one, in order, stopping at the first failure.
async function pwaFlush() {   // back online: send what was written offline, in order
  const out = pwaStore.get(PWA_OUTBOX(), []); if (!out.length || !pwaOn('pwa_offline')) return;
  let sent = 0;
  while (out.length) {
    const m = out[0];
    try {
      let id = m.chat;
      if (id == null || !(S.state.chats || []).some((c) => c.id === id)) { const r = await post('/api/chats', {}); if (!r.ok) break; id = (await r.json()).id; }
      const r = await fetch('/api/chats/' + id + '/send', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: m.text, model: S.model, effort: S.effort})});
      if (!r.ok) break;
      await r.text();                                   // the answer is written and saved on the server
      out.shift(); pwaStore.set(PWA_OUTBOX(), out); sent++;
    } catch (e) { break; }
  }
  if (sent) { toast(sent + (sent === 1 ? ' message' : ' messages') + ' written offline were sent.'); await load(); }
}

// Notifications on this device (web push).
// ---------------------------------------------------------------- pwa_push: notifications on this device
// b64ToBytes: turn the server's public key from web-safe base64 text into bytes.
const b64ToBytes = (s) => { const b = atob((s + '='.repeat((4 - s.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from(b, (c) => c.charCodeAt(0)); };
// pwaPushRow: the Settings row with Turn on / Turn off / Send a test for notifications; turning on asks permission, then registers this device with the server.
function pwaPushRow() {
  const ok = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  const out = el('small', {style: 'color:var(--muted);display:block;margin-top:6px'});
  const ctl = el('div', {style: 'display:flex;gap:8px;flex-wrap:wrap'});
  const draw = async () => {
    const reg = ok ? await navigator.serviceWorker.ready : null, sub = reg ? await reg.pushManager.getSubscription() : null;
    ctl.replaceChildren(!ok ? el('span', {}, 'This browser cannot show notifications. On iPhone, install Emvryx to the home screen first.')
      : sub ? sxBtn('Turn off', async () => { await post('/api/push/unsubscribe', {endpoint: sub.endpoint}); await sub.unsubscribe(); draw(); })
        : sxBtn('Turn on', async () => {
          if (await Notification.requestPermission() !== 'granted') { out.textContent = 'Notifications are blocked for Emvryx in this browser’s settings.'; return; }
          const k = await (await api('/api/push')).json();
          const s2 = await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: b64ToBytes(k.key)});
          const r = await post('/api/push/subscribe', {subscription: s2.toJSON()}); const j = await r.json().catch(() => ({}));
          out.textContent = r.ok ? 'On. You will be told when an answer or VryxCode is ready while Emvryx is closed.' : (j.message || 'That did not work.'); draw(); }, 'primary'),
      sub ? sxBtn('Send a test', async () => { const r = await post('/api/push/test'); const j = await r.json().catch(() => ({})); out.textContent = r.ok ? 'Sent: it should appear in a moment.' : (j.message || 'It could not be sent.'); }) : '');
  };
  draw();
  return el('div', {}, ctl, out);
}

// Sharing and shortcuts: text or links shared to Emvryx, files opened with it, and the long-press shortcuts.
// ---------------------------------------------------------------- pwa_share: shared text and links, files opened with Emvryx, the shortcuts
// pwaLaunch: read the address the app was opened with and act on it: start a chat with the shared text, open a new chat, VryxCode or voice; also receives files opened with the app.
function pwaLaunch() {
  if (!pwaOn('pwa_share')) return;
  const q = new URLSearchParams(location.search), shared = [q.get('share_title'), q.get('share_text'), q.get('share_url')].filter(Boolean);
  const what = q.get('pwa');
  if (shared.length || what) history.replaceState(null, '', location.pathname + location.hash);
  if (shared.length) { newChat(false); input.value = [...new Set(shared)].join('\n'); input.focus(); toast('Shared to Emvryx: add your question and send.'); }
  else if (what === 'new') newChat(false);
  else if (what === 'code') openCode();
  else if (what === 'voice') { newChat(false); toast('Hold the microphone to talk.'); }
  if ('launchQueue' in window) launchQueue.setConsumer(async (p) => {
    const files = await Promise.all((p.files || []).map((h) => h.getFile()));
    if (files.length) { newChat(false); await addFiles(files); toast('Opened in Emvryx: ask anything about ' + (files.length === 1 ? 'it' : 'them') + '.'); }
  });
}

// The Windows app tells the page which build it is; the server knows the newest one.
// ---------------------------------------------------------------- app_updates: inside the Emvryx app for Windows (windows-app/main.cc)
// The app tells the page which build it is; the server knows the newest one (app_updates.py). Later waits for the next build.
// winAppUpdate: inside the Windows app, show a bar when a newer build exists; Later remembers not to ask again for that build.
async function winAppUpdate() {
  const app = window.EMVRYX_APP;
  if (!app || app.platform !== 'windows' || !app.builtFrom || !pwaOn('app_updates') || $('appUpdate')) return;
  let j;
  try { const r = await api('/api/app-latest?platform=windows'); if (!r.ok) return; j = await r.json(); } catch (e) { return; }
  if (!j.sha || j.sha === app.builtFrom || pwaStore.get('emvryx_app_later') === j.sha) return;
  const later = () => pwaStore.set('emvryx_app_later', j.sha);
  const bar = el('div', {class: 'app-update', id: 'appUpdate', role: 'status'}, el('b', {}, 'A new version of Emvryx is ready'), el('span', {class: 'grow'}),
    el('button', {class: 'chip', type: 'button', onclick: () => { later(); bar.remove(); }}, 'Later'),
    el('a', {class: 'btn small', href: j.download, onclick: () => { later(); setTimeout(() => bar.remove(), 300); }}, 'Update'));
  document.body.append(bar);
}

// pwaReady: after sign-in: remember the user and the offline switch, show the buttons, send any outbox, and (once) handle the launch address, update watching and the Windows update.
// ---------------------------------------------------------------- after sign-in
function pwaReady() {
  if (!S.state) return;
  PWA.user = S.state.user; pwaStore.set('emvryx_pwa_user', S.state.user);
  pwaStore.set('emvryx_pwa_flags', {pwa_offline: pwaOn('pwa_offline')});         // offline, the switches cannot be asked for: remember this one
  if (!pwaOn('pwa_offline')) { try { localStorage.removeItem(PWA_KEPT()); } catch (e) { /* nothing kept */ } }
  pwaButtons(); pwaFlush();
  if (!PWA.launched) { PWA.launched = true; pwaLaunch(); pwaWatchUpdates(); winAppUpdate();
    if (location.hash === '#code') { history.replaceState(null, '', location.pathname); openCode(); } }      // a VryxCode notification was tapped
}
// Check twice a second whether the app state changed and run pwaReady again if so.
setInterval(() => { if (S.state && S.state !== pwaReady.seen) { pwaReady.seen = S.state; pwaReady(); } }, 500);
