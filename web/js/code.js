/* VryxCode: sessions, the work feed, the live line and the composer. */
// ---------------------------------------------------------------- VryxCode
const C = {info: null, sid: null, seen: 0, timer: null, project: null, file: null, model: null, auto: false, last: null, files: [], view: 'home', filter: 'all', env: 'local', saved: false, checkpoints: [], sessions: [], pvAuto: false, mode: 'ask', prevMode: 'ask', todo: [], events: [], todoOpen: true};
try { C.env = localStorage.getItem('emvryx_code_env') || 'local'; } catch (e) {}
C.effort = 'balanced'; try { C.effort = localStorage.getItem('emvryx_code_effort') || 'balanced'; } catch (e) {}
const oneModel = () => !!(C.info && C.info.effort);          // feature flag vryxcode_effort: no model picker, VryxCode picks the model and you pick the effort
const effortName = () => { const l = oneModel() && C.info.effort.levels.find((x) => x.id === C.effort); return l ? l.name : 'Balanced'; };
const cOn = () => !$('code').hidden;
const cModel = () => (C.info ? C.info.models.find((m) => m.id === C.model) : null);
async function openCode() {
  $('code').hidden = false; document.body.classList.remove('menu-open'); document.body.classList.add('vx'); startDots($('vxDots'), $('code'));
  const r = await api('/api/code'); C.info = await r.json(); showUsage(C.info.usage);
  const usable = C.info.models.filter((m) => m.state === 'ready');
  if (!cModel() || cModel().state !== 'ready') C.model = (usable.find((m) => m.id === S.model) || usable[0] || C.info.models[0] || {}).id;
  if (oneModel()) C.model = C.info.effort.auto || C.model;
  C.project = C.project || C.info.running && C.info.project || C.info.projects[0] || 'my-project';
  renderCodeBar(); showHome(); vxRenderTemplates(); vxNotifyInit(); maybeVryxTour();
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
  vxWhere();
  if (vxProjectsOn() && C.filter === 'all') { $('codeList').replaceChildren(...vxOrganizer(rows)); return; }
  if (vxReviewOn() && C.filter === 'all' && rows.length) {        // vryxcode_review: Working, Ready for review (finished with changes you have not opened yet), Done
    const seen = vxSeen(), busy = (x) => live.includes(x.state) || ['asking', 'queued'].includes(x.state);
    const ready = (x) => !busy(x) && x.state === 'done' && (x.added || x.removed || x.files) && seen[x.id] !== x.updated;
    const groups = [['Working', rows.filter(busy)], ['Ready for review', rows.filter(ready)], ['Done', rows.filter((x) => !busy(x) && !ready(x))]];
    $('codeList').replaceChildren(...groups.filter(([, g]) => g.length).flatMap(([name, g]) => [el('div', {class: 'vx-group'}, name.toUpperCase() + ' ' + g.length), ...g.map(sessionCard)]));
    return;
  }
  $('codeList').replaceChildren(...(rows.length ? rows.map(sessionCard) : [el('div', {class: 'empty-list'}, C.sessions.length ? 'Nothing here with this filter.' : 'No sessions yet. Tap New session to start one. Everything VryxCode does is listed here, so you can come back to it, see what it changed, or rewind it.')]));
}
const modelName = (id) => { const x = ((C.info && C.info.models) || []).find((y) => y.id === id); return x ? (x.outside ? x.name : x.label) : (id || 'model'); };
function sessionCard(m) {
  const live = ['starting', 'working'].includes(m.state), ask = m.state === 'asking', queued = m.state === 'queued', bad = ['failed', 'interrupted'].includes(m.state);
  const ic = live ? el('span', {class: 'spin', 'aria-label': 'Working'}) : queued ? el('b', {style: 'font-size:15px;color:var(--muted)'}, '\u22ef') : ask ? el('b', {style: 'color:#f5a524;font-size:20px'}, '!') : bad ? el('b', {style: 'color:var(--danger);font-size:18px'}, '\u2717') : m.state === 'stopped' ? el('b', {style: 'font-size:14px'}, '\u25a0') : icon('code');
  const env = {id: m.env || 'local', name: ENV_NAME[m.env || 'local']};
  const badge = queued ? el('span', {class: 'badge'}, 'Queued' + (m.position ? ' \u00b7 #' + m.position : '')) : ask ? el('span', {class: 'badge ask'}, 'Needs you') : bad ? el('span', {class: 'badge bad'}, m.state === 'interrupted' ? 'Interrupted' : 'Failed') : m.state === 'stopped' ? el('span', {class: 'badge'}, 'Stopped') : '';
  const stats = [m.steps ? m.steps + (m.steps === 1 ? ' step' : ' steps') : '', m.files ? m.files + (m.files === 1 ? ' file' : ' files') + ' changed' : ''].filter(Boolean).join(' \u00b7 ');
  const lines = vxReviewOn() && (m.added || m.removed) ? el('span', {class: 'vx-lines'}, el('span', {class: 'a'}, '+' + (m.added || 0)), ' ', el('span', {class: 'd'}, '\u2212' + (m.removed || 0))) : '';
  return el('div', {class: 'scard', role: 'button', tabindex: '0', onclick: () => openSession(m), onkeydown: (ev) => { if (ev.key === 'Enter') openSession(m); }},
    el('div', {class: 'top'}, el('span', {class: 'sicon'}, ic), el('div', {class: 'mid'}, el('div', {class: 't'}, m.title), el('div', {class: 'sub'}, icon(ENV_ICON(env.id)), el('span', {}, m.project + ' \u00b7 ' + modelName(m.model) + ' \u00b7 ' + env.name))), el('span', {class: 'age'}, m.age)),
    m.snippet ? el('div', {class: 'snip'}, m.snippet) : '',
    el('div', {class: 'foot'}, badge, lines, el('span', {}, stats), el('span', {class: 'grow'}), live || ask ? '' : el('button', {class: 'del', 'aria-label': 'Delete this session', onclick: async (ev) => { ev.stopPropagation(); if (!confirm('Delete this session from the list? Your files are kept.')) return; await post('/api/code/sessions/' + m.id + '/delete', {}); renderHome(); }}, '\u00d7')));
}
function envInfo() {
  dialog([el('h2', {}, 'Environments'), el('div', {style: 'color:var(--muted)'}, 'Where VryxCode runs the code it writes. Pick one when you start a session.'),
    ...C.info.environments.map((e) => el('div', {class: 'opt', style: 'cursor:default'}, el('span', {class: 'sicon', style: 'width:36px;height:36px;border-radius:10px;background:var(--surface2);display:grid;place-items:center'}, icon(ENV_ICON(e.id))),
      el('span', {class: 'grow'}, el('b', {}, e.name + (e.available ? '' : ' \u00b7 not available')), el('small', {}, e.note))))], 'Close');
}
function resetWork() { C.todo = []; C.events = []; C.ctx = null; if ($('codeCtx')) $('codeCtx').hidden = true; renderTodo(); if (typeof OUT !== 'undefined') { OUT.items = []; OUT.pending = null; if (OUT.open) outRender(); } }
function newSession() {
  C.view = 'session'; $('code').classList.remove('home'); $('codeTitle').textContent = 'VryxCode'; C.sid = null; C.saved = false; C.checkpoints = []; C.seen = 0; C.last = null; C.pvAuto = false; C.pvPage = '';
  offerReply(''); $('codeIn').replaceChildren(); $('codeGo').hidden = false; $('codeStop').hidden = true; resetWork(); renderCodeBar(); emptyFeed(); refreshFiles(); loadCmds(); C.pics = []; C.docs = []; renderPics(); $('codeTask').focus();
}
function vxOrganizer(rows) {   // vryxcode_projects: every project with its sessions under it (newest first), like Claude's list; + starts a new one in that project
  const by = {}; let n = 0;
  for (const m of rows) (by[m.project] = by[m.project] || []).push(m);
  const names = [...new Set([...Object.keys(by), ...((C.info && C.info.projects) || [])])];
  const latest = (p) => Math.max(0, ...(by[p] || []).map((m) => m.updated || 0));
  names.sort((a, b) => latest(b) - latest(a) || a.localeCompare(b));
  const seen = vxSeen(), busy = (x) => ['starting', 'working', 'asking', 'queued'].includes(x.state);
  return names.map((p) => el('div', {class: 'vx-proj'},
    el('div', {class: 'vx-phead'}, el('span', {class: 'nm'}, p), el('button', {type: 'button', class: 'add', title: 'New session in ' + p, 'aria-label': 'New session in ' + p, onclick: () => { C.project = p; newSession(); }}, '+')),
    ...((by[p] || []).length ? by[p].map((m) => { n += 1;
      const ready = !busy(m) && m.state === 'done' && (m.added || m.removed || m.files) && seen[m.id] !== m.updated;
      return el('div', {class: 'vx-prow' + (ready ? ' ready' : ''), role: 'button', tabindex: '0', onclick: () => openSession(m), onkeydown: (ev) => { if (ev.key === 'Enter') openSession(m); }},
        busy(m) ? el('span', {class: 'spin', 'aria-label': 'Working'}) : ready ? el('span', {class: 'dot', title: 'Ready for review'}) : '',
        el('span', {class: 't'}, m.title || 'Session'),
        m.added || m.removed ? el('span', {class: 'vx-lines'}, el('span', {class: 'a'}, '+' + (m.added || 0)), ' ', el('span', {class: 'd'}, '\u2212' + (m.removed || 0))) : '',
        el('span', {class: 'age'}, m.age || ''), el('span', {class: 'num'}, String(n)));
    }) : [el('div', {class: 'vx-pempty'}, 'No sessions yet')])));
}
const vxReviewOn = () => !!(S.state && S.state.features && S.state.features.vryxcode_review);
function vxSeen() { try { return JSON.parse(localStorage.getItem('emvryx_vx_seen') || '{}') || {}; } catch (e) { return {}; } }
function vxMarkSeen(m) { try { const s = vxSeen(); s[m.id] = m.updated; localStorage.setItem('emvryx_vx_seen', JSON.stringify(s)); } catch (e) { /* private window: it just stays in Ready for review */ } }
function openSession(m) {
  vxMarkSeen(m);
  C.view = 'session'; $('code').classList.remove('home'); $('codeTitle').textContent = 'VryxCode'; C.sid = m.id; C.project = m.project; C.saved = false; C.checkpoints = m.checkpoints || []; C.pvAuto = false; C.pvPage = '';
  if (C.info.models.some((x) => x.id === m.model && x.state === 'ready')) C.model = m.model;
  C.seen = 0; C.last = null; $('codeIn').replaceChildren(); resetWork(); C.chatKey = C.project + '|' + C.model; renderCodeBar(); refreshFiles(); loadCmds(); C.pics = []; C.docs = []; renderPics(); poll();
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
  if (oneModel()) {
    $('codeModelBtn').replaceChildren(el('span', {}, effortName()), el('span', {style: 'color:var(--muted)'}, ' ▾')); $('codeModelBtn').setAttribute('aria-label', 'Effort: ' + effortName());
    $('vxModel').replaceChildren(el('span', {class: 'k'}, 'Effort'), el('b', {}, effortName()), el('span', {class: 'c'}, '▾')); $('vxModel').setAttribute('aria-label', 'Effort: ' + effortName());
  } else {
    $('codeModelBtn').replaceChildren(m ? (m.outside ? m.name + ' · outside' : m.label) : 'No model', el('span', {style: 'color:var(--muted)'}, '▾'));
    $('vxModel').replaceChildren(el('span', {class: 'k'}, 'Model'), el('b', {}, m ? (m.outside ? m.name + ' · outside' : m.label) : 'none ready'), el('span', {class: 'c'}, '▾'));
  }
  const env = C.info && C.info.environments.find((x) => x.id === C.env); $('codeEnv').replaceChildren(icon(ENV_ICON(C.env)), el('span', {class: 'lab'}, (env ? env.name : ENV_NAME[C.env] || 'This computer'))); $('codeEnv').disabled = !!(C.sid && !C.saved);
  C.auto = C.mode === 'auto'; $('codeAuto').replaceChildren(MODES[C.mode].short); $('codeAuto').setAttribute('aria-label', 'How VryxCode works: ' + MODES[C.mode].name);
  $('codeFilesBtn').replaceChildren(icon('folder'), el('span', {class: 'lab'}, 'Files' + (C.files.length ? ' (' + C.files.length + ')' : '')), C.files.length ? el('span', {class: 'num'}, String(C.files.length)) : '');
  $('codeFilesBtn').setAttribute('aria-label', 'Files' + (C.files.length ? ', ' + C.files.length : ''));
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
function closeCodeMenus() { $('vxModelMenu').hidden = true; $('codeProjMenu').hidden = true; $('codeModelMenu').hidden = true; $('codeEnvMenu').hidden = true; $('codeFilterMenu').hidden = true; $('codeModeMenu').hidden = true; $('codeSuggest').hidden = true; }
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
  const r = await post('/api/code/projects/delete', {project: C.project}); const j = await r.json().catch(() => ({message: 'The server did not answer properly.', action: 'Try again in a moment.'}));
  if (!r.ok) { note('bad', 'COULD NOT DELETE', j.message + ' ' + (j.action || '')); return; }
  C.info.projects = C.info.projects.filter((p) => p !== C.project); C.project = C.info.projects[0] || 'my-project'; renderCodeBar(); refreshFiles();
}
function modelMenu(e, m) {
  e.stopPropagation(); if (!m.hidden) { m.hidden = true; return; } closeCodeMenus();
  if (oneModel()) {
    m.replaceChildren(el('div', {class: 'head'}, 'EFFORT'), ...C.info.effort.levels.map((x) => el('button', {class: 'opt' + (x.id === C.effort ? ' sel' : ''),
      onclick: () => { C.effort = x.id; try { localStorage.setItem('emvryx_code_effort', x.id); } catch (er) {} closeCodeMenus(); renderCodeBar(); }}, el('span', {class: 'grow'}, el('b', {}, x.name), el('small', {}, x.note)))));
    m.hidden = false; return;
  }
  m.replaceChildren(el('div', {class: 'head'}, 'WHICH MODEL SHOULD CODE?'), ...C.info.models.map((x) => el('button', {class: 'opt' + (x.id === C.model ? ' sel' : ''), disabled: x.state !== 'ready',
    onclick: () => { C.model = x.id; closeCodeMenus(); renderCodeBar(); }}, el('span', {class: 'grow'}, el('b', {}, x.label), el('small', {}, x.state === 'ready' ? (x.note || 'Ready') : x.badge)))));
  m.hidden = false;
}
$('codeModelBtn').onclick = (e) => modelMenu(e, $('codeModelMenu'));
$('vxModel').onclick = (e) => modelMenu(e, $('vxModelMenu'));
document.addEventListener('click', (e) => { if (cOn() && !e.target.closest('.menu')) closeCodeMenus(); });
const MODES = {ask: {short: 'Ask', name: 'Ask before editing', note: 'It asks you before it changes a file or runs something.'},
  auto: {short: 'Auto', name: 'Edit without asking', note: 'It writes and edits files by itself. It still asks before anything riskier.'},
  plan: {short: 'Plan', name: 'Plan first', note: 'It only looks around and writes a plan. Nothing is changed until you tap Build it.'}};
