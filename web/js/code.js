/* VryxCode: sessions, the work feed, the live line and the composer. */
// ---------------------------------------------------------------- VryxCode
const C = {info: null, sid: null, seen: 0, timer: null, project: null, file: null, model: null, auto: false, last: null, files: [], view: 'home', filter: 'all', env: 'local', saved: false, checkpoints: [], sessions: [], pvAuto: false, mode: 'ask', prevMode: 'ask', todo: [], events: [], todoOpen: true};
try { C.env = localStorage.getItem('emvryx_code_env') || 'local'; } catch (e) {}
const cOn = () => !$('code').hidden;
const cModel = () => (C.info ? C.info.models.find((m) => m.id === C.model) : null);
async function openCode() {
  $('code').hidden = false; document.body.classList.remove('menu-open');
  const r = await api('/api/code'); C.info = await r.json(); showUsage(C.info.usage);
  const usable = C.info.models.filter((m) => m.state === 'ready');
  if (!cModel() || cModel().state !== 'ready') C.model = (usable.find((m) => m.id === S.model) || usable[0] || C.info.models[0] || {}).id;
  C.project = C.project || C.info.running && C.info.project || C.info.projects[0] || 'my-project';
  renderCodeBar(); showHome();
}
// ---- the Sessions list: where VryxCode opens, like a to-do list of everything it has worked on
const ENV_NAME = {local: 'This computer', sandbox: 'Isolated sandbox', cloud: 'Cloud machine'};
const FILTERS = [['all', 'All'], ['running', 'Running'], ['queued', 'Queued'], ['needs', 'Needs you'], ['done', 'Finished']];
async function showHome() {
  clearTimeout(C.timer); C.view = 'home'; $('code').classList.remove('ide'); $('code').classList.add('home'); closeCodeMenus(); $('codePv').hidden = true; showDrawer(false);
  $('codeTitle').textContent = 'Code'; $('codeBack').setAttribute('aria-label', 'Back to chats'); await renderHome();
}
function envLine(e) { return e ? [icon(ENV_ICON(e.id)), el('span', {}, e.name)] : []; }
function ENV_ICON(id) { return id === 'sandbox' ? 'box' : id === 'cloud' ? 'cloud' : 'laptop'; }
async function renderHome() {
  const [r, ri] = await Promise.all([api('/api/code/sessions'), api('/api/code')]); C.sessions = (await r.json()).sessions || []; C.info = await ri.json();
  $('codeEnvs').replaceChildren(el('span', {class: 'lbl'}, 'Environments'), ...C.info.environments.map((e) => el('button', {class: 'chip', onclick: () => envInfo()}, el('span', {class: 'dot' + (e.available ? ' on' : '')}), e.name)));
  $('codeFilter').textContent = (FILTERS.find((f) => f[0] === C.filter) || FILTERS[0])[1] + ' \u25be';
  const live = ['starting', 'working'], pick = (x) => C.filter === 'all' || (C.filter === 'running' && live.includes(x.state)) || (C.filter === 'queued' && x.state === 'queued') || (C.filter === 'needs' && x.state === 'asking') || (C.filter === 'done' && !live.includes(x.state) && !['asking', 'queued'].includes(x.state));
  const rows = C.sessions.filter(pick);
  $('codeList').replaceChildren(...(rows.length ? rows.map(sessionCard) : [el('div', {class: 'empty-list'}, C.sessions.length ? 'Nothing here with this filter.' : 'No sessions yet. Tap New session to start one. Everything VryxCode does is listed here, so you can come back to it, see what it changed, or rewind it.')]));
}
function sessionCard(m) {
  const live = ['starting', 'working'].includes(m.state), ask = m.state === 'asking', queued = m.state === 'queued', bad = ['failed', 'interrupted'].includes(m.state);
  const ic = live ? el('span', {class: 'spin', 'aria-label': 'Working'}) : queued ? el('b', {style: 'font-size:15px;color:var(--muted)'}, '\u22ef') : ask ? el('b', {style: 'color:#f5a524;font-size:20px'}, '!') : bad ? el('b', {style: 'color:var(--danger);font-size:18px'}, '\u2717') : m.state === 'stopped' ? el('b', {style: 'font-size:14px'}, '\u25a0') : icon('code');
  const env = {id: m.env || 'local', name: ENV_NAME[m.env || 'local']};
  const badge = queued ? el('span', {class: 'badge'}, 'Queued' + (m.position ? ' \u00b7 #' + m.position : '')) : ask ? el('span', {class: 'badge ask'}, 'Needs you') : bad ? el('span', {class: 'badge bad'}, m.state === 'interrupted' ? 'Interrupted' : 'Failed') : m.state === 'stopped' ? el('span', {class: 'badge'}, 'Stopped') : '';
  const stats = [m.steps ? m.steps + (m.steps === 1 ? ' step' : ' steps') : '', m.files ? m.files + (m.files === 1 ? ' file' : ' files') + ' changed' : ''].filter(Boolean).join(' \u00b7 ');
  return el('div', {class: 'scard', role: 'button', tabindex: '0', onclick: () => openSession(m), onkeydown: (ev) => { if (ev.key === 'Enter') openSession(m); }},
    el('div', {class: 'top'}, el('span', {class: 'sicon'}, ic), el('div', {class: 'mid'}, el('div', {class: 't'}, m.title), el('div', {class: 'sub'}, icon(ENV_ICON(env.id)), el('span', {}, m.project + ' \u00b7 ' + env.name))), el('span', {class: 'age'}, m.age)),
    m.snippet ? el('div', {class: 'snip'}, m.snippet) : '',
    el('div', {class: 'foot'}, badge, el('span', {}, stats), el('span', {class: 'grow'}), live || ask ? '' : el('button', {class: 'del', 'aria-label': 'Delete this session', onclick: async (ev) => { ev.stopPropagation(); if (!confirm('Delete this session from the list? Your files are kept.')) return; await post('/api/code/sessions/' + m.id + '/delete', {}); renderHome(); }}, '\u00d7')));
}
function envInfo() {
  dialog([el('h2', {}, 'Environments'), el('div', {style: 'color:var(--muted)'}, 'Where VryxCode runs the code it writes. Pick one when you start a session.'),
    ...C.info.environments.map((e) => el('div', {class: 'opt', style: 'cursor:default'}, el('span', {class: 'sicon', style: 'width:36px;height:36px;border-radius:10px;background:var(--surface2);display:grid;place-items:center'}, icon(ENV_ICON(e.id))),
      el('span', {class: 'grow'}, el('b', {}, e.name + (e.available ? '' : ' \u00b7 not available')), el('small', {}, e.note))))], 'Close');
}
function resetWork() { C.todo = []; C.events = []; renderTodo(); if (typeof OUT !== 'undefined') { OUT.items = []; OUT.pending = null; if (OUT.open) outRender(); } }
function newSession() {
  C.view = 'session'; $('code').classList.remove('home'); $('codeTitle').textContent = 'VryxCode'; C.sid = null; C.saved = false; C.checkpoints = []; C.seen = 0; C.last = null; C.pvAuto = false;
  $('codeIn').replaceChildren(); $('codeGo').hidden = false; $('codeStop').hidden = true; resetWork(); renderCodeBar(); emptyFeed(); refreshFiles(); $('codeTask').focus();
}
function openSession(m) {
  C.view = 'session'; $('code').classList.remove('home'); $('codeTitle').textContent = 'VryxCode'; C.sid = m.id; C.project = m.project; C.saved = false; C.checkpoints = m.checkpoints || []; C.pvAuto = false;
  if (C.info.models.some((x) => x.id === m.model && x.state === 'ready')) C.model = m.model;
  C.seen = 0; C.last = null; $('codeIn').replaceChildren(); resetWork(); C.chatKey = C.project + '|' + C.model; renderCodeBar(); refreshFiles(); poll();
}
$('codeNew').onclick = newSession;
$('codeFilter').onclick = (e) => {
  e.stopPropagation(); const m = $('codeFilterMenu'); if (!m.hidden) { m.hidden = true; return; } closeCodeMenus();
  m.replaceChildren(...FILTERS.map(([id, name]) => el('button', {class: 'opt' + (id === C.filter ? ' sel' : ''), onclick: () => { C.filter = id; closeCodeMenus(); renderHome(); }}, el('span', {class: 'grow'}, name)))); m.hidden = false;
};
$('codeEnv').onclick = (e) => {
  e.stopPropagation(); const m = $('codeEnvMenu'); if (!m.hidden) { m.hidden = true; return; } closeCodeMenus(); if (C.sid && !C.saved) return;
  m.replaceChildren(el('div', {class: 'head'}, 'WHERE SHOULD IT RUN?'), ...C.info.environments.map((x) => el('button', {class: 'opt' + (x.id === C.env ? ' sel' : ''), disabled: !x.available,
    onclick: () => { C.env = x.id; try { localStorage.setItem('emvryx_code_env', x.id); } catch (er) {} closeCodeMenus(); renderCodeBar(); }},
    icon(ENV_ICON(x.id)), el('span', {class: 'grow'}, el('b', {}, x.name), el('small', {}, x.note)))));
  m.hidden = false;
};
function renderCodeBar() {
  $('codeProj').textContent = C.project + ' ▾';
  const m = cModel();
  $('codeModelBtn').replaceChildren(m ? (m.outside ? m.name + ' · outside' : m.label) : 'No model', el('span', {style: 'color:var(--muted)'}, '▾'));
  const env = C.info && C.info.environments.find((x) => x.id === C.env); $('codeEnv').replaceChildren(icon(ENV_ICON(C.env)), el('span', {class: 'lab'}, (env ? env.name : ENV_NAME[C.env] || 'This computer'))); $('codeEnv').disabled = !!(C.sid && !C.saved);
  C.auto = C.mode === 'auto'; $('codeAuto').replaceChildren(MODES[C.mode].short); $('codeAuto').setAttribute('aria-label', 'How VryxCode works: ' + MODES[C.mode].name);
  $('codeFilesBtn').replaceChildren(icon('folder'), el('span', {class: 'lab'}, 'Files' + (C.files.length ? ' (' + C.files.length + ')' : '')));
  $('codePreviewBtn').replaceChildren(icon('eye'), el('span', {class: 'lab'}, 'Preview'));
  ideApply();
}
function emptyFeed() {
  if (C.info && C.info.allowed === false) { $('codeIn').replaceChildren(el('div', {class: 'empty'}, el('h1', {}, 'VryxCode is not open to you yet'), el('p', {}, C.info.why_not || 'Ask the owner for access.'))); $('codeGo').disabled = true; return; }
  $('codeGo').disabled = false;
  const tip = (t) => el('button', {class: 'chip', onclick: () => { $('codeTask').value = t; $('codeTask').focus(); }}, t);
  $('codeIn').replaceChildren(el('div', {class: 'empty'}, el('h1', {}, 'What should we build?'),
    el('p', {}, 'Describe one task. VryxCode works in its own project folder: it reads, edits, runs the tests and tries again, and asks before it changes anything.'),
    el('div', {class: 'row'}, tip('Write a function with a unit test'), tip('Fix the failing test in this project'), tip('Explain what this project does')),
    el('p', {style: 'font-size:13px'}, C.files.includes('VRYX.md') ? 'Using the notes in VRYX.md. Type / for commands and @ to point at a file.' : 'Type / for commands and @ to point at a file. /init creates VRYX.md, notes VryxCode reads every time.')));
}
function closeCodeMenus() { $('codeProjMenu').hidden = true; $('codeModelMenu').hidden = true; $('codeEnvMenu').hidden = true; $('codeFilterMenu').hidden = true; $('codeModeMenu').hidden = true; $('codeSuggest').hidden = true; }
$('codeProjNew').onclick = (e) => { e.stopPropagation(); newProject(); };
$('codeProj').onclick = (e) => {
  e.stopPropagation(); const m = $('codeProjMenu'); if (!m.hidden) { m.hidden = true; return; } closeCodeMenus();
  const item = (label, fn, cls) => el('button', {class: 'opt' + (cls ? ' ' + cls : ''), onclick: () => { closeCodeMenus(); fn(); }}, el('span', {class: 'grow'}, label));
  const names = Array.from(new Set(C.info.projects.concat([C.project])));
  m.replaceChildren(el('div', {class: 'head'}, 'PROJECT'), ...names.map((n) => item(n, () => { C.project = n; C.file = null; renderCodeBar(); refreshFiles(); }, n === C.project ? 'sel' : '')),
    item('+ New project', newProject), item('Import from GitHub...', openRepoPicker), el('div', {class: 'head'}, 'THIS PROJECT'),
    item('GitHub...', openProjectGithub), item('Download as zip', () => { window.location = '/api/code/zip?project=' + encodeURIComponent(C.project); }), item('Import a zip or folder...', openImport),
    item('Delete project', deleteProject));
  m.hidden = false;
};
function newProject() {
  closeCodeMenus();
  const name = el('input', {type: 'text', placeholder: 'my-new-app', maxlength: '40', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', 'aria-label': 'Project name', style: 'width:100%;box-sizing:border-box'});
  const msg = el('div', {style: 'color:var(--muted);font-size:14px;min-height:20px'}, 'Letters, numbers, dashes and underscores. Up to 40.');
  let m;
  const make = () => {
    const n = name.value.trim();
    if (!/^[A-Za-z0-9_-]{1,40}$/.test(n)) { msg.style.color = 'var(--danger)'; msg.textContent = 'Use letters, numbers, dashes or underscores only (no spaces), up to 40.'; name.focus(); return; }
    if ((C.info.projects || []).includes(n)) { msg.style.color = 'var(--danger)'; msg.textContent = 'You already have a project called ' + n + '. Pick it from the project list instead.'; name.focus(); return; }
    C.info.projects = (C.info.projects || []).concat([n]); C.project = n; C.file = null; m.remove();
    if (C.view === 'home') newSession(); else { renderCodeBar(); refreshFiles(); }          // from the Sessions list: straight to a blank session in the new project
    toast('Started ' + n + '. Tell VryxCode what to build.');
  };
  name.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); make(); } });
  m = dialog([el('h2', {}, 'New project'), el('div', {style: 'color:var(--muted)'}, 'A project is a folder of files VryxCode builds in. Give it a short name.'), name, msg],
    'Cancel', el('button', {class: 'btn primary', type: 'button', onclick: make}, 'Create project'));
  setTimeout(() => name.focus(), 50);
}
async function deleteProject() {
  if (!confirm('Delete the project "' + C.project + '" and all its files? This cannot be undone.')) return;
  const r = await post('/api/code/projects/delete', {project: C.project}); const j = await r.json();
  if (!r.ok) { note('bad', 'COULD NOT DELETE', j.message + ' ' + (j.action || '')); return; }
  C.info.projects = C.info.projects.filter((p) => p !== C.project); C.project = C.info.projects[0] || 'my-project'; renderCodeBar(); refreshFiles();
}
$('codeModelBtn').onclick = (e) => {
  e.stopPropagation(); const m = $('codeModelMenu'); if (!m.hidden) { m.hidden = true; return; } closeCodeMenus();
  m.replaceChildren(el('div', {class: 'head'}, 'WHICH MODEL SHOULD CODE?'), ...C.info.models.map((x) => el('button', {class: 'opt' + (x.id === C.model ? ' sel' : ''), disabled: x.state !== 'ready',
    onclick: () => { C.model = x.id; closeCodeMenus(); renderCodeBar(); }}, el('span', {class: 'grow'}, el('b', {}, x.label), el('small', {}, x.state === 'ready' ? (x.note || 'Ready') : x.badge)))));
  m.hidden = false;
};
document.addEventListener('click', (e) => { if (cOn() && !e.target.closest('.menu')) closeCodeMenus(); });
const MODES = {ask: {short: 'Ask', name: 'Ask before editing', note: 'It asks you before it changes a file or runs something.'},
  auto: {short: 'Auto-edit', name: 'Edit without asking', note: 'It writes and edits files by itself. It still asks before anything riskier.'},
  plan: {short: 'Plan', name: 'Plan first', note: 'It only looks around and writes a plan. Nothing is changed until you tap Build it.'}};
