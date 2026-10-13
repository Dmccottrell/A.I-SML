/* The page's foundation: iPhone sizing, palettes, state, theme and loading the app. */
// iPhone installed app: the page can be given a height shorter than the screen (an empty band under the message box). The device's own screen size is
// reliable there, so the app is sized to it (never smaller than what the browser reports), and again after a turn of the phone.
function fitScreen() {
  try {
    const de = document.documentElement;
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const standalone = navigator.standalone === true || (window.matchMedia && matchMedia('(display-mode: standalone)').matches);
    if (!ios || !standalone) { de.style.removeProperty('--appH'); return; }
    const portrait = window.innerHeight >= window.innerWidth;
    const full = portrait ? Math.max(screen.width, screen.height) : Math.min(screen.width, screen.height);
    if (full > window.innerHeight && full < window.innerHeight + 300) de.style.setProperty('--appH', full + 'px'); else de.style.removeProperty('--appH');
  } catch (e) {}
}
fitScreen(); addEventListener('resize', fitScreen); addEventListener('orientationchange', () => setTimeout(fitScreen, 300)); addEventListener('pageshow', fitScreen);
'use strict';
// ---------------------------------------------------------------- palettes (design/brand-tokens.json)
const MODEL = {
  Emvryx:   {dark: {accent:'#F5A524', onaccent:'#1A1204', accenttext:'#F5A524', sun:'#F5A524', core:'#FFD27A', glow:'rgba(245,165,36,.14)'}, light: {accent:'#F5A524', onaccent:'#1A1204', accenttext:'#8F5600', sun:'#E08A00', core:'#FFD27A', glow:'rgba(245,165,36,.12)'}},   // the brand amber, as on the website: shown before a model is known (login)
  Ember:    {dark: {accent:'#C8431F', onaccent:'#FFFFFF', accenttext:'#F0734F', sun:'#C8431F', core:'#FFB05A', glow:'rgba(200,67,31,.20)'}, light: {accent:'#B7391E', onaccent:'#FFFFFF', accenttext:'#8F2A14', sun:'#A8321A', core:'#FF9A3C', glow:'rgba(183,57,30,.14)'}},
  Flare:    {dark: {accent:'#FF4B1F', onaccent:'#1A0500', accenttext:'#FF6B3D', sun:'#FF4B1F', core:'#FFF3E6', glow:'rgba(255,75,31,.20)'}, light: {accent:'#FF4B1F', onaccent:'#1A0500', accenttext:'#B83208', sun:'#E5340A', core:'#FFF3E6', glow:'rgba(255,75,31,.12)'}},
  Equinox:  {dark: {accent:'#EEF0F6', onaccent:'#07080D', accenttext:'#EEF0F6', sun:'#EEF0F6', core:'#07080D', glow:'rgba(238,240,246,.08)'}, light: {accent:'#0D0F1A', onaccent:'#FFFFFF', accenttext:'#0D0F1A', sun:'#0D0F1A', core:'#FFFFFF', glow:'rgba(13,15,26,.07)'}},
  Solstice: {dark: {accent:'#F2A60C', onaccent:'#1F1400', accenttext:'#FFBE3B', sun:'#F2A60C', core:'#FFE7A0', glow:'rgba(242,166,12,.18)'}, light: {accent:'#F2A60C', onaccent:'#1F1400', accenttext:'#8A5A00', sun:'#D18A00', core:'#FFE7A0', glow:'rgba(242,166,12,.13)'}},
  Apogee:   {dark: {accent:'#A8D1F5', onaccent:'#06121F', accenttext:'#B5D8F8', sun:'#A8D1F5', core:'#F4F9FF', glow:'rgba(168,209,245,.15)'}, light: {accent:'#A8D1F5', onaccent:'#06121F', accenttext:'#2A5F96', sun:'#4F8FC9', core:'#F4F9FF', glow:'rgba(120,170,220,.15)'}}
};
// The violet look (a feature flag, "violet_theme": Admin > Previews). Only Emvryx's own colour changes; each model keeps its own.
const VIOLET = {dark: {accent:'#8B5CF6', onaccent:'#FFFFFF', accenttext:'#A78BFA', sun:'#8B5CF6', core:'#C4B5FD', glow:'rgba(139,92,246,.14)'}, light: {accent:'#7C3AED', onaccent:'#FFFFFF', accenttext:'#6D28D9', sun:'#7C3AED', core:'#8B5CF6', glow:'rgba(124,58,237,.12)'}};
const violetOn = () => !!(S.state && S.state.features && S.state.features.violet_theme);
const BASE = {
  dark:  {bg:'#07080D', side:'#0A0B11', surface:'#0F1119', surface2:'#161926', line:'#232739', text:'#EEF0F6', muted:'#9AA3BC'},
  light: {bg:'#F7F8FC', side:'#EEF0F7', surface:'#FFFFFF', surface2:'#EEF0F7', line:'#D8DCEA', text:'#0D0F1A', muted:'#4A526B'}
};
const SUMMARY_MARK = '[Earlier in this chat, shortened to save room]';
const $ = (id) => document.getElementById(id);
const el = (tag, attrs, ...kids) => {
  const e = document.createElement(tag);
  for (const k in (attrs || {})) {
    if (k === 'class') e.className = attrs[k]; else if (k.startsWith('on')) e.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] !== false && attrs[k] != null) e.setAttribute(k, attrs[k]);
  }
  for (const c of kids.flat()) if (c != null) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
};
// The mark is an E whose middle arm runs into a glowing ring. Each model keeps the E and its own colours, and the ring
// grows with the model: Ember a coal, Flare a ring, Equinox ticks, Solstice rays, Apogee halos. `kind` 'brand' is Emvryx's
// own amber (login, sidebar); otherwise it is a model name, and the colours follow the page's model theme.
const LOGO_KINDS = ['ember', 'flare', 'equinox', 'solstice', 'apogee'];
const logoRays = (r1, r2, n, color) => Array.from({length: n}, (_, i) => { const a = i * 2 * Math.PI / n;
  return `<path d="M${(46 + r1 * Math.cos(a)).toFixed(1)} ${(32 + r1 * Math.sin(a)).toFixed(1)} L${(46 + r2 * Math.cos(a)).toFixed(1)} ${(32 + r2 * Math.sin(a)).toFixed(1)}" stroke="${color}" stroke-width="2" stroke-linecap="round"/>`; }).join('');