function setMode(m) { if (m === 'plan' && C.mode !== 'plan') C.prevMode = C.mode; C.mode = m; renderCodeBar(); }
$('codeAuto').onclick = (e) => {
  e.stopPropagation(); const m = $('codeModeMenu'); if (!m.hidden) { m.hidden = true; return; } closeCodeMenus();
  m.replaceChildren(el('div', {class: 'head'}, 'HOW SHOULD IT WORK?'), ...Object.entries(MODES).map(([id, x]) => el('button', {class: 'opt' + (id === C.mode ? ' sel' : ''), onclick: () => { closeCodeMenus(); setMode(id); }},
    el('span', {class: 'grow'}, el('b', {}, x.name), el('small', {}, x.note)))));
  m.hidden = false;
};
$('codeBack').onclick = () => { if (C.view === 'session') { showHome(); return; } $('code').hidden = true; document.body.classList.remove('vx'); clearTimeout(C.timer); closeCodeMenus(); };
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
// what this session changed: the real difference against the project as it was before the session (kept or undone file by file), or, without that, the steps' own diff lines
C.kept = C.kept || new Set();
async function renderChanges() {
  const pane = $('tabChanges');
  let list = null;
  if (C.sid) {
    try { const r = await api('/api/code/sessions/' + C.sid + '/changes'); if (r.ok) list = ((await r.json()).changes || []).filter((f) => !C.kept.has(C.sid + '|' + f.path)); } catch (e) { list = null; }
  }
  if (list) { renderRealChanges(pane, list); return; }
  const old = changesFromEvents();
  if (!old.length) { pane.replaceChildren(el('div', {class: 'hint'}, 'Nothing has been changed in this session yet. When VryxCode edits files they are listed here with what was added and removed.')); return; }
  pane.replaceChildren(el('div', {class: 'hint'}, old.length + (old.length === 1 ? ' file' : ' files') + ' changed in this session. Long edits show only their first lines here; open the file to see all of it.'),
    ...old.map((f) => el('details', {class: 'chg'}, el('summary', {}, el('span', {class: 'nm'}, f.path), f.add ? el('span', {class: 'a'}, '+' + f.add) : '', f.del ? el('span', {class: 'd'}, '\u2212' + f.del) : ''),
      el('pre', {}, ...f.lines.filter((l) => l !== '').map((l) => el('span', {class: /^\s*\+ /.test(l) ? 'add' : /^\s*- /.test(l) ? 'del' : ''}, l))),
      el('div', {class: 'acts'}, el('button', {class: 'chip', onclick: () => { showDrawer(true, 'files'); viewFile(f.path); }}, 'Open the file')))));
}
function renderRealChanges(pane, list) {
  if (!list.length) { pane.replaceChildren(el('div', {class: 'hint'}, 'Nothing to review: every change in this session has been kept, or nothing was changed.')); return; }
  const running = ['working', 'asking', 'starting'].includes(C.state);
  const kind = {new: 'New', changed: 'Changed', removed: 'Removed'};
  const others = ((C.info && C.info.models) || []).filter((m) => m.state === 'ready' && m.id !== C.model);
  pane.replaceChildren(el('div', {class: 'hint'}, list.length + (list.length === 1 ? ' file' : ' files') + ' changed since this session began. Keep what you like and undo the rest, one file at a time.'),
    others.length && C.sid && !C.saved && !oneModel() ? el('div', {class: 'second'}, el('span', {}, 'Second opinion:'), ...others.map((m) => el('button', {class: 'chip', title: 'Another model reads these changes and lists problems. It cannot change anything.', onclick: () => secondOpinion(m)}, m.label || m.name || m.id))) : '',
    ...list.map((f) => el('details', {class: 'chg'}, el('summary', {}, el('span', {class: 'nm'}, f.path), el('span', {class: 'k ' + f.status}, kind[f.status]), f.add ? el('span', {class: 'a'}, '+' + f.add) : '', f.del ? el('span', {class: 'd'}, '\u2212' + f.del) : ''),
      el('pre', {}, ...f.diff.split('\n').filter((l) => !/^(---|\+\+\+)/.test(l)).map((l) => el('span', {class: l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : ''}, l))),
      el('div', {class: 'acts'},
        el('button', {class: 'chip', onclick: () => { C.kept.add(C.sid + '|' + f.path); renderChanges(); }}, 'Keep'),
        el('button', {class: 'chip bad', disabled: running, title: running ? 'Wait for VryxCode to finish, or press Stop' : '', onclick: async () => {
          const r = await post('/api/code/sessions/' + C.sid + '/reject', {path: f.path}); const j = await r.json().catch(() => ({}));
          if (!r.ok) { note('bad', 'Could not undo', (j.message || '') + ' ' + (j.action || '')); return; }
          note('fin', 'Undone', f.path + (j.restored ? ' is back as it was.' : ' was removed.')); refreshFiles(); if (!$('codePv').hidden) reloadPreview(); renderChanges();
        }}, 'Undo this file'),
        f.status === 'removed' ? '' : el('button', {class: 'chip', onclick: () => { showDrawer(true, 'files'); viewFile(f.path); }}, 'Open')))));
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
  ['copy', 'Try an idea in a separate copy of this project (the original is not touched)', () => forkProject()],
  ['usecopy', 'Use this copy\u2019s files in the project it came from (the original is kept as -before)', () => adoptCopy()],
  ['second', 'Ask another model to check what this session changed (read-only)', () => showDrawer(true, 'changes')],
  ['changes', 'See what this session changed (the Changes list)', () => showDrawer(true, 'changes')], ['rewind', 'Put the files back to an earlier point', () => showDrawer(true, 'rewind')],
  ['files', 'Browse the project files', () => showDrawer(true, 'files')], ['preview', 'Open the live preview', () => openPreview()], ['new', 'Start a new session', () => newSession()],
  ['picture', 'Attach a screenshot or picture (or paste one into the message box)', () => pickPictures()],
  ...(vxReviewOn() ? [['attach', 'Attach a document (PDF, Word or text, like brand guidelines or a spec) for VryxCode to read first', () => pickDocs()]] : []),
  ['memory', 'What VryxCode remembers about you (forget notes)', () => showMemory()],
  ['fixci', 'Fix what is failing on GitHub for this project (reads the CI log)', () => fixCi()],
  ['watchci', 'Watch this project\u2019s CI: fix new failures by itself (owner)', () => watchCi()],
  ['permissions', 'This project\u2019s saved permission rules (always allow / never allow)', () => showRules()],
  ['tour', 'Take the VryxCode tour again', () => openVryxTour(true)],
  ['help', 'List these commands', () => note('fin', 'Commands', SLASH.map((x) => '/' + x[0] + ' \u2014 ' + x[1]).concat((C.cmds || []).map((x) => '/' + x.name + ' \u2014 ' + (x.about || 'this project\u2019s own command'))).join('\n') + '\n@filename \u2014 point at a file in your message')]];
