/* The Settings screen. */
// ---------------------------------------------------------------- settings
function removeAccountDialog(u, done) {   // an admin deletes someone else's account: confirm it is you, then type their name
  const [rk, rb] = reauthFields(), err = sxErr(), typed = sxInput('text', u.user);
  const m = dialog([el('h2', {}, 'Delete ' + u.user + '?'),
    el('p', {style: 'margin:0;color:var(--muted)'}, 'This removes the account and everything it owns: chats, saved notes, memory, coding projects, devices and connected apps. It cannot be undone. To keep the account but stop it being used, use Turn off instead.'),
    ...rk, el('p', {style: 'margin:0'}, 'Type ', el('b', {}, u.user), ' to confirm:'), typed, err,
    el('button', {class: 'btn danger', type: 'button', onclick: async () => { const j = await sxPost('/api/admin/delete-user', Object.assign({user: u.user, confirm: typed.value.trim()}, rb()), err); if (!j) return; m.remove(); toast(u.user + ' was deleted.'); done(); }}, 'Delete everything')], 'Keep the account');
}
function accessDialog(u, done) {   // the first owner chooses a plan, no limits, and admin rights for one person
  let plan = u.tier, unlimited = !!u.unlimited, admin = !!u.admin;
  const note = el('div', {style: 'color:var(--muted);font-size:14px'}, 'No limits means no usage cap at all, like the owner. A plan sets the normal cap. Admin rights open the Owner pages in Settings (people, invite codes, backups, reports).');
  const seg = sxSeg([['free', 'Free'], ['pro', 'Pro'], ['mega', 'Mega']], plan, (v) => { plan = v; });
  const row = (title, desc, ctl) => el('div', {class: 'srow inline'}, el('div', {class: 'stxt'}, el('b', {}, title), el('small', {}, desc)), el('div', {class: 'sctl'}, ctl));
  dialog([el('h2', {}, 'Plan and rights for ' + u.user), note, el('b', {}, 'Plan'), seg,
    row('No usage limits', 'Skips every cap, whatever the plan says.', sxSwitch(unlimited, (v) => { unlimited = v; }, 'No usage limits')),
    row('Admin rights', 'Can use the Owner pages in Settings. Cannot give out plans or admin rights.', sxSwitch(admin, (v) => { admin = v; }, 'Admin rights')),
    el('div', {class: 'btnrow'}, el('button', {class: 'btn', type: 'button', onclick: async (e) => {
      const r = await post('/api/admin/access', {user: u.user, plan, unlimited, admin}), j = await r.json().catch(() => ({}));
      if (!r.ok) return toast(j.message || 'That did not work.');
      e.target.closest('.dialog').parentNode.remove(); toast('Saved for ' + u.user + '.'); done();
    }}, 'Save'))], 'Cancel');
}
async function openSources() {
  const j = await (await api('/api/live/sources')).json();
  const row = (x) => el('div', {style: 'display:flex;gap:8px;align-items:baseline;padding:2px 0'}, el('span', {style: 'color:' + (x.active ? '#3fb950' : 'var(--muted)')}, x.active ? '●' : '○'), el('span', {}, x.name), x.needs_key && !x.active ? el('small', {style: 'color:var(--muted)'}, 'needs ' + x.keys.join(' or ')) : x.note ? el('small', {style: 'color:var(--muted)'}, x.note) : '');
  const grp = (title, list) => list.length ? [el('b', {style: 'margin-top:8px'}, title + ' (' + list.length + ')'), ...list.map(row)] : [];
  const testOut = el('div', {style: 'margin-top:8px;font-size:14px'});
  const testBtn = el('button', {class: 'sbtn', type: 'button', onclick: async () => {
    testBtn.disabled = true; testBtn.textContent = 'Testing\u2026 (up to 30 seconds)'; testOut.replaceChildren();
    try {
      const r = await post('/api/admin/sources/test', {}), t = await r.json();
      if (!r.ok) throw new Error(t.message || 'The test could not run.');
      testOut.append(el('b', {}, 'Test results'), ...t.rows.map((x) => el('div', {style: 'display:flex;gap:8px;align-items:baseline;padding:2px 0'},
        el('span', {style: 'color:' + (x.ok === true ? '#3fb950' : x.ok === false ? '#f85149' : 'var(--muted)')}, x.ok === true ? '\u2713' : x.ok === false ? '\u2717' : '\u25cb'),
        el('span', {}, x.name), el('small', {style: 'color:var(--muted)'}, x.detail + (x.ms ? ' (' + (x.ms / 1000).toFixed(1) + ' s)' : '')))));
    } catch (e) { testOut.textContent = e.message; }
    testBtn.disabled = false; testBtn.textContent = 'Test them now';
  }}, 'Test them now');
  const web = j.web === 'wikipedia' ? 'Wikipedia only (no web search key is set)' : j.web[0].toUpperCase() + j.web.slice(1);
  dialog([el('h2', {}, 'Live sources'), el('div', {style: 'color:var(--muted);font-size:14px'}, 'Green means it works now. Keys are set on the computer that runs Emvryx (see docs/LIVE_DATA.md).'),
    el('b', {}, 'Web search: ' + web),
    ...(S.state && S.state.admin ? [el('div', {}, testBtn, testOut)] : []),
    ...grp('Always on, no internet needed', j.sources.filter((x) => x.where === 'offline')),
    ...grp('Free online services, no key', j.sources.filter((x) => x.where === 'online' && !x.keys.length)),
    ...grp('Online services that use a key', j.sources.filter((x) => x.keys.length))], 'Close');
}