const logo = (size, animate, kind) => {
  const k = kind === 'brand' ? 'brand' : (LOGO_KINDS.includes((kind || '').toLowerCase()) ? kind.toLowerCase() : (LOGO_KINDS.includes(((curModel() || {}).name || '').toLowerCase()) ? curModel().name.toLowerCase() : 'flare'));
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('width', size); s.setAttribute('height', size); s.setAttribute('viewBox', '0 0 64 64'); s.setAttribute('fill', 'none'); s.setAttribute('aria-hidden', 'true');
  const pulse = (v) => animate ? `<animate attributeName="r" values="${v}" dur="1.6s" repeatCount="indefinite"/>` : '';
  const sun = k === 'brand' ? (violetOn() ? '#8B5CF6' : '#F5A524') : 'var(--sun)', main = k === 'apogee' ? 'var(--sun)' : 'var(--text)';
  let ring;
  if (k === 'brand') ring = `<circle cx="46" cy="32" r="5.5" stroke="${violetOn() ? '#C4B5FD' : '#FFD27A'}" stroke-width="3">${pulse('4.5;7;4.5')}</circle><circle cx="46" cy="32" r="1.8" fill="${sun}"/>`;
  else if (k === 'ember') ring = `<circle cx="45" cy="32" r="3.4" fill="${sun}">${pulse('2.6;4.4;2.6')}</circle>`;
  else if (k === 'apogee') ring = `<circle class="core" cx="46" cy="32" r="4.5" style="stroke-width:2.5">${pulse('4;6;4')}</circle><circle cx="46" cy="32" r="8.5" stroke="${sun}" stroke-width="1.6" stroke-opacity="0.7"/><circle cx="46" cy="32" r="12" stroke="${sun}" stroke-width="1.2" stroke-opacity="0.4"/>`;
  else ring = `<circle class="core" cx="46" cy="32" r="5.5">${pulse('4.5;7;4.5')}</circle>` + (k === 'equinox' ? logoRays(8.5, 11, 4, 'var(--text)') : k === 'solstice' ? logoRays(8.5, 11.5, 8, sun) : '');
  s.innerHTML = `<circle cx="46" cy="32" r="${k === 'ember' ? 9 : k === 'apogee' ? 15 : 12}" fill="${sun}" fill-opacity="0.16"/>
    <path d="M17 16 H41 M17 48 H41 M17 16 V48" stroke="${main}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M17 32 H${k === 'ember' ? 36 : 37}" stroke="${sun}" stroke-width="6" stroke-linecap="round"/>${ring}`;
  return s;
};
const fmt = (n) => Math.round(n).toLocaleString('en-US');
const nice = (n) => fmt(n >= 100 ? Math.round(n / 10) * 10 : Math.round(n));