// ---- pictures sent with the next message (the full agent sees them), memory, saved permission rules, the project's own /commands
C.pics = [];
C.docs = [];                                   // vryxcode_review: documents attached to the next message ({id, name}), read by the model before it starts
function renderPics() {
  let row = $('codePics');
  if (!row) { row = el('div', {id: 'codePics', class: 'row', style: 'gap:6px;flex-wrap:wrap;margin:4px 0'}); $('codeTask').before(row); }
  row.replaceChildren(...C.pics.map((p, i) => el('span', {class: 'chip'}, el('img', {src: p, alt: 'Picture ' + (i + 1), style: 'height:28px;border-radius:4px;vertical-align:middle;margin-right:4px'}),
    el('button', {class: 'del', 'aria-label': 'Remove picture ' + (i + 1), onclick: () => { C.pics.splice(i, 1); renderPics(); }}, '\u00d7'))),
    ...(C.docs || []).map((d, i) => el('span', {class: 'chip'}, '\u{1F4C4} ' + d.name, el('button', {class: 'del', 'aria-label': 'Remove ' + d.name, onclick: () => { C.docs.splice(i, 1); renderPics(); }}, '\u00d7'))));
  row.hidden = !C.pics.length && !(C.docs || []).length;
}
function pickDocs() {   // a PDF, Word file or text file from this device, kept in your Documents and read by VryxCode with your next message
  const f = el('input', {type: 'file', accept: '.pdf,.docx,.txt,.md,.markdown,.csv,.json,.html,.htm,.yaml,.yml', multiple: true});
  f.onchange = async () => {
    for (const file of Array.from(f.files || []).slice(0, 8)) {
      if (file.size > 10e6) { note('bad', 'Too big', file.name + ' is over 10 MB.'); continue; }
      const data = await new Promise((res) => { const rd = new FileReader(); rd.onload = () => res(String(rd.result).split(',')[1] || ''); rd.readAsDataURL(file); });
      const r = await post('/api/documents', {name: file.name, data}); const j = await r.json().catch(() => ({}));
      if (r.ok) { C.docs.push({id: j.id, name: j.name}); renderPics(); } else note('bad', 'Not attached', file.name + ': ' + (j.message || 'it could not be read.'));
    }
  };
  f.click();
}
function addPicture(file) {
  if (!file || !/^image\/(png|jpe?g|webp|gif)$/.test(file.type) || C.pics.length >= 3) return;
  if (file.size > 5 * 1024 * 1024) { note('bad', 'Picture too big', 'Pictures can be up to 5 MB.'); return; }
  const rd = new FileReader(); rd.onload = () => { C.pics.push(String(rd.result)); renderPics(); }; rd.readAsDataURL(file);
}
function pickPictures() { const f = el('input', {type: 'file', accept: 'image/png,image/jpeg,image/webp,image/gif', multiple: true}); f.onchange = () => Array.from(f.files || []).forEach(addPicture); f.click(); }
$('codeTask').addEventListener('paste', (e) => { const files = Array.from((e.clipboardData && e.clipboardData.files) || []).filter((f) => f.type.startsWith('image/')); if (files.length) { e.preventDefault(); files.forEach(addPicture); } });
async function showMemory() {
  const r = await api('/api/code/memory'); const j = await r.json().catch(() => ({notes: []}));
  let m; const forget = async (i) => { await post('/api/code/memory', {forget: i}); m.remove(); showMemory(); };
  m = dialog([el('h2', {}, 'What VryxCode remembers'), el('div', {style: 'color:var(--muted)'}, 'Short notes it saved about you and how you like to work. It reads them at the start of every session.'),
    ...(j.notes.length ? j.notes.map((n, i) => el('div', {class: 'opt', style: 'cursor:default'}, el('span', {class: 'grow'}, n), el('button', {class: 'chip', onclick: () => forget(i)}, 'Forget'))) : [el('div', {}, 'Nothing yet.')])],
    'Close', j.notes.length ? el('button', {class: 'btn', type: 'button', onclick: () => { if (confirm('Forget everything VryxCode remembers about you?')) forget(null); }}, 'Forget all') : null);
}
async function showRules() {
  const q = '?project=' + encodeURIComponent(C.project); const r = await api('/api/code/rules' + q); const j = await r.json().catch(() => ({allow: [], deny: []}));
  let m; const change = async (body) => { const x = await post('/api/code/rules', Object.assign({project: C.project}, body)); const k = await x.json().catch(() => ({})); if (!x.ok) { note('bad', 'Could not save', k.message || ''); return; } m.remove(); showRules(); };
  const rule = el('input', {type: 'text', placeholder: 'npm test, git push, write_file ...', 'aria-label': 'Rule', style: 'flex:1'});
  const list = (kind, title) => [el('b', {}, title), ...(j[kind].length ? j[kind].map((x) => el('div', {class: 'opt', style: 'cursor:default'}, el('code', {class: 'grow'}, x), el('button', {class: 'chip', onclick: () => change({remove: x})}, 'Remove'))) : [el('div', {style: 'color:var(--muted)'}, 'None.')])];
  m = dialog([el('h2', {}, 'Permission rules for ' + C.project), el('div', {style: 'color:var(--muted)'}, 'A rule is the start of a command (npm test) or a tool (write_file). "Never" wins. "Yes, and don\u2019t ask again" adds to "Always".'),
    ...list('allow', 'Always allow'), ...list('deny', 'Never allow'),
    el('div', {class: 'row'}, rule, el('button', {class: 'chip', onclick: () => change({add: {kind: 'allow', rule: rule.value}})}, 'Always'), el('button', {class: 'chip bad', onclick: () => change({add: {kind: 'deny', rule: rule.value}})}, 'Never'))], 'Close');
}
async function fixCi() {
  const r = await post('/api/code/fixci', {project: C.project, model: C.model, effort: C.effort, env: C.env, notify: vxNotifyOn()}); const j = await r.json().catch(() => ({}));
  if (!r.ok) { note('bad', 'Could not check CI', (j.message || '') + ' ' + (j.action || '')); return; }
  if (!j.id) { note('fin', 'CI', j.message || 'Nothing is failing.'); return; }
  if (C.view === 'home') newSession();
  C.sid = j.id; C.saved = false; C.checkpoints = []; C.seen = 0; C.stopping = false; $('codeIn').replaceChildren(); poll();
}
async function watchCi() {
  const on = !((C.info && C.info.ci_watch) || []).includes(C.project);
  const r = await post('/api/code/ci-watch', {project: C.project, on, model: C.model}); const j = await r.json().catch(() => ({}));
  if (!r.ok) { note('bad', 'Could not change Watch CI', (j.message || '') + ' ' + (j.action || '')); return; }
  if (C.info) C.info.ci_watch = on ? (C.info.ci_watch || []).concat([C.project]) : (C.info.ci_watch || []).filter((p) => p !== C.project);
  note('fin', on ? 'Watching CI' : 'Stopped watching CI', on ? 'Every few minutes VryxCode looks at GitHub. When a new commit fails, your phone is told and it starts fixing it. Pushing the fix still asks you.' : C.project + ' is no longer watched.');
}
async function loadCmds() { try { const r = await api('/api/code/commands?project=' + encodeURIComponent(C.project)); C.cmds = (await r.json()).commands || []; } catch (e) { C.cmds = []; } }
let SUG = {items: [], at: -1};
function suggest() {
  const t = $('codeTask'), box = $('codeSuggest'), pos = t.selectionStart, before = t.value.slice(0, pos);
  let items = [];
  const sl = /^\/(\w*)$/.exec(before);
  if (sl) items = SLASH.filter((x) => x[0].startsWith(sl[1].toLowerCase())).map((x) => ({label: '/' + x[0], sub: x[1], run: () => { t.value = ''; closeCodeMenus(); x[2](); }}))
    .concat((C.cmds || []).filter((x) => x.name.startsWith(sl[1].toLowerCase()) && !SLASH.some((y) => y[0] === x.name)).map((x) => ({label: '/' + x.name, sub: x.about || 'this project\u2019s own command', run: () => { t.value = '/' + x.name + ' '; closeCodeMenus(); t.focus(); }})));
  else { const at = /(?:^|\s)@([\w./-]*)$/.exec(before);
    if (at) { const q = at[1].toLowerCase(); items = C.files.filter((f) => f.toLowerCase().includes(q)).slice(0, 8).map((f) => ({label: '@' + f, sub: '', run: () => { const start = before.length - at[1].length - 1; t.value = t.value.slice(0, start) + '@' + f + ' ' + t.value.slice(pos); closeCodeMenus(); t.focus(); }})); } }
  SUG = {items, at: items.length ? 0 : -1};
  if (!items.length) { box.hidden = true; return; }
  box.replaceChildren(...items.map((x, i) => el('button', {class: 'opt' + (i === 0 ? ' hi' : ''), onmousedown: (e) => e.preventDefault(), onclick: x.run}, el('code', {}, x.label), x.sub ? el('span', {class: 'grow'}, el('small', {}, x.sub)) : '')));
  box.hidden = false;
}
// The suggested reply (flag vryxcode_suggest): after a finished turn the empty message box shows what to say next, greyed out, as Claude does.
// Tab, or a swipe right across the box on a phone, fills it in; typing anything else ignores it, and sending clears it.
function offerReply(text) {
  C.offer = (S.state && S.state.features && S.state.features.vryxcode_suggest && text) ? String(text).slice(0, 200) : '';
  const t = $('codeTask'); t.placeholder = C.offer || 'Ask, answer, or tell VryxCode what to build or fix'; t.classList.toggle('offer', !!C.offer);
}
function takeOffer() {
  const t = $('codeTask'); if (!C.offer || t.value) return false;
  t.value = C.offer; offerReply(''); t.focus(); t.setSelectionRange(t.value.length, t.value.length); suggest(); return true;
}
$('codeTask').addEventListener('keydown', (e) => { if (e.key === 'Tab' && !e.shiftKey && $('codeSuggest').hidden && takeOffer()) e.preventDefault(); });
(() => {
  let x0 = null, y0 = 0;
  $('codeTask').addEventListener('touchstart', (e) => { const p = e.touches[0]; x0 = e.touches.length === 1 ? p.clientX : null; y0 = p.clientY; }, {passive: true});
  $('codeTask').addEventListener('touchend', (e) => { const p = e.changedTouches[0]; if (x0 != null && p.clientX - x0 > 60 && Math.abs(p.clientY - y0) < 40) takeOffer(); x0 = null; }, {passive: true});
})();
$('codeTask').addEventListener('input', suggest);
$('codeTask').addEventListener('keydown', (e) => { if (!$('codeSuggest').hidden && SUG.items.length && (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey))) { e.preventDefault(); SUG.items[SUG.at].run(); } else if (e.key === 'Escape') $('codeSuggest').hidden = true; });
$('codeFilesBtn').onclick = () => showDrawer($('codeDrawer').hidden);
$('codeDrawerX').onclick = () => showDrawer(false);
let pfView = 0;          // the Files drawer shows one thing at a time (the list, search hits or the map): only the newest request may draw it
async function refreshFiles() {
  if (!C.project) return;
  const view = ++pfView;
  const r = await api('/api/code/files?project=' + encodeURIComponent(C.project)); const j = await r.json(); C.files = j.files; renderCodeBar();
  $('codePreviewBtn').disabled = !j.files.some((f) => /\.html?$/i.test(f));       // a web page can be previewed
  if (IDE.on) { ideTree(); ideSync(); }
  if (view !== pfView) return;                                                   // a search or the map was asked for meanwhile: leave it showing
  $('codeFiles').replaceChildren(...(j.files.length ? j.files.map((f) => el('button', {class: f === C.file ? 'on' : '', onclick: () => viewFile(f)}, f)) : [el('div', {style: 'color:var(--muted);padding:6px 8px;font-size:14px'}, 'No files yet.')]));
}