function setMode(m) { if (m === 'plan' && C.mode !== 'plan') C.prevMode = C.mode; C.mode = m; renderCodeBar(); }
$('codeAuto').onclick = (e) => {
  e.stopPropagation(); const m = $('codeModeMenu'); if (!m.hidden) { m.hidden = true; return; } closeCodeMenus();
  m.replaceChildren(el('div', {class: 'head'}, 'HOW SHOULD IT WORK?'), ...Object.entries(MODES).map(([id, x]) => el('button', {class: 'opt' + (id === C.mode ? ' sel' : ''), onclick: () => { closeCodeMenus(); setMode(id); }},
    el('span', {class: 'grow'}, el('b', {}, x.name), el('small', {}, x.note)))));
  m.hidden = false;
};
$('codeBack').onclick = () => { if (C.view === 'session') { showHome(); return; } $('code').hidden = true; clearTimeout(C.timer); closeCodeMenus(); };
function showDrawer(on, tab) {
  $('codeDrawer').hidden = !on; if (!on) return; tab = tab || C.tab || 'files'; C.tab = tab;
  document.querySelectorAll('#codeDrawer .dtabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
  $('tabFiles').hidden = tab !== 'files'; $('tabChanges').hidden = tab !== 'changes'; $('tabRewind').hidden = tab !== 'rewind';
  if (tab === 'changes') renderChanges(); if (tab === 'rewind') renderRewind();
}
document.querySelectorAll('#codeDrawer .dtabs button').forEach((b) => { b.onclick = () => showDrawer(true, b.dataset.tab); });
// what this session changed, from the steps it took (the diff lines each edit showed)
function changesFromEvents() {
  const files = new Map();
  for (const e of C.events) {
    if (e.kind !== 'step' || (e.tool !== 'write_file' && e.tool !== 'edit_file')) continue;
    const lines = String(e.preview || '').split('\n'), m = /^(?:write|edit) (\S+)/.exec(lines[0] || ''); if (!m) continue;
    const f = files.get(m[1]) || {path: m[1], add: 0, del: 0, lines: []};
    for (const l of lines.slice(1)) { if (/^\s*\+ /.test(l)) f.add++; else if (/^\s*- /.test(l)) f.del++; f.lines.push(l); }
    f.lines.push('');
    files.set(m[1], f);
  }
  return [...files.values()];
}
function renderChanges() {
  const list = changesFromEvents(), pane = $('tabChanges');
  if (!list.length) { pane.replaceChildren(el('div', {class: 'hint'}, 'Nothing has been changed in this session yet. When VryxCode edits files they are listed here with what was added and removed.')); return; }
  pane.replaceChildren(el('div', {class: 'hint'}, list.length + (list.length === 1 ? ' file' : ' files') + ' changed in this session. Long edits show only their first lines here; open the file to see all of it.'),
    ...list.map((f) => el('details', {class: 'chg'}, el('summary', {}, el('span', {class: 'nm'}, f.path), f.add ? el('span', {class: 'a'}, '+' + f.add) : '', f.del ? el('span', {class: 'd'}, '\u2212' + f.del) : ''),
      el('pre', {}, ...f.lines.filter((l) => l !== '').map((l) => el('span', {class: /^\s*\+ /.test(l) ? 'add' : /^\s*- /.test(l) ? 'del' : ''}, l))),
      el('div', {class: 'acts'}, el('button', {class: 'chip', onclick: () => { showDrawer(true, 'files'); viewFile(f.path); }}, 'Open the file')))));
}
function renderRewind() {
  const cps = [...(C.checkpoints || [])].reverse(), pane = $('tabRewind');
  if (!C.sid || !cps.length) { pane.replaceChildren(el('div', {class: 'hint'}, 'Before each of your messages VryxCode saves the project, so you can put the files back as they were. Nothing is saved yet for this session.')); return; }
  pane.replaceChildren(el('div', {class: 'hint'}, 'Put the files back as they were before one of your messages. Files made after that point are removed. Your other projects are not touched.'),
    ...cps.map((c) => el('button', {class: 'opt', onclick: async () => {
      if (!confirm('Put the files back as they were before "' + (c.label || 'message ' + c.turn) + '"?')) return;
      const r = await post('/api/code/sessions/' + C.sid + '/rewind', {turn: c.turn}); const j = await r.json().catch(() => ({}));
      if (!r.ok) { note('bad', 'Could not rewind', (j.message || '') + ' ' + (j.action || '')); return; }
      showDrawer(false); poll(); refreshFiles(); if (!$('codePv').hidden) reloadPreview();
    }}, icon('undo'), el('span', {class: 'grow'}, el('b', {}, 'Before message ' + c.turn), el('small', {}, c.label || '')))));
}
// the to-do list the model keeps (its todo tool): a card above the feed that fills in as items are ticked off
function renderTodo() {
  const box = $('codeTodo'), items = C.todo || [];
  if (!items.length) { box.hidden = true; box.replaceChildren(); return; }
  const done = items.filter((i) => i.done).length;
  box.hidden = false;
  box.replaceChildren(el('div', {class: 'th', onclick: () => { C.todoOpen = !C.todoOpen; renderTodo(); }}, el('span', {}, 'To-do ' + done + '/' + items.length), el('span', {class: 'bar'}, el('i', {style: 'width:' + Math.round(100 * done / items.length) + '%'})), el('span', {style: 'color:var(--muted)'}, C.todoOpen ? '\u25b4' : '\u25be')),
    C.todoOpen ? el('ul', {}, ...items.map((i) => el('li', {class: i.done ? 'done' : ''}, el('span', {class: 'bx'}, i.done ? '\u2713' : ''), el('span', {}, i.text)))) : '');
}
// "/" commands and "@" file mentions in the message box
// a code review: the model gets the change (this session's, or a pull request's) in Plan-first mode, so it can only read; you see one short line
async function startReview(review) {
  if (!C.sid) { note('fin', 'Open a session first', 'Start or open a VryxCode session, then use /review.'); return; }
  setMode('plan');
  const line = review.pr ? 'Review pull request ' + review.pr : 'Review the changes this session made';
  const r = await post('/api/code/sessions/' + C.sid + '/message', {text: line, plan: true, review});
  if (!r.ok) { const j = await r.json().catch(() => ({})); note('fin', 'Could not start the review', (j.message || 'Try again.') + (j.action ? ' ' + j.action : '')); return; }
  poll();
}
const SLASH = [['plan', 'Plan first: look and plan, change nothing', () => setMode('plan')], ['ask', 'Ask before editing', () => setMode('ask')], ['auto', 'Edit without asking', () => setMode('auto')],
  ['init', 'Create VRYX.md, notes VryxCode reads every session', async () => { const r = await post('/api/code/init', {project: C.project}); const j = await r.json().catch(() => ({})); note('fin', j.created ? 'Created VRYX.md' : 'VRYX.md is already there', 'Open it from Files and fill it in: what the project is, how to test it, your style rules.'); refreshFiles(); }],
  ['review', 'Review what this session changed: problems, worst first (read-only)', () => startReview({session: true})],
  ['reviewpr', 'Review a GitHub pull request (read-only): paste its link', () => { const link = prompt('Paste the pull request link, like https://github.com/owner/repo/pull/12'); if (link) startReview({pr: link}); }],
  ['changes', 'See what this session changed (the Changes list)', () => showDrawer(true, 'changes')], ['rewind', 'Put the files back to an earlier point', () => showDrawer(true, 'rewind')],
  ['files', 'Browse the project files', () => showDrawer(true, 'files')], ['preview', 'Open the live preview', () => openPreview()], ['new', 'Start a new session', () => newSession()],
  ['help', 'List these commands', () => note('fin', 'Commands', SLASH.map((x) => '/' + x[0] + ' \u2014 ' + x[1]).join('\n') + '\n@filename \u2014 point at a file in your message')]];
let SUG = {items: [], at: -1};
function suggest() {
  const t = $('codeTask'), box = $('codeSuggest'), pos = t.selectionStart, before = t.value.slice(0, pos);
  let items = [];
  const sl = /^\/(\w*)$/.exec(before);
  if (sl) items = SLASH.filter((x) => x[0].startsWith(sl[1].toLowerCase())).map((x) => ({label: '/' + x[0], sub: x[1], run: () => { t.value = ''; closeCodeMenus(); x[2](); }}));
  else { const at = /(?:^|\s)@([\w./-]*)$/.exec(before);
    if (at) { const q = at[1].toLowerCase(); items = C.files.filter((f) => f.toLowerCase().includes(q)).slice(0, 8).map((f) => ({label: '@' + f, sub: '', run: () => { const start = before.length - at[1].length - 1; t.value = t.value.slice(0, start) + '@' + f + ' ' + t.value.slice(pos); closeCodeMenus(); t.focus(); }})); } }
  SUG = {items, at: items.length ? 0 : -1};
  if (!items.length) { box.hidden = true; return; }
  box.replaceChildren(...items.map((x, i) => el('button', {class: 'opt' + (i === 0 ? ' hi' : ''), onmousedown: (e) => e.preventDefault(), onclick: x.run}, el('code', {}, x.label), x.sub ? el('span', {class: 'grow'}, el('small', {}, x.sub)) : '')));
  box.hidden = false;
}
$('codeTask').addEventListener('input', suggest);
$('codeTask').addEventListener('keydown', (e) => { if (!$('codeSuggest').hidden && SUG.items.length && (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey))) { e.preventDefault(); SUG.items[SUG.at].run(); } else if (e.key === 'Escape') $('codeSuggest').hidden = true; });
$('codeFilesBtn').onclick = () => showDrawer($('codeDrawer').hidden);
$('codeDrawerX').onclick = () => showDrawer(false);
async function refreshFiles() {
  if (!C.project) return;
  const r = await api('/api/code/files?project=' + encodeURIComponent(C.project)); const j = await r.json(); C.files = j.files; renderCodeBar();
  $('codePreviewBtn').disabled = !j.files.some((f) => /\.html?$/i.test(f));       // a web page can be previewed
  if (IDE.on) { ideTree(); ideSync(); }
  $('codeFiles').replaceChildren(...(j.files.length ? j.files.map((f) => el('button', {class: f === C.file ? 'on' : '', onclick: () => viewFile(f)}, f)) : [el('div', {style: 'color:var(--muted);padding:6px 8px;font-size:14px'}, 'No files yet.')]));
}