// ---------------------------------------------------------------- state
const S = {state: null, chatId: null, skill: '', skills: [], docs: [], messages: [], title: 'New chat', private: false, model: null, effort: 'balanced', busy: false, abort: null,
           theme: localStorage.getItem('emvryx_theme') || 'dark', shown: null, stick: true, thinkTimer: null};
try { S.model = localStorage.getItem('emvryx_model'); S.effort = localStorage.getItem('emvryx_effort') || 'balanced'; } catch (e) {}
if (!['auto', 'quick', 'balanced', 'deep'].includes(S.effort)) S.effort = 'balanced';

function remember() {   // the open chat, so the home-screen app reopens where you were (a private chat is never saved, so it is not remembered)
  if (!S.restored) return;   // while the page is still starting up nothing may erase what was remembered
  try { if (S.chatId != null && S.chatId >= 0 && !S.private) localStorage.setItem('emvryx_chat', String(S.chatId)); else if (S.private) localStorage.removeItem('emvryx_chat'); } catch (e) {}   // an empty new chat keeps the last real one
}
async function restoreChat() {   // once per page load, after the chat list is known
  if (S.restored) return; S.restored = true;
  let id = null; try { id = parseInt(localStorage.getItem('emvryx_chat'), 10); } catch (e) {}
  if (S.chatId == null && id >= 0 && S.state.chats.some((c) => c.id === id)) await openChat(id);
}
async function api(path, opts) {
  const r = await fetch(path, Object.assign({credentials: 'same-origin', headers: {'Content-Type': 'application/json'}}, opts));
  if (r.status === 401) { showLogin(); throw new Error('login'); }
  return r;
}
const post = (path, body) => api(path, {method: 'POST', body: JSON.stringify(body || {})});

// ---------------------------------------------------------------- theme
function mname(m) { return m ? m.name + (m.version ? ' ' + m.version : '') : 'Emvryx'; }   // the name with its version: Flare 2.5
function allModels() { return S.state ? S.state.models.cards.concat(S.state.models.other || []) : []; }
function curModel() { return allModels().find((m) => m.id === S.model) || null; }
function applySize() {   // text size: 0.85 small .. 1.3 extra large, remembered on this device
  let z = 1; try { z = parseFloat(localStorage.getItem('emvryx_size')) || 1; } catch (e) {}
  document.documentElement.style.setProperty('--z', String(Math.min(1.4, Math.max(0.7, z))));
}
function applyTheme() {
  applySize();
  const mode = S.theme === 'auto' ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : S.theme;
  document.documentElement.dataset.mode = mode;
  const m = curModel(), p = Object.assign({}, BASE[mode], (!m && violetOn() ? VIOLET : (MODEL[m ? m.name : 'Emvryx'] || MODEL.Flare))[mode]);
  for (const k in p) document.documentElement.style.setProperty('--' + k, p[k]);
  document.querySelector('meta[name=theme-color]').content = p.bg;
  const on = (id) => !!(S.state && S.state.features && S.state.features[id]);
  // two looks behind feature flags: their stylesheets are only loaded (and their classes only set) while the flag is on for this person, so off means exactly the earlier look
  const sheet = (id, href, want) => { const e = document.getElementById(id); if (want && !e) document.head.append(el('link', {id, rel: 'stylesheet', href})); else if (!want && e) e.remove(); };
  document.body.classList.toggle('ml', on('modern_look')); sheet('cssModern', '/modern.css', on('modern_look'));
  document.body.classList.toggle('vxn', on('vryxcode_update')); sheet('cssVryx', '/vryx.css', on('vryxcode_update'));
}
function wash() { const w = el('div', {class: 'wash'}); document.body.append(w); setTimeout(() => w.remove(), 1100); }