// ---- the home screen's start box and idea chips (a session starts the moment you press Build it)
const VX_IDEAS = [['Bill splitter', 'A bill splitter: bill, tip percentage and number of people, and it shows what each person pays.'],
  ['To-do list', 'A to-do list that saves in the browser, with tick, delete and filter, and looks good on a phone.'],
  ['Focus timer', 'A focus timer with 25 and 5 minute rounds, a progress ring and a sound at the end.'],
  ['Snake', 'The game Snake in one HTML file with arrow keys and swipe controls, a score and a high score.'],
  ['Habit tracker', 'A 7-day habit grid I can tick off, with a streak counter, saved in the browser.']];
function vxRenderChips() {
  $('vxChips').replaceChildren(...VX_IDEAS.map(([name, text]) => el('button', {type: 'button', onclick: () => { $('vxQuick').value = text; $('vxQuick').focus(); }}, el('b', {}, '+'), name)));
}
// starters: a small working project the model fills in (coding/templates.py). Tap one, say what you want, press Build it.
async function vxRenderTemplates() {
  let list = [];
  try { list = ((await (await api('/api/code/templates')).json()).templates) || []; } catch (e) { /* the chips alone are fine */ }
  $('vxTpl').hidden = !list.length;
  $('vxTpls').replaceChildren(...list.map((t) => el('button', {type: 'button', class: C.template === t.id ? 'on' : '', title: t.desc, onclick: () => {
    C.template = C.template === t.id ? null : t.id;
    $('vxQuick').placeholder = C.template ? 'Make it yours: ' + t.idea : 'A bill splitter with tip, a habit tracker, a snake game...';
    $('vxTpls').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.id === C.template)); $('vxQuick').focus();
  }, 'data-id': t.id}, el('span', {}, t.icon), el('b', {}, t.name), el('small', {}, t.desc))));
}
const vxFreeName = (base) => { const have = new Set((C.info && C.info.projects) || []); let n = base, i = 2; while (have.has(n)) n = base + '-' + i++; return n; };
const vxProjectsOn = () => !!(S.state && S.state.features && S.state.features.vryxcode_projects);
function vxIdeaName(text) {   // "A bill splitter with tip and people" -> "bill-splitter": a short folder name made from the idea
  const t = String(text || '').toLowerCase().replace(/^(please\s+)?((can|could) you\s+)?((make|build|create|write|code|give)( me)?\s+)?((a|an|the|my|me)\s+)?/, '');
  const words = t.split(/\s(?:with|that|which|where|for|using|in|so|to)\s|[,.;:!?()]/)[0].replace(/[^a-z0-9\s-]/g, ' ').trim().split(/\s+/).filter(Boolean).slice(0, 4);
  return (words.join('-').slice(0, 32).replace(/-+$/, '')) || 'new-project';
}
function vxWhere() {          // under the box: where the idea will be built
  const row = $('vxWhere'); if (!row) return;
  row.hidden = !vxProjectsOn(); if (row.hidden) return;
  const text = $('vxQuick').value.trim(), here = C.buildHere && C.project;
  row.replaceChildren(here ? el('span', {}, 'Builds in ', el('b', {}, C.project), ' \u00b7 ') : el('span', {}, 'Builds in a new project' + (text ? ': ' : ''), text ? el('b', {}, vxFreeName(vxIdeaName(text))) : '', ' \u00b7 '),
    el('button', {type: 'button', class: 'link', onclick: () => { C.buildHere = !here; vxWhere(); }}, here ? 'use a new project instead' : 'use ' + (C.project || 'the current project') + ' instead'));
}
$('vxQuickGo').onclick = () => {
  const text = $('vxQuick').value.trim();
  if (!text && !C.template) { $('vxQuick').focus(); return; }
  const tpl = C.template; C.template = null;
  const fresh = !tpl && vxProjectsOn() && !C.buildHere ? vxFreeName(vxIdeaName(text)) : null;      // vryxcode_projects: a new idea gets its own project
  newSession(); C.startTemplate = tpl; if (tpl) C.project = vxFreeName(tpl);
  if (fresh) { C.project = fresh; C.info.projects = (C.info.projects || []).concat([fresh]); renderCodeBar(); }
  C.buildHere = false; $('codeTask').value = text; $('vxQuick').value = ''; $('codeGo').click();
};
$('vxQuick').addEventListener('input', () => vxWhere());
$('vxQuick').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('vxQuickGo').click(); } });
vxRenderChips();
// the phone notification (owner only; it needs the ntfy topic from Admin > Security): remembered on this device
const vxNotifyOn = () => { try { return localStorage.getItem('vx_notify') === '1'; } catch (e) { return false; } };
function vxNotifyInit() {
  const row = $('vxNotifyRow'); row.hidden = !(S.state && S.state.owner); $('vxNotify').checked = vxNotifyOn();
}
$('vxNotify').onchange = () => { try { localStorage.setItem('vx_notify', $('vxNotify').checked ? '1' : '0'); } catch (e) { /* it simply is not remembered */ } };

