/* The welcome tour and the what's new notice. */
// ---------------------------------------------------------------- welcome tour (a feature flag: Settings > Owner > Features and testing)
const TOUR_VERSION = 1;
const tourDevice = () => {   // desktop browser, the installed app (home screen / dock), or a phone's browser
  let installed = false; try { installed = (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true; } catch (e) {}
  if (installed) return 'pwa';
  return /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || (window.matchMedia && matchMedia('(pointer: coarse)').matches && innerWidth < 800) ? 'mobile' : 'desktop';
};
const featureOn = (id) => !!(S.state && S.state.features && S.state.features[id]);
const TAGLINE = {Flare: 'Fast and light', Equinox: 'Everyday work', Solstice: 'Harder questions', Apogee: 'Toughest challenges'};
function openTour(replay) {
  if (document.querySelector('.tour')) return;
  const st = S.state, admin = !!st.admin;
  const names = [...new Set(allModels().filter((m) => m.state !== 'soon' && TAGLINE[m.name]).map((m) => m.name))];
  const spark = (n) => Array.from({length: n}, (_, i) => el('i', {class: 'spark', style: 'left:' + (8 + (i * 83) % 84) + '%;top:' + (40 + (i * 37) % 50) + '%;animation-delay:' + (i * 0.45) + 's'}));
  const slides = [
    {art: () => el('div', {class: 'art'}, el('div', {class: 'rings'}, el('i'), el('i'), el('i')), el('div', {class: 'rise', style: 'position:relative'}, logo(96, true)), ...spark(8)),
     kicker: 'A small language model AI', title: 'Welcome to Emvryx', text: 'Designed by Darryl McCottrell, someone who loves technology. Emvryx learns, evolves, writes code and so much more.'},
    {art: () => el('div', {class: 'art'}, el('div', {class: 'mcards'}, ...names.map((n, i) => el('div', {class: 'mcard rise', style: '--d:' + (i * 0.12) + 's'}, el('b', {}, n), el('span', {}, TAGLINE[n]))))),
     title: 'Pick the right model', text: 'Smaller ones answer fast. Bigger ones think harder. Choose under the message box, or leave it on Auto and Emvryx picks for you.'},
    {art: () => el('div', {class: 'art'}, el('div', {class: 'chat'}, el('div', {class: 'bubble2 me rise', style: 'align-self:flex-end'}, 'Why is the sky blue?'),
       el('div', {class: 'bubble2 rise', style: '--d:.5s'}, 'Air scatters short blue light far more than red, so blue reaches your eyes from every direction.', el('br'), el('span', {class: 'src'}, 'Source: Wikipedia')))),
     title: 'Answers with sources', text: 'When it looks something up, it says where it came from. When it can’t find out, it tells you instead of guessing.'},
    {art: () => el('div', {class: 'art'}, el('div', {class: 'chips'}, ...[['lock', 'Private chats'], ['brain', 'Memory you control'], ['doc', 'Your documents'], ['spark', 'Skills'], ['chart', 'Live facts']].map(([ic, t], i) => el('span', {class: 'rise', style: '--d:' + (i * 0.1) + 's'}, icon(ic), t)))),
     title: 'Make it yours', text: 'Private chats are never saved. Add your documents, connect your calendar or mail, and tell it how you like answers.'},
    {art: () => el('div', {class: 'art'}, el('div', {class: 'term'}, el('div', {class: 'dim rise'}, '> Make a slug helper'), el('div', {class: 'rise', style: '--d:.4s'}, el('span', {class: 'ok'}, '✓'), ' Wrote slug.py'), el('div', {class: 'rise', style: '--d:.8s'}, el('span', {class: 'ok'}, '✓'), ' Added a test'), el('div', {class: 'rise', style: '--d:1.2s'}, el('span', {class: 'ok'}, '✓'), ' Ran the tests: all pass'))),
     title: 'Build with VryxCode', text: 'Describe what you want. VryxCode plans it, writes the files, runs them, fixes what breaks and shows you the result live.'},
  ];
  if (admin) slides.push({art: () => el('div', {class: 'art'}, el('div', {class: 'chips'}, ...['People', 'Invite codes', 'Backups', 'Answer reports', 'Features and testing'].map((t, i) => el('span', {class: 'rise', style: '--d:' + (i * 0.1) + 's'}, t)))),
    title: 'You’re an admin', text: 'Settings > Owner has the tools to run Emvryx: add people, make invite codes, take backups, read reports, and test new features before everyone gets them.'});
  const dev = tourDevice(), ios = /iPhone|iPad|iPod/i.test(navigator.userAgent);
  if (dev !== 'pwa') slides.push({art: () => el('div', {class: 'art'}, el('div', {class: 'chips'}, ...(dev === 'desktop' ? ['Address bar', 'Install Emvryx', 'Opens in its own window'] : ios ? ['Tap Share', 'Add to Home Screen', 'Open it like an app'] : ['Tap the menu', 'Install app', 'Open it like an app']).map((t, i) => el('span', {class: 'rise', style: '--d:' + (i * 0.15) + 's'}, t)))),
    title: 'Keep it one tap away', text: dev === 'desktop' ? 'In Chrome or Edge, click the install icon in the address bar (in Safari: File, then Add to Dock). Emvryx then opens in its own window.' : ios ? 'In Safari, tap the Share button, then Add to Home Screen. Emvryx opens full screen, like an app.' : 'Open your browser menu and choose Install app (or Add to Home screen). Emvryx opens full screen, like an app.'});
  slides.push({art: () => el('div', {class: 'art'}, el('div', {class: 'rings'}, el('i'), el('i')), el('div', {class: 'rise', style: 'position:relative'}, logo(84, true)), ...spark(12)),
    title: 'You’re all set', text: 'Ask anything to start. You can replay this tour any time in Settings > About.'});
  let i = 0, startX = null;
  const nodes = slides.map((s) => el('div', {class: 'slide'}, s.art(), s.kicker ? el('div', {class: 'kicker'}, s.kicker) : null, el('h2', {}, s.title), el('p', {}, s.text)));
  const dots = el('div', {class: 'dots'}, ...slides.map(() => el('span')));
  const back = el('button', {type: 'button', hidden: true, onclick: () => go(i - 1)}, 'Back'), next = el('button', {type: 'button', class: 'go', onclick: () => (i === slides.length - 1 ? finish() : go(i + 1))}, 'Next');
  const root = el('div', {class: 'tour', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Welcome to Emvryx'}, el('div', {class: 'glow'}),
    el('button', {class: 'skip', type: 'button', onclick: () => finish(true)}, 'Skip'), el('div', {class: 'stage'}, ...nodes), el('div', {class: 'foot'}, dots, el('div', {class: 'btns'}, back, next)));
  function go(n) {
    i = Math.max(0, Math.min(slides.length - 1, n));
    nodes.forEach((s, k) => { s.classList.toggle('on', k === i); s.classList.toggle('past', k < i); });
    [...dots.children].forEach((d, k) => d.classList.toggle('on', k === i));
    back.hidden = i === 0; next.textContent = i === slides.length - 1 ? 'Start chatting' : 'Next';
  }
  async function finish(skipped) {
    S.tourSoon = false; setTimeout(checkWhatsNew, 900);
    document.removeEventListener('keydown', onKey); root.remove();
    try { await post('/api/settings', {tour_seen: TOUR_VERSION, device: tourDevice()}); if (S.state && S.state.settings) S.state.settings.tour_devices = Object.assign({}, S.state.settings.tour_devices, {[tourDevice()]: TOUR_VERSION}); } catch (e) { /* it will simply show once more */ }
    if (!skipped && !replay) { try { $('input').focus(); } catch (e) {} }
  }
  const onKey = (e) => { if (e.key === 'ArrowRight') go(i + 1); else if (e.key === 'ArrowLeft') go(i - 1); else if (e.key === 'Escape') finish(true); };
  document.addEventListener('keydown', onKey);
  root.addEventListener('touchstart', (e) => { startX = e.touches[0].clientX; }, {passive: true});
  root.addEventListener('touchend', (e) => { if (startX == null) return; const dx = e.changedTouches[0].clientX - startX; startX = null; if (Math.abs(dx) > 50) go(i + (dx < 0 ? 1 : -1)); }, {passive: true});
  document.body.append(root); go(0);
}
function maybeTour() {   // the first time someone signs in (and only while the feature is switched on for them)
  if (S.tourChecked || !S.state || !featureOn('welcome_tour')) return; S.tourChecked = true;
  if ((((S.state.settings || {}).tour_devices || {})[tourDevice()] || 0) < TOUR_VERSION) { S.tourSoon = true; setTimeout(() => openTour(false), 600); }      // the first time on each kind of device
}

// ---------------------------------------------------------------- what's new: published releases, shown once when someone opens the app after a release
const REL_KIND = {major: 'Major', minor: 'Minor', patch: 'Patch', 'model-new': 'New model', 'model-update': 'Model update'};
const relTitle = (r) => r.model ? r.model : 'v' + r.version;
function whatsNewList(releases) {
  return releases.length ? releases.map((r) => el('div', {class: 'adm-sub', style: 'margin:0 0 10px'}, el('div', {class: 'adm-row'}, el('span', {}, el('b', {}, relTitle(r)), ' ', el('span', {class: 'adm-tag'}, REL_KIND[r.kind] || r.kind)), el('small', {}, admDate(r.at))),
    ...(r.model ? [] : r.items.map((i) => el('div', {}, el('b', {style: 'font-size:15px'}, i.title), el('br'), el('small', {}, i.desc)))), r.notes ? el('small', {}, r.notes) : null)) : [el('p', {style: 'color:var(--muted)'}, 'Nothing has been released yet.')];
}
async function openWhatsNew(all) {
  let j; try { j = await (await api('/api/whats-new')).json(); } catch (e) { return; }
  const list = all ? j.releases : j.unseen;
  const m = dialog([el('h2', {}, all ? 'What’s new' : '✨ What’s new in Emvryx'), el('p', {style: 'color:var(--muted);margin-top:0'}, all ? 'Everything released so far. Current version: v' + j.version + '.' : 'New since you were last here.'), ...whatsNewList(list)], all ? 'Close' : 'Got it');
  if (!all) post('/api/settings', {whats_new_seq: j.seq});      // shown once: it counts as seen as soon as it is on the screen
}
let wnChecked = 0;
async function checkWhatsNew() {   // when the app opens, and again when the person comes back to it, at most once a minute
  if (!S.state || Date.now() - wnChecked < 60000 || S.tourSoon || document.querySelector('.tour') || document.querySelector('.dialog')) return; wnChecked = Date.now();
  try { const j = await (await api('/api/whats-new')).json(); if (j.unseen.length) openWhatsNew(false); } catch (e) {}
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) setTimeout(checkWhatsNew, 800); });
async function signOut() {   // one tap from the menu or the top of the side panel
  if (!confirm('Sign out of Emvryx on this device?')) return;
  try { await post('/api/logout'); } catch (e) { /* already signed out */ }
  try { localStorage.removeItem('emvryx_chat'); } catch (e) {}
  location.reload();
}
function closeAcct() { $('acctMenu').hidden = true; $('account').setAttribute('aria-expanded', 'false'); }
function renderLinks() {   // two tools in the list; Usage, Memory and Settings live in the account menu (Skills, Documents and Connected apps are hidden until they work)
  const mk = (ico, name, note, fn) => el('button', {class: 'link', onclick: () => { document.body.classList.remove('menu-open'); closeAcct(); fn(); }}, icon(ico), el('span', {}, name), note ? el('small', {}, note) : '');
  $('links').replaceChildren(mk('code', 'VryxCode', '', openCode), mk('spark', 'Skills', '', openSkills), mk('pencil', 'Teacher mode', '', () => newChat(false, 'teacher')), mk('doc', 'Documents', '', openDocs), mk('lock', 'Private chat', 'Never saved', () => newChat(true)));
  $('acctMenu').replaceChildren(mk('chart', 'Usage', '', openUsage), mk('brain', 'Memory', '', openMemory), mk('gear', 'Settings', '', openSettings), ...(S.state.admin ? [mk('lock', 'Admin', '', () => openAdmin())] : []), mk('signout', 'Sign out', '', signOut));
}
$('account').onclick = (e) => { e.stopPropagation(); const m = $('acctMenu'); m.hidden = !m.hidden; $('account').setAttribute('aria-expanded', String(!m.hidden)); };
document.addEventListener('click', (e) => { if (!$('acctMenu').hidden && !$('acctMenu').contains(e.target)) closeAcct(); });