// ---------------------------------------------------------------- load
async function load() {
  const q = new URLSearchParams({effort: S.effort}); if (S.model) q.set('model', S.model);
  const r = await api('/api/state?' + q);
  S.state = await r.json();
  if (!S.model || !allModels().some((m) => m.id === S.model && m.state === 'ready')) S.model = S.state.model;
  $('auth').hidden = true; $('app').hidden = false;
  if (!S.skills.length) { try { S.skills = (await (await api('/api/skills')).json()).skills; } catch (e) {} }
  applyTheme(); renderAll();
  await restoreChat();
  maybeTour(); checkWhatsNew(); restoreView();
}
function renderAll() {
  const st = S.state;
  $('brand').replaceChildren(logo(32, false, 'brand'), 'Emvryx', el('button', {class: 'icon', type: 'button', style: 'margin-left:auto;width:40px;height:40px;color:var(--muted)', 'aria-label': 'Sign out', title: 'Sign out', onclick: signOut}, icon('signout')));
  $('who').textContent = st.user === 'owner' ? 'Owner' : st.user;
  $('avatar').textContent = (st.user[0] || 'Y').toUpperCase();
  $('plan').textContent = (st.owner ? (st.founder ? 'Owner, no limits' : 'Admin, no limits') : st.plan[0].toUpperCase() + st.plan.slice(1) + ' plan' + (st.admin ? ' \u00b7 Admin' : ''));
  if (st.demo) { $('banner').hidden = false; $('banner').replaceChildren(el('b', {}, 'Demo mode. '), 'No model is attached, so replies are a stand-in. Start the server with --llama to use a real model.'); }
  else if (st.gaming) { $('banner').hidden = false; $('banner').replaceChildren(el('b', {}, 'Emvryx is resting. '), 'The PC is being used for something else, so chats are paused for now.'); }
  else $('banner').hidden = true;
  renderChats(); renderLinks(); renderComposer(); renderUsage(st.usage, true); renderThread(); warmModel(); maybeNudge();
}
function renderChats() {
  const box = $('chatList'); box.replaceChildren();
  if (S.q) {   // searching: matching chats, with the words around the match
    for (const r of S.hits || []) box.append(el('button', {class: 'hit', onclick: () => { S.q = ''; $('chatSearch').value = ''; openChat(r.id); }}, el('b', {}, r.title), r.snippet ? el('small', {}, r.snippet) : ''));
    if (!(S.hits || []).length) box.append(el('div', {class: 'label'}, S.hits ? 'NOTHING FOUND' : 'SEARCHING...'));
    return;
  }
  const day = new Date(); day.setHours(0, 0, 0, 0);
  const all = S.state.chats, plain = all.filter((c) => !c.skill && !c.pinned && !c.folder);
  const today = plain.filter((c) => c.updated * 1000 >= day.getTime()), earlier = plain.filter((c) => c.updated * 1000 < day.getTime());
  const group = (name, list) => { if (!list.length) return; box.append(el('div', {class: 'label'}, name));
    for (const c of list) box.append(el('div', {class: 'row' + (c.id === S.chatId ? ' cur' : '')},
      el('button', {class: 'open', onclick: () => openChat(c.id)}, (c.pinned ? '\ud83d\udccc ' : '') + c.title),
      el('button', {class: 'more', 'aria-label': 'Options for ' + c.title, 'aria-haspopup': 'true', onclick: (e) => chatMenu(c, e.currentTarget)}, '\u22ef'),
      el('button', {class: 'del', 'aria-label': 'Delete chat ' + c.title, onclick: () => delChat(c)}, '\u00d7'))); };
  group('PINNED', all.filter((c) => c.pinned));
  for (const f of [...new Set(all.filter((c) => c.folder && !c.pinned).map((c) => c.folder))]) group(f.toUpperCase(), all.filter((c) => c.folder === f && !c.pinned));
  group('TODAY', today); group('EARLIER', earlier);
  const names = {teacher: 'TEACHER MODE', study: 'STUDY HELPER'};   // chats started from a skill or Teacher mode keep their own list, so they never mix with ordinary chats
  const seen = [...new Set(all.filter((c) => c.skill && !c.pinned && !c.folder).map((c) => c.skill))];
  for (const id of seen) group(names[id] || (((S.skills.find((k) => k.id === id) || {}).name) || id).toUpperCase(), all.filter((c) => c.skill === id && !c.pinned && !c.folder));
  if (!all.length) box.append(el('div', {class: 'label'}, 'NO CHATS YET'));
}
let searchTimer = null;
$('chatSearch').addEventListener('input', (e) => {
  S.q = e.target.value.trim(); S.hits = null; renderChats(); clearTimeout(searchTimer);
  if (!S.q) return;
  searchTimer = setTimeout(async () => { const q = S.q; try { const r = await api('/api/chats/search?q=' + encodeURIComponent(q)); const j = await r.json(); if (S.q === q) { S.hits = j.results; renderChats(); } } catch (x) {} }, 250);
});
function chatMenu(c, btn) {   // a small menu next to the chat: pin, folder, delete
  document.querySelectorAll('.chatmenu').forEach((m) => m.remove());
  const item = (label, fn) => el('button', {class: 'link', style: 'min-height:40px', onclick: async () => { menu.remove(); await fn(); }}, label);
  const menu = el('div', {class: 'acctmenu chatmenu', style: 'position:fixed;left:' + Math.max(8, btn.getBoundingClientRect().left - 150) + 'px;top:' + (btn.getBoundingClientRect().bottom + 4) + 'px;right:auto;bottom:auto;width:200px;z-index:60'},
    item(c.pinned ? 'Unpin' : '\ud83d\udccc Pin to the top', async () => { await post('/api/chats/' + c.id + '/pin', {pinned: !c.pinned}); await load(); }),
    item('Move to a folder\u2026', async () => { const f = prompt('Folder name (leave empty to take it out of its folder):', c.folder || ''); if (f === null) return; await post('/api/chats/' + c.id + '/folder', {folder: f}); await load(); }),
    item('Delete', () => delChat(c)));
  document.body.append(menu);
  setTimeout(() => document.addEventListener('click', function off() { menu.remove(); document.removeEventListener('click', off); }, {once: false}), 0);
}
const ICONS = {signout: 'M10 4H5v16h5M15 8l4 4-4 4M19 12H9', eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', folder: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z', laptop: 'M5 6h14v9H5zM3 18h18', box: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12L4 7.5M12 12v9', cloud: 'M7 18a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 17.4 9 4.5 4.5 0 0 1 17 18z', undo: 'M9 7L4 12l5 5M4 12h11a5 5 0 0 1 0 10h-3', code: 'M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 6l-3 12', lock: 'M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z', chart: 'M5 20V10M12 20V4M19 20v-7',
               brain: 'M12 4a3 3 0 0 0-3 3 3 3 0 0 0-3 3 3 3 0 0 0 1 5 3 3 0 0 0 5 2zM12 4a3 3 0 0 1 3 3 3 3 0 0 1 3 3 3 3 0 0 1-1 5 3 3 0 0 1-5 2z',
               doc: 'M7 3h7l4 4v14H7zM14 3v4h4M9.5 12h5M9.5 16h5',
               pencil: 'M4 20l1-4L16 5l3 3L8 19zM14 7l3 3',
               spark: 'M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z',
               x: 'M6 6l12 12M18 6L6 18', search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.3-4.3', back: 'M15 6l-6 6 6 6',
               gear: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1'};
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '20'); svg.setAttribute('height', '20'); svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'none'); svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', ICONS[name]); path.setAttribute('stroke', 'currentColor'); path.setAttribute('stroke-width', '1.8'); path.setAttribute('stroke-linecap', 'round'); path.setAttribute('stroke-linejoin', 'round');
  svg.append(path); return svg;
}