// ---- search the project, and its map (coding/code_map.py): what is where, made from the files alone; "Explain this project" asks the model to put it in words
let pfSearchTimer = null;
$('codeSearch').addEventListener('input', () => {
  clearTimeout(pfSearchTimer); const q = $('codeSearch').value.trim();
  if (q.length < 2) { refreshFiles(); return; }
  pfSearchTimer = setTimeout(async () => {
    const view = ++pfView;
    const r = await api('/api/code/search?project=' + encodeURIComponent(C.project) + '&q=' + encodeURIComponent(q)); const j = await r.json().catch(() => ({hits: []}));
    if ($('codeSearch').value.trim() !== q || view !== pfView) return;             // typed on, or asked for something else, meanwhile
    $('codeFiles').replaceChildren(...(j.hits.length ? j.hits.map((h) => el('button', {onclick: () => viewFile(h.path)}, el('b', {}, h.path + (h.line ? ':' + h.line : '')), el('small', {style: 'display:block;color:var(--muted)'}, h.text)))
      : [el('div', {style: 'color:var(--muted);padding:6px 8px;font-size:13px'}, 'Nothing matches "' + q + '".')]));
  }, 250);
});
$('codeMapBtn').onclick = async () => {
  clearTimeout(pfSearchTimer); const view = ++pfView;
  const r = await api('/api/code/map?project=' + encodeURIComponent(C.project)); const m = await r.json().catch(() => null);
  if (!m || view !== pfView) return;
  const langs = Object.entries(m.languages).map(([k, v]) => k + ' ' + v).join(' \u00b7 ');
  const box = el('div', {class: 'vx-map'}, el('p', {}, m.files + (m.files === 1 ? ' file' : ' files') + (langs ? ' \u00b7 ' + langs : '') + (m.entry ? ' \u00b7 starts at ' + m.entry : '')),
    ...(m.outline.length ? m.outline.map((o) => el('div', {class: 'o'}, el('b', {}, o.path), el('span', {}, o.items.slice(0, 8).join(', ')))) : [el('p', {}, 'Nothing to map yet.')]),
    el('div', {class: 'acts'}, C.sid && !C.saved ? el('button', {class: 'chip', onclick: async () => {
      const x = await post('/api/code/sessions/' + C.sid + '/message', {text: 'Explain this project', explain: true}); const j = await x.json().catch(() => ({}));
      if (!x.ok) { note('bad', 'Could not start', (j.message || '') + ' ' + (j.action || '')); return; }
      showDrawer(false); poll();
    }}, 'Explain this project') : el('small', {}, 'Open a session to ask VryxCode to explain it.')));
  $('codeFiles').replaceChildren(box);
};