const SX = {page: 'general', acct: null, q: '', st: null};
const sxWhen = (t) => new Date(t * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
const clip = (s, n) => { s = String(s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '\u2026' : s; };
const sxBtn = (label, fn, cls) => el('button', {class: 'sbtn' + (cls ? ' ' + cls : ''), type: 'button', onclick: fn}, label);
const sxPill = (text, kind) => el('span', {class: 'pill' + (kind ? ' ' + kind : '')}, text);
function sxSeg(opts, cur, fn) { return el('div', {class: 'seg'}, ...opts.map(([v, t]) => el('button', {class: cur === v ? 'on' : '', type: 'button', onclick: (e) => { fn(v); [...e.target.parentNode.children].forEach((b) => b.classList.remove('on')); e.target.classList.add('on'); }}, t))); }
function sxSwitch(on, fn, label) { const b = el('button', {class: 'switch', type: 'button', role: 'switch', 'aria-checked': String(!!on), 'aria-label': label, onclick: () => { const v = b.getAttribute('aria-checked') !== 'true'; b.setAttribute('aria-checked', String(v)); fn(v); }}); return b; }
const sxSet = async (patch) => { await post('/api/settings', patch); await load().catch(() => {}); };
const sxLocal = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
async function sxAcct() { try { SX.acct = await (await api('/api/account')).json(); } catch (e) { if (e.message === 'login') closeSettings(); } return SX.acct; }

// A page is a list of sections; a section is {title, rows}; a row is {title, desc, ctl | node, keys, danger}. Search looks through every row.
function sxSections(id) {
  const st = S.state, s = st.settings, w = st.window, a = SX.acct || {mfa: {}}, owner = st.admin;
  const A = {
    general: [{title: 'Welcome tour and what\u2019s new', rows: [{title: 'What\u2019s new', desc: 'Every release so far, newest first: new features and new model versions.', ctl: sxBtn('See releases', () => { closeSettings(); openWhatsNew(true); }), keys: 'whats new releases updates changes history version'}, ...(featureOn('welcome_tour') ? [{title: 'Welcome tour', desc: 'The short animated introduction to Emvryx: the models, answers with sources, making it yours and VryxCode.', ctl: sxBtn('Start the tour', () => { closeSettings(); openTour(true); }), keys: 'welcome tour introduction walk through intro'}] : [])]},
      {title: 'Appearance', rows: [
      {title: 'Theme', desc: 'Automatic follows your phone or computer.', ctl: sxSeg([['auto', 'Automatic'], ['dark', 'Dark'], ['light', 'Light']], S.theme, (v) => { S.theme = v; try { localStorage.setItem('emvryx_theme', v); } catch (e) {} applyTheme(); }), keys: 'dark light mode colour color'},
      {title: 'Text and button size', ctl: sxSeg([['0.85', 'Small'], ['1', 'Normal'], ['1.15', 'Large'], ['1.3', 'Extra large']], String(parseFloat(sxLocal('emvryx_size', '1')) || 1), (v) => { try { localStorage.setItem('emvryx_size', v); } catch (e) {} applySize(); }), keys: 'font zoom bigger'}]},
      {title: 'Answers', rows: [
      {title: 'Pause before the answer', desc: 'A short beat before words appear, so replies feel less abrupt.', ctl: sxSeg([['off', 'None'], ['short', 'Short'], ['natural', 'Natural']], s.thinking_pause || 'short', (v) => sxSet({thinking_pause: v})), keys: 'delay typing speed'}]}],
    chat: [{title: 'Looking things up', rows: [
      {title: 'Where answers come from', desc: 'Questions are first looked up in Wikipedia on the server. Auto also searches the web, when it is online, for recent things (news, scores, prices) or when Wikipedia does not have the answer; your question is sent to a search service then, and each answer says so. Private chats never search the web.', ctl: sxSeg([['auto', 'Auto'], ['off', 'Wikipedia only'], ['always', 'Always search the web'], ['none', 'Model only']], s.web_search || 'auto', (v) => sxSet({web_search: v})), keys: 'web search wikipedia tavily internet', stack: true},
      {title: 'Live facts', desc: 'Sums, dates, prices, rates, scores and news come from code and free public services, not from the model’s memory. Only the needed words (a place, a currency, a team) are sent, never the chat. Off in private chats and in “Model only”.', ctl: sxSwitch(s.live_data !== false, (v) => sxSet({live_data: v}), 'Live facts'), keys: 'weather stocks sports currency'},
      {title: 'Which sources are on', desc: 'See what works right now and which keys are missing.', ctl: sxBtn('See sources', openSources), keys: 'api keys tavily brave rawg tmdb'}]},
      {title: 'Chat length', rows: [
      {title: 'How long a chat can be', desc: 'Right now: ' + fmt(w.window) + ' tokens, ' + w.reason + '. Long chats use more memory and are slower to read.', ctl: sxSeg([['everyday', 'Everyday (about 8K)'], ['long', 'Long (if allowed)']], s.window_mode, (v) => sxSet({window_mode: v})), keys: 'context window tokens', stack: true}]}],
    memory: [{title: 'Custom instructions', rows: [
      {title: 'How you like answers', desc: 'For example: \u201cKeep answers short. I am a nurse.\u201d It goes with every question where it fits (up to 400 letters). The small models follow short, simple instructions best.', node: 'custom', keys: 'style tone personalization system prompt'}]},
      {title: 'Memory', rows: [
      {title: 'Remember things about me', desc: 'Facts you tell it (your name, what you do, what you like) are kept on the server and given to whichever model you talk to. Private chats never save or read them. Passwords and card numbers are never kept.', ctl: sxSwitch(s.memory !== false, (v) => sxSet({memory: v}), 'Remember things about me'), keys: 'personalization remember'},
      {title: 'What it remembers', desc: 'See, add or delete any fact.', ctl: sxBtn('Open memory', () => { closeSettings(); openMemory(); })}]},
      {title: 'Saved notes', rows: [
      {title: 'Saved notes', desc: 'Notes you gave a thumbs up are kept so the same question works offline. You can delete any of them.', ctl: sxBtn('Open saved notes', openSaved), keys: 'thumbs up offline'}]}],
    data: [{title: 'Your data', rows: [
      {title: 'Documents', desc: 'Files and pictures you added to chats.', ctl: sxBtn('Open documents', () => { closeSettings(); openDocs(); })},
      {title: 'Download my data', desc: 'Everything saved about you in one zip: chats, notes, memory, projects.', ctl: el('a', {class: 'sbtn', href: '/api/export', download: ''}, 'Download'), keys: 'export backup'},
      {title: 'Private chats', desc: 'Chats started as Private are never saved, never searched on the web and never use memory.'}]},
      {title: 'Delete', rows: [
      {title: 'Delete all my chats', desc: 'Removes every chat. This cannot be undone.', danger: true, ctl: sxBtn('Delete chats', async () => { if (confirm('Delete every chat? This cannot be undone.')) { await post('/api/delete-everything'); S.chatId = null; S.messages = []; remember(); await load(); } }, 'bad')}]},
      {title: 'Legal', rows: [
      {title: 'Privacy and terms', ctl: el('div', {style: 'display:flex;gap:8px'}, el('a', {class: 'sbtn', href: '/privacy', target: '_blank', rel: 'noopener'}, 'Privacy'), el('a', {class: 'sbtn', href: '/terms', target: '_blank', rel: 'noopener'}, 'Terms'))}]}],
    apps: [{title: 'Connected apps', rows: [
      {title: 'Use my connected apps in chats', desc: 'When a question is clearly about one (\u201cwhat is on my calendar\u201d), the few matching items are read and given to the model as notes. Read-only. Private chats never use them.', ctl: sxSwitch(s.connected_apps !== false, (v) => sxSet({connected_apps: v}), 'Use my connected apps in chats'), keys: 'calendar notion slack email'},
      {title: 'All apps', desc: 'Calendar, email, Notion, Slack, Todoist, Linear, Trello, Jira, Dropbox, GitLab, Vercel and more: each one needs only a token, link or app password you paste.', ctl: sxBtn('See all apps', () => { closeSettings(); openApps(); }), keys: 'google gmail outlook todoist trello jira'},
      {title: 'GitHub', desc: 'Lets VryxCode create repositories and pull and push. Your token is stored encrypted and the model never sees it. Pulling, pushing and creating always ask first.', ctl: sxBtn('Manage', () => { closeSettings(); openApps(); }), keys: 'git repository vryxcode'}]}],
    security: [{title: 'Signing in', rows: [
      {title: 'Password', desc: a.has_password ? 'Set. Changing it signs your other devices out.' : 'Not set. Add one to sign in with your name and password.', ctl: el('div', {style: 'display:flex;gap:8px;align-items:center'}, sxPill(a.has_password ? 'Set' : 'Not set', a.has_password ? 'ok' : 'warn'), sxBtn(a.has_password ? 'Change' : 'Set a password', () => passwordDialog(), a.has_password ? '' : 'primary')), keys: 'change reset'},
      {title: 'Two-step sign-in', desc: a.mfa.on ? 'On. Signing in also needs a 6-digit code from your authenticator app.' : 'Off. Adds a 6-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator, Authy, 1Password) every time you sign in.', ctl: el('div', {style: 'display:flex;gap:8px;align-items:center'}, sxPill(a.mfa.on ? 'On' : 'Off', a.mfa.on ? 'ok' : 'warn'), a.mfa.on ? sxBtn('Turn off', () => mfaOffDialog(), 'bad') : sxBtn('Set up', () => mfaSetupDialog(), 'primary')), keys: 'mfa 2fa authenticator totp'},
      ...(a.passkeys_ok && passkeyOk() ? [{title: 'Passkeys', desc: 'Sign in with your fingerprint, face or screen lock: nothing to type, and nothing a thief can phish. Counts as two factors.', node: 'passkeys'}] : []),
      ...(a.mfa.on ? [{title: 'Recovery codes', desc: a.mfa.recovery_left + ' of 8 left. Each works once if you lose your phone.', ctl: sxBtn('Make new codes', () => recoveryDialog()), keys: 'backup codes lost phone'}] : [])]},
      {title: 'Where you are signed in', rows: [{node: 'devices'}]},
      {title: 'Recent security activity', rows: [{node: 'activity'}]}],
    account: [{title: 'You', rows: [
      {title: 'Name', desc: 'This is how you sign in.', ctl: el('b', {}, a.user || st.user)},
      {title: 'Email', desc: a.email ? (a.email_verified ? 'Verified. You can sign in with an email code.' : 'Not verified yet' + (a.mail ? '. Verify it to sign in with an email code.' : ' (this server cannot send email, so it stays unverified).')) : 'None. Add one so you can recover your account.',
        ctl: el('div', {style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap'}, a.email ? el('span', {style: 'word-break:break-all'}, a.email) : null, a.email && !a.email_verified && a.mail ? sxBtn('Verify', () => verifyEmailDialog(), 'primary') : null, sxBtn(a.email ? 'Change' : 'Add email', () => emailDialog())), keys: 'address mail'},
      {title: 'Plan', desc: owner ? 'Owner: no limits.' : 'What your plan includes is on the usage page.', ctl: el('div', {style: 'display:flex;gap:8px;align-items:center'}, sxPill(owner ? 'Owner' : st.plan[0].toUpperCase() + st.plan.slice(1)), sxBtn('Usage', () => { closeSettings(); openUsage(); })), keys: 'free pro mega limits'}]},
      {title: 'Session', rows: [
      {title: 'Sign out', desc: 'On this device.', ctl: sxBtn('Sign out', async () => { await post('/api/logout'); location.reload(); })}]},
      ...(owner ? [{title: 'Owner account', rows: [{title: 'This is the admin account', desc: 'It has no usage limits and the Owner pages in this menu. Keep it safe: use a password and two-step sign-in. It cannot be deleted or turned off from the app.'}]}] : [{title: 'Delete account', rows: [
      {title: 'Delete my account', desc: 'Removes your chats, notes, memory, projects, GitHub link and devices. This cannot be undone.', danger: true, ctl: sxBtn('Delete account', () => deleteDialog(), 'bad')}]}])],
    about: [{title: 'Emvryx', rows: [
      {title: 'One family of four models', desc: 'Flare, Equinox, Solstice and Apogee are the Emvryx models; VryxCode builds projects with them.'},
      {title: 'Your server', desc: st.demo ? 'Demo mode: no model is attached.' : 'Connected.', ctl: st.contact ? el('a', {class: 'sbtn', href: 'mailto:' + st.contact}, 'Report a problem') : null}]}]
  };
  return A[id] || [];
}
const SX_NAV = [['general', 'General', 'gear'], ['chat', 'Chat and lookups', 'spark'], ['memory', 'Memory', 'brain'], ['data', 'Data controls', 'folder'], ['apps', 'Connected apps', 'code'], ['security', 'Security', 'lock'], ['account', 'Account', 'eye'], ['about', 'About', 'doc']];
const SX_OWNER = [['a-overview', 'Overview', 'chart'], ['a-flags', 'Previews (Admin screen)', 'spark'], ['a-people', 'People (Admin screen)', 'eye'], ['a-signups', 'Sign-ups and invites', 'pencil'], ['a-feedback', 'Answer reports', 'pencil'], ['a-backups', 'Backups', 'folder'], ['a-cloud', 'Cloud machine', 'cloud'], ['a-log', 'Security log', 'lock']];
const SX_LEAD = {general: 'How Emvryx looks and feels on this device.', chat: 'How it finds facts and how much of a chat it keeps in mind.', memory: 'What it knows about you, shared by every model.', data: 'Your files, your downloads and what gets deleted.', apps: 'Other services Emvryx can work with.', security: 'Protect your account: password, two-step sign-in and your devices.', account: 'Who you are and your plan.', about: 'About this Emvryx.',
  'a-overview': 'How safe this server is to share, and how it is doing.', 'a-flags': 'Try new things yourself first, then widen who sees them. Changes apply at once.', 'a-people': 'Everyone with an account.', 'a-signups': 'Who may create an account, and invite codes.', 'a-feedback': 'What people said went wrong with an answer, newest first.', 'a-backups': 'Copies of everything this server keeps, so a broken disk is not the end.', 'a-cloud': 'A computer elsewhere (like a rented GPU box) where VryxCode can run your code.', 'a-log': 'Sign-ins, failures and changes, newest first.'};


// Keep the open Settings or Admin screen in the address (#settings/security, #admin/people), so an accidental refresh brings the person back to it instead of the chat.
function viewHash(h) { try { if (h) history.replaceState(null, '', '#' + h); else if (location.hash) history.replaceState(null, '', location.pathname + location.search); } catch (e) {} }
function sxHash() { viewHash(SX.root && SX.root.isConnected ? 'settings' + (SX.root.classList.contains('on-page') && SX.page ? '/' + SX.page : '') : ''); }
function restoreView() {
  if (S.viewChecked) return; S.viewChecked = true;
  const m = /^#(settings|admin)(?:\/([\w-]+))?$/.exec(location.hash || ''); if (!m) return;
  if (m[1] === 'admin') { if (S.state && S.state.admin) openAdmin(m[2]); else viewHash(''); return; }
  const ok = [...SX_NAV, ...SX_OWNER].some((x) => x[0] === m[2]); openSettings(ok ? m[2] : undefined);
}
function closeSettings() { document.querySelectorAll('.sx').forEach((n) => n.remove()); SX.root = null; sxHash(); }
async function openSettings(page) {
  closeSettings(); SX.page = page || SX.page || 'general'; SX.q = ''; SX.st = S.state;
  await sxAcct();
  const root = el('div', {class: 'sx', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Settings'});
  $('dialogs').append(root); SX.root = root; sxRender(!!page);
}
function chevron() { const c = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); c.setAttribute('class', 'chev'); c.setAttribute('width', '18'); c.setAttribute('height', '18'); c.setAttribute('viewBox', '0 0 24 24'); c.setAttribute('fill', 'none'); c.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', 'M9 6l6 6-6 6'); p.setAttribute('stroke', 'currentColor'); p.setAttribute('stroke-width', '2'); p.setAttribute('stroke-linecap', 'round'); c.append(p); return c; }
function sxNavItem(id, name, ico) {
  const a = SX.acct || {mfa: {}}, flag = id === 'security' && (!a.has_password || !a.mfa.on) && S.state.admin;
  return el('button', {class: 'sx-item' + (SX.page === id && !SX.q ? ' on' : ''), type: 'button', onclick: () => { SX.page = id; SX.q = ''; sxRender(true); }}, icon(ico), el('span', {}, name), flag ? el('span', {class: 'dot', title: 'Needs attention'}) : null,
    chevron());
}
function sxRender(onPage) {
  const root = SX.root; if (!root || !root.isConnected) return;
  const keepScroll = root.querySelector('.sx-body') ? root.querySelector('.sx-body').scrollTop : 0, owner = S.state.admin;
  if (onPage !== undefined) root.classList.toggle('on-page', !!onPage || !!SX.q);
  const search = el('input', {type: 'text', placeholder: 'Search settings', 'aria-label': 'Search settings', value: SX.q, oninput: (e) => { SX.q = e.target.value.trim(); root.classList.toggle('on-page', !!SX.q); sxBody(); sxNav.querySelectorAll('.sx-item').forEach((n) => n.classList.remove('on')); if (!SX.q) sxRender(); }});
  const sxNav = el('div', {class: 'sx-nav'},
    el('div', {class: 'sx-head'}, el('h2', {}, 'Settings'), el('button', {class: 'icon', type: 'button', 'aria-label': 'Close settings', onclick: closeSettings}, icon('x'))),
    el('div', {class: 'sx-search'}, icon('search'), search),
    el('div', {class: 'sx-list'}, ...SX_NAV.map(([id, n, i]) => sxNavItem(id, n, i)), ...(owner ? [el('div', {class: 'label'}, 'OWNER'), ...SX_OWNER.map(([id, n, i]) => sxNavItem(id, n, i))] : [])));
  const body = el('div', {class: 'sx-body', id: 'sxBody'});
  root.replaceChildren(sxNav, body);
  sxBody(); body.scrollTop = keepScroll; sxHash();
  if (SX.q) { search.focus(); search.setSelectionRange(search.value.length, search.value.length); }
}
function sxRowNode(r) {
  if (r.node) { const box = el('div', {class: 'srow stack', 'data-node': r.node}, el('div', {style: 'color:var(--muted)'}, 'Loading...')); setTimeout(() => sxFill(r.node, box), 0); return box; }
  const auto = r.ctl && r.ctl.classList && (r.ctl.classList.contains('switch') || r.ctl.classList.contains('sbtn'));
  return el('div', {class: 'srow' + (r.stack ? ' stack' : '') + (r.danger ? ' danger' : '') + (auto || r.inline ? ' inline' : '')}, el('div', {class: 'stxt'}, el('b', {}, r.title), r.desc ? el('small', {}, r.desc) : null), r.ctl ? el('div', {class: 'sctl'}, r.ctl) : null);
}
function sxCard(rows) { return el('div', {class: 'sx-card'}, ...rows.map(sxRowNode)); }
function sxBody() {
  const body = $('sxBody'); if (!body) return;
  const all = [...SX_NAV, ...SX_OWNER];
  if (SX.q) {
    const q = SX.q.toLowerCase(), kids = [el('h1', {style: 'display:flex;align-items:center;gap:8px'}, 'Search', el('button', {class: 'icon sx-close', type: 'button', 'aria-label': 'Close settings', onclick: closeSettings}, icon('x')))]; let n = 0;
    for (const [id, name] of SX_NAV) for (const sec of sxSections(id)) {
      const rows = sec.rows.filter((r) => !r.node && ((r.title || '') + ' ' + (r.desc || '') + ' ' + (r.keys || '') + ' ' + sec.title + ' ' + name).toLowerCase().includes(q));
      if (rows.length) { n += rows.length; kids.push(el('div', {class: 'sx-sec'}, name + ' › ' + sec.title), sxCard(rows)); }
    }
    for (const [id, name] of SX_OWNER) if (S.state.admin && name.toLowerCase().includes(q)) { n++; kids.push(el('div', {class: 'sx-sec'}, 'Owner'), el('div', {class: 'sx-card'}, el('button', {class: 'sx-item', type: 'button', onclick: () => { SX.q = ''; SX.page = id; sxRender(true); }}, name))); }
    if (!n) kids.push(el('p', {class: 'lead'}, 'Nothing matches “' + SX.q + '”.'));
    return body.replaceChildren(...kids);
  }
  const [id, name] = all.find((x) => x[0] === SX.page) || all[0];
  const head = el('h1', {style: 'display:flex;align-items:center;gap:8px'}, el('button', {class: 'icon sx-back', type: 'button', 'aria-label': 'Back to settings', onclick: () => { SX.root.classList.remove('on-page'); sxHash(); }}, icon('back')), name,
    el('button', {class: 'icon sx-close', type: 'button', 'aria-label': 'Close settings', onclick: closeSettings}, icon('x')));
  if (id.startsWith('a-')) { body.replaceChildren(head, el('p', {class: 'lead'}, SX_LEAD[id]), el('div', {id: 'sxAdmin'}, el('div', {style: 'color:var(--muted)'}, 'Loading...'))); return adminPage(id); }
  const kids = [head, el('p', {class: 'lead'}, SX_LEAD[id])];
  for (const sec of sxSections(id)) kids.push(el('div', {class: 'sx-sec'}, sec.title), sxCard(sec.rows));
  body.replaceChildren(...kids);
}
async function sxReload() { await sxAcct(); sxRender(); }
const EVENT_NAMES = {login_ok: 'Signed in', login_fail: 'Wrong sign-in try', logout: 'Signed out', lockout: 'Address locked out', signup: 'New account', password_set: 'Password changed', mfa_on: 'Two-step turned on', mfa_off: 'Two-step turned off',
  mfa_recovery_used: 'Recovery code used', mfa_recovery_new: 'New recovery codes', mfa_reset_by_owner: 'Two-step reset by owner', password_reset_by_admin: 'Password reset by admin', gaming_mode: 'Gaming mode', model_unloaded: 'Model unloaded', idle_unload_changed: 'Idle unload changed', model_published: 'Model published', model_checks: 'Safety checks', app_added: 'App added', app_changed: 'App changed', app_key_rotated: 'App key replaced', reauth_fail: 'Wrong password or code', email_changed: 'Email changed', session_revoked: 'Device signed out', key_rotated: 'Key replaced',
  pair_created: 'Sign-in link made', pair_used: 'Sign-in link used', user_added: 'Person added', ban: 'Account turned off', unban: 'Account turned on', signups_changed: 'Sign-up rule changed', invite_made: 'Invite made', bad_origin: 'Cross-site request refused', email_code: 'Email code sent'};

async function sxFill(kind, box) {
  try {
    if (kind === 'devices') {
      const j = await (await api('/api/sessions')).json();
      box.replaceChildren(...j.sessions.map((d) => el('div', {class: 'srow inline', style: 'border:0;padding:6px 0'}, el('div', {class: 'stxt'}, el('b', {}, d.device + (d.current ? '  ·  this device' : '')), el('small', {}, 'Last used ' + sxWhen(d.last_seen) + (d.where ? ' · ' + d.where : ''))),
        el('div', {class: 'sctl'}, sxBtn('Sign out', async () => { if (d.current) { await post('/api/logout'); location.reload(); } else { await post('/api/sessions/revoke', {id: d.id}); sxFill(kind, box); } })))),
        ...(j.sessions.length > 1 ? [el('div', {}, sxBtn('Sign out every other device', async () => { await post('/api/sessions/revoke-others'); sxFill(kind, box); }))] : []));
    } else if (kind === 'passkeys') {
      const a = SX.acct;
      box.replaceChildren(el('b', {}, 'Passkeys'), el('small', {style: 'color:var(--muted);font-size:14px'}, 'Sign in with your fingerprint, face or screen lock: nothing to type, and nothing a thief can phish. It counts as two factors, so it skips the 6-digit code.'),
        ...a.passkeys.map((p) => el('div', {class: 'srow inline', style: 'border:0;padding:6px 0'}, el('div', {class: 'stxt'}, el('b', {}, p.name), el('small', {}, 'Added ' + (p.created ? sxWhen(p.created) : ''))), el('div', {class: 'sctl'}, sxBtn('Remove', () => removePasskeyDialog(p), 'bad')))),
        el('div', {}, sxBtn(a.passkeys.length ? 'Add another passkey' : 'Add a passkey', () => addPasskeyDialog(), 'primary')));
    } else if (kind === 'custom') {
      const ta = el('textarea', {class: 'f', maxlength: '400', placeholder: 'Keep answers short and simple.', 'aria-label': 'Custom instructions', style: 'width:100%;background:var(--bg);border:1px solid var(--line);border-radius:12px;color:var(--text);padding:12px;font:inherit;min-height:90px'}, (S.state.settings.custom_instructions || ''));
      const note = el('small', {style: 'color:var(--muted)'});
      box.replaceChildren(ta, el('div', {style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap'}, sxBtn('Save', async () => { await sxSet({custom_instructions: ta.value}); note.textContent = 'Saved.'; }, 'primary'), sxBtn('Clear', async () => { ta.value = ''; await sxSet({custom_instructions: ''}); note.textContent = 'Cleared.'; }), note));
    } else if (kind === 'activity') {
      const j = await (await api('/api/account/activity')).json();
      box.classList.remove('stack'); box.style.padding = '0';
      box.replaceChildren(...(j.events.length ? j.events.map((e) => el('div', {class: 'logline'}, el('time', {}, sxWhen(e.at)), el('b', {}, EVENT_NAMES[e.kind] || e.kind), el('span', {}, [e.ip, e.detail].filter(Boolean).join(' · ')))) : [el('div', {class: 'logline'}, 'Nothing yet.')]));
    }
  } catch (e) { if (e.message !== 'login') box.textContent = 'Could not load this.'; }
}

// ---- dialogs for the account
const sxErr = () => el('div', {role: 'alert', style: 'color:var(--danger);font-size:14px'});
function sxInput(type, ph, attrs) { return el('input', Object.assign({type, placeholder: ph, autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false'}, attrs || {})); }
// "Enter your password / code" fields for sensitive changes: returns [nodes, () => body]
function reauthFields() {
  const a = SX.acct, kids = [], got = {};
  if (a.has_password) { const pw = pwBox({autocomplete: 'current-password', placeholder: 'Your password', 'aria-label': 'Your password'}); kids.push(authField('Your password', pw.node)); got.password = () => pw.input.value; }
  if (a.mfa.on) { const c = sxInput('text', '6-digit code or recovery code', {inputmode: 'text', autocomplete: 'one-time-code', 'aria-label': 'Two-step code'}); kids.push(authField('Two-step code', c, 'From your authenticator app, or a recovery code.')); got.code = () => c.value; }
  return [kids, () => Object.fromEntries(Object.entries(got).map(([k, f]) => [k, f()]))];
}
async function sxPost(url, body, err) { const r = await post(url, body); const j = await r.json().catch(() => ({})); if (!r.ok) { err.textContent = j.message || 'Something went wrong.'; return null; } return j; }
function passwordDialog() {
  const a = SX.acct, [rk, rb] = reauthFields(), err = sxErr(), pw = pwBox({autocomplete: 'new-password', placeholder: 'New password', 'aria-label': 'New password'}, true), again = pwBox({autocomplete: 'new-password', placeholder: 'Type it again', 'aria-label': 'New password again'});
  const cur = a.has_password ? rk.slice(0, 1) : [], rest = a.has_password ? rk.slice(1) : rk;
  const go = el('button', {class: 'btn', type: 'button', onclick: async () => {
    err.textContent = ''; if (pw.input.value !== again.input.value) { err.textContent = 'The two passwords do not match.'; return; }
    const b = rb(); const j = await sxPost('/api/account/password', {current: b.password, code: b.code, new: pw.input.value}, err); if (!j) return;
    m.remove(); toast('Password saved.' + (j.signed_out_others ? ' ' + j.signed_out_others + ' other device(s) were signed out.' : '')); sxReload();
  }}, a.has_password ? 'Change password' : 'Save password');
  const m = dialog([el('h2', {}, a.has_password ? 'Change password' : 'Set a password'), ...cur, authField('New password', pw.node), authField('New password again', again.node), ...rest, err, go], 'Cancel');
}
function emailDialog() {
  const a = SX.acct, [rk, rb] = reauthFields(), err = sxErr(), email = sxInput('text', 'you@example.com', {inputmode: 'email', autocomplete: 'email', value: a.email || ''});
  const go = el('button', {class: 'btn', type: 'button', onclick: async () => { err.textContent = ''; const b = rb(); const j = await sxPost('/api/account/email', Object.assign({email: email.value}, b), err); if (!j) return; m.remove(); sxReload(); }}, 'Save email');
  const m = dialog([el('h2', {}, a.email ? 'Change email' : 'Add an email'), authField('Email', email, 'Changing it means you verify it again.'), ...rk, err, go], 'Cancel');
}
function verifyEmailDialog() {
  const err = sxErr(), code = sxInput('text', '6-digit code', {inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: '6', class: 'codein'});
  const info = el('div', {class: 'authnote'}, 'Sending a code to ' + SX.acct.email + '...');
  const m = dialog([el('h2', {}, 'Verify your email'), info, authField('Code from the email', code), err, el('button', {class: 'btn', type: 'button', onclick: async () => { err.textContent = ''; const j = await sxPost('/api/account/email/verify', {code: code.value}, err); if (!j) return; m.remove(); sxReload(); }}, 'Verify')], 'Cancel');
  sxPost('/api/account/email/send', {}, err).then((j) => { info.textContent = j ? 'We sent a 6-digit code to ' + SX.acct.email + '. It works for 10 minutes.' : 'Could not send a code.'; });
}
function addPasskeyDialog() {
  const [rk, rb] = reauthFields(), err = sxErr(), name = sxInput('text', 'Name it, e.g. My phone', {'aria-label': 'Passkey name'});
  const go = async (e) => {
    err.textContent = ''; e.target.disabled = true;
    try {
      const r = await post('/api/account/passkey/begin', rb()); const o = await r.json(); if (!r.ok) { err.textContent = o.message || 'Something went wrong.'; return; }
      const cred = await navigator.credentials.create({publicKey: {challenge: b64uToBuf(o.challenge), rp: o.rp, user: {id: b64uToBuf(o.user.id), name: o.user.name, displayName: o.user.displayName}, pubKeyCredParams: o.pubKeyCredParams,
        authenticatorSelection: o.authenticatorSelection, attestation: o.attestation, timeout: o.timeout, excludeCredentials: o.excludeCredentials.map((c) => ({type: c.type, id: b64uToBuf(c.id)}))}});
      const j = await sxPost('/api/account/passkey/finish', {credential: {id: cred.id, clientDataJSON: bufToB64u(cred.response.clientDataJSON), attestationObject: bufToB64u(cred.response.attestationObject)}, name: name.value}, err);
      if (j) { m.remove(); toast('Passkey added.'); sxReload(); }
    } catch (x) { err.textContent = passkeyError(x).message || 'That did not work.'; } finally { e.target.disabled = false; }
  };
  const m = dialog([el('h2', {}, 'Add a passkey'), el('p', {style: 'margin:0;color:var(--muted)'}, 'Your device will ask for your fingerprint, face or screen lock.'), authField('Name', name), ...rk, err, el('button', {class: 'btn', type: 'button', onclick: go}, 'Continue')], 'Cancel');
}
function removePasskeyDialog(p) {
  const [rk, rb] = reauthFields(), err = sxErr();
  const m = dialog([el('h2', {}, 'Remove \u201c' + p.name + '\u201d?'), el('p', {style: 'margin:0;color:var(--muted)'}, 'It stops working here at once. Delete it from your phone or password manager too.'), ...rk, err,
    el('button', {class: 'btn danger', type: 'button', onclick: async () => { const j = await sxPost('/api/account/passkey/delete', Object.assign({id: p.id}, rb()), err); if (j) { m.remove(); sxReload(); } }}, 'Remove')], 'Keep it');
}
function recoveryCodesView(codes, onDone) {
  const text = 'Emvryx recovery codes (each works once)\n\n' + codes.join('\n') + '\n';
  const done = el('button', {class: 'btn', type: 'button', disabled: 'disabled', onclick: onDone}, 'Done');
  const saved = el('input', {type: 'checkbox', id: 'recSaved', onchange: () => { done.disabled = !saved.checked; }});
  return [el('div', {class: 'authnote'}, 'Save these now. They are shown once. Each one signs you in once if you lose your phone.'), el('div', {class: 'codes'}, ...codes.map((c) => el('code', {}, c))),
    el('div', {style: 'display:flex;gap:8px;flex-wrap:wrap'}, sxBtn('Copy', async (e) => { try { await navigator.clipboard.writeText(text); e.target.textContent = 'Copied'; } catch (x) { e.target.textContent = 'Press and hold to copy'; } }),
      el('a', {class: 'sbtn', href: 'data:text/plain;charset=utf-8,' + encodeURIComponent(text), download: 'emvryx-recovery-codes.txt'}, 'Download')),
    el('label', {style: 'display:flex;gap:10px;align-items:center'}, saved, 'I saved these somewhere safe'), done];
}
async function mfaSetupDialog() {
  const a = SX.acct, [rk, rb] = reauthFields(), err = sxErr(), box = el('div', {style: 'display:flex;flex-direction:column;gap:14px'});
  const m = dialog([el('h2', {}, 'Set up two-step sign-in'), box], 'Cancel');
  const start = async () => {
    const j = await sxPost('/api/account/mfa/start', rb(), err); if (!j) return;
    const qr = qrSvg('otpauth://totp/Emvryx:' + encodeURIComponent(a.user) + '?secret=' + j.secret.replace(/ /g, '') + '&issuer=Emvryx', 176);
    const qrBox = qr ? el('div', {style: 'align-self:center;background:#fff;border-radius:14px;padding:6px;line-height:0'}, qr) : null;
    const code = sxInput('text', '000000', {inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: '6', class: 'codein', 'aria-label': 'Code from the app'}), err2 = sxErr();
    const verify = el('button', {class: 'btn', type: 'button', onclick: async () => { err2.textContent = ''; const r = await sxPost('/api/account/mfa/enable', {code: code.value}, err2); if (!r) return;
      box.replaceChildren(el('b', {}, 'Two-step sign-in is on.'), ...recoveryCodesView(r.recovery, () => { m.remove(); sxReload(); })); m.querySelector('.dialog').lastElementChild.hidden = true; }}, 'Turn on');
    box.replaceChildren(
      el('div', {class: 'steps'}, el('div', {}, el('span', {class: 'n'}, '1'), 'Add Emvryx to an authenticator app'), el('small', {style: 'color:var(--muted)'}, 'Any one works: Google Authenticator, Microsoft Authenticator, Authy, 1Password, Bitwarden.')),
      qrBox,
      el('a', {class: 'btn', href: j.uri, style: 'text-decoration:none;text-align:center;display:flex;align-items:center;justify-content:center;min-height:48px'}, 'Open my authenticator app'),
      el('small', {style: 'color:var(--muted)'}, 'On the phone you are using, that button adds it for you. To use the QR code, scan it from another device. Or choose “enter a setup key” in your app and type this:'),
      el('div', {class: 'setupkey'}, j.secret), el('small', {style: 'color:var(--muted)'}, 'Name it Emvryx. Time based, 6 digits.'),
      el('div', {class: 'steps'}, el('div', {}, el('span', {class: 'n'}, '2'), 'Type the 6-digit code it shows')), code, err2, verify);
    code.addEventListener('input', () => { if (/^\d{6}$/.test(code.value)) verify.click(); });
  };
  if (rk.length) box.replaceChildren(el('p', {style: 'margin:0;color:var(--muted)'}, 'First, confirm it is you.'), ...rk, err, el('button', {class: 'btn', type: 'button', onclick: start}, 'Continue'));
  else start();
}
function mfaOffDialog() {
  const [rk, rb] = reauthFields(), err = sxErr();
  const m = dialog([el('h2', {}, 'Turn off two-step sign-in?'), el('p', {style: 'margin:0;color:var(--muted)'}, 'Your account will only need your password again. Confirm it is you:'), ...rk, err,
    el('button', {class: 'btn danger', type: 'button', onclick: async () => { const j = await sxPost('/api/account/mfa/disable', rb(), err); if (!j) return; m.remove(); sxReload(); }}, 'Turn off')], 'Keep it on');
}
function recoveryDialog() {
  const [rk, rb] = reauthFields(), err = sxErr(), box = el('div', {style: 'display:flex;flex-direction:column;gap:14px'});
  const m = dialog([el('h2', {}, 'New recovery codes'), box], 'Close');
  box.replaceChildren(el('p', {style: 'margin:0;color:var(--muted)'}, 'This replaces your old codes, which stop working.'), ...rk, err,
    el('button', {class: 'btn', type: 'button', onclick: async () => { const j = await sxPost('/api/account/mfa/recovery', rb(), err); if (!j) return; box.replaceChildren(...recoveryCodesView(j.recovery, () => { m.remove(); sxReload(); })); m.querySelector('.dialog').lastElementChild.hidden = true; }}, 'Make new codes'));
}
function deleteDialog() {
  const a = SX.acct, [rk, rb] = reauthFields(), err = sxErr(), typed = sxInput('text', a.user);
  const m = dialog([el('h2', {}, 'Delete your account?'), el('p', {style: 'margin:0;color:var(--muted)'}, 'This removes your chats, notes, memory, projects, GitHub link and devices, and cannot be undone. Type your name (' + a.user + ') to confirm.'), authField('Your name', typed), ...rk, err,
    el('button', {class: 'btn danger', type: 'button', onclick: async () => { const j = await sxPost('/api/delete-account', Object.assign({confirm: typed.value.trim()}, rb()), err); if (j) location.reload(); }}, 'Delete everything')], 'Keep my account');
}
async function maybeNudge() {   // the owner's account is the one that matters most: ask once per visit until it has a password and two-step sign-in
  document.querySelectorAll('#nudge').forEach((n) => n.remove());
  if (!S.state || !S.state.admin) return;
  try { const at = parseInt(localStorage.getItem('emvryx_nudge') || '0', 10); if (at && Date.now() - at < 14 * 86400000) return; } catch (e) {}
  let a; try { a = await (await api('/api/account')).json(); } catch (e) { return; }
  if (a.has_password && a.mfa.on) return;
  const bar = el('div', {class: 'nudge', id: 'nudge'}, el('span', {}, el('b', {style: 'color:var(--accenttext)'}, 'Protect the owner account: '), !a.has_password ? 'set a password' : 'turn on two-step sign-in', '.'),
    sxBtn('Do it now', () => { bar.remove(); openSettings('security'); }, 'primary'), el('button', {class: 'x', type: 'button', 'aria-label': 'Not now', onclick: () => { bar.remove(); try { localStorage.setItem('emvryx_nudge', String(Date.now())); } catch (e) {} }}, 'Not now'));
  $('banner').after(bar);
}
function toast(text) { const t = el('div', {class: 'sx-toast', role: 'status', style: 'pointer-events:none;position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--surface2);border:1px solid var(--line);border-radius:999px;padding:10px 18px;z-index:80;box-shadow:0 8px 24px rgba(0,0,0,.4)'}, text); document.body.append(t); setTimeout(() => t.remove(), 3500); }

// ---- the owner's pages