// ---- parallel tries and a second opinion
async function forkProject() {
  if (!C.project) return;
  const r = await post('/api/code/projects/fork', {project: C.project}); const j = await r.json().catch(() => ({}));
  if (!r.ok) { note('bad', 'Could not make a copy', (j.message || '') + ' ' + (j.action || '')); return; }
  C.project = j.project; newSession(); note('fin', 'Working in a copy', 'This is "' + j.project + '", a separate copy. Try your idea here; the original is not touched. When you like it, type /usecopy.');
}
async function adoptCopy() {
  const m = /^(.*)-try(-\d+)?$/.exec(C.project || ''); if (!m) { note('fin', 'This is not a copy', 'Make one first with /copy, try your idea there, then come back to /usecopy.'); return; }
  if (!confirm('Use the files of "' + C.project + '" in "' + m[1] + '"? "' + m[1] + '" is kept first as "' + m[1] + '-before".')) return;
  const r = await post('/api/code/projects/adopt', {copy: C.project, into: m[1]}); const j = await r.json().catch(() => ({}));
  if (!r.ok) { note('bad', 'Could not use the copy', (j.message || '') + ' ' + (j.action || '')); return; }
  C.project = j.project; newSession(); note('fin', 'Done', '"' + j.project + '" now has the copy\u2019s files. Your old version is saved as "' + j.backup + '".');
}
async function secondOpinion(model) {
  const r = await post('/api/code/sessions/' + C.sid + '/second-opinion', {model: model.id, notify: vxNotifyOn()}); const j = await r.json().catch(() => ({}));
  if (!r.ok) { note('bad', 'Could not ask', (j.message || '') + ' ' + (j.action || '')); return; }
  showDrawer(false); C.model = model.id; renderCodeBar();
  C.sid = j.id; C.saved = false; C.checkpoints = []; C.pvAuto = false; C.chatKey = C.project + '|' + C.model; C.seen = 0; $('codeIn').replaceChildren(); poll();
}
