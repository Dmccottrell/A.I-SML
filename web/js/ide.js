/* The Editor layout: files, editor, output panel, autocomplete. */
// ---------------------------------------------------------------- Editor layout (wide screens): files | editor | VryxCode | preview
const IDE = {want: false, on: false, tabs: [], active: -1, ed: null, busy: false, project: null};
try { IDE.want = localStorage.getItem('emvryx_ide') === '1'; } catch (e) {}
const ideCan = () => matchMedia('(min-width: 1100px)').matches;
const ideBase = (p) => p.split('/').pop();
function ideApply() {                       // idempotent: it is called after every file refresh, so it only redraws when something really changed
  const on = IDE.want && ideCan() && C.view === 'session', was = IDE.on;
  IDE.on = on; $('code').classList.toggle('ide', on); $('codeIdeBtn').classList.toggle('on', IDE.want);
  if (!on) return;
  if (IDE.project !== C.project) {          // another project: tabs of the old one go, unless they hold unsaved changes (those keep their own project)
    IDE.project = C.project; ideStash();
    const cur = IDE.tabs[IDE.active]; IDE.tabs = IDE.tabs.filter((t) => t.dirty || t.project === C.project);
    IDE.active = cur && IDE.tabs.includes(cur) ? IDE.tabs.indexOf(cur) : IDE.tabs.length - 1; ideTree(); ideRenderTabs(); ideShow(); return;
  }
  if (!was) { ideStash(); ideTree(); ideRenderTabs(); ideShow(); }
}
$('codeIdeBtn').onclick = () => { IDE.want = !IDE.want; try { localStorage.setItem('emvryx_ide', IDE.want ? '1' : '0'); } catch (e) {} ideApply(); };
addEventListener('resize', () => { if ($('code').hidden) return; ideApply(); });
function ideTree() {
  const rows = [], seen = new Set(), cur = IDE.tabs[IDE.active];
  [...(C.files || [])].sort().forEach((f) => {
    const parts = f.split('/');
    parts.slice(0, -1).forEach((d, i) => { const p = parts.slice(0, i + 1).join('/'); if (!seen.has(p)) { seen.add(p); rows.push(el('div', {class: 'idir', style: 'padding-left:' + (8 + i * 12) + 'px'}, '\u25b8 ' + d)); } });
    rows.push(el('button', {class: 'ifile' + (cur && cur.path === f ? ' on' : ''), 'data-ext': (f.split('.').pop() || '').toLowerCase(), style: '--d:' + ((parts.length - 1) * 12) + 'px', title: f, onclick: () => ideOpen(f)}, ideBase(f)));
  });
  $('ideFiles').replaceChildren(...(rows.length ? rows : [el('div', {style: 'color:var(--muted);padding:6px 8px;font-size:14px'}, 'No files yet. Tap + New, or ask VryxCode.')]));
}
function ideEditor() {
  if (!IDE.ed) IDE.ed = EmvryxEditor.makeEditor($('ideBody'), {onChange: ideChanged, onSave: ideSave, onEdit: () => aiStart('edit'), onType: acTyped});
  return IDE.ed;
}
function ideStash() {                       // remember the text and cursor of the tab being left
  const t = IDE.tabs[IDE.active]; if (!t || !IDE.ed || t.readOnly) return;
  t.text = IDE.ed.getText(); t.state = IDE.ed.state();
}
function ideShow() {                        // draw the active tab in the editor (or the empty message)
  const body = $('ideBody'), t = IDE.tabs[IDE.active];
  if (!t) { if (IDE.ed) { body.replaceChildren(); IDE.ed = null; } body.replaceChildren(el('div', {class: 'iempty'}, el('div', {class: 'vx-mark'}, '</>'), el('b', {}, 'Pick a file to edit'), el('span', {}, 'VryxCode works in the chat on the right. When it changes a file you have open, it updates here.'))); ideStatus('', ''); $('ideLang').textContent = ''; $('ideSave').hidden = true; $('ideEditSel').hidden = true; $('ideExplain').hidden = true; ideConflict(); return; }
  if (!IDE.ed || !body.querySelector('.ed')) { body.replaceChildren(); IDE.ed = null; }
  const ed = ideEditor(); ed.setReadOnly(t.readOnly); ed.setLang(EmvryxEditor.langOf(t.path)); ed.setText(t.text); ed.restore(t.state);
  $('ideLang').textContent = EmvryxEditor.langOf(t.path); $('ideSave').hidden = !!t.readOnly; $('ideEditSel').hidden = !!t.readOnly; $('ideExplain').hidden = false;
  ideStatus(t.readOnly ? (t.note || 'Read-only') : t.dirty ? 'Unsaved changes' : '', t.readOnly ? '' : t.dirty ? '' : '');
  ideConflict();
}
function ideStatus(text, cls) { const n = $('ideStatus'); n.textContent = text; n.className = cls || ''; }
function ideRenderTabs() {
  $('ideTabs').replaceChildren(...IDE.tabs.map((t, i) => el('div', {class: 'itab' + (i === IDE.active ? ' on' : ''), role: 'tab', title: t.path, onclick: () => ideActivate(i)},
    el('span', {}, ideBase(t.path) + (t.project !== C.project ? ' (' + t.project + ')' : '') + (t.dirty ? ' \u25cf' : '')), el('button', {class: 'x', 'aria-label': 'Close ' + t.path, onclick: (ev) => { ev.stopPropagation(); ideClose(i); }}, '\u00d7'))));
}
function ideActivate(i) { if (AI.open) aiClose(); ideStash(); IDE.active = i; ideRenderTabs(); ideShow(); ideTree(); }
async function ideOpen(path) {
  const have = IDE.tabs.findIndex((t) => t.path === path && t.project === C.project);
  if (have >= 0) { ideActivate(have); return; }
  const r = await api('/api/code/file?project=' + encodeURIComponent(C.project) + '&path=' + encodeURIComponent(path)); const j = await r.json().catch(() => ({}));
  if (!r.ok) { ideStatus(j.message || 'Could not open that file.', 'bad'); return; }
  const binary = j.text === '(a binary file)';
  ideStash();
  IDE.tabs.push({path, project: C.project, text: binary ? '' : j.text, orig: j.text, disk: j.text, dirty: false, readOnly: binary || !!j.truncated, note: binary ? 'A binary file: it cannot be edited here.' : j.truncated ? 'Too big to edit here (the editor shows the first 200 KB).' : '', state: null, conflict: null});
  IDE.active = IDE.tabs.length - 1; ideRenderTabs(); ideShow(); ideTree();
}
function ideChanged(text) {
  const t = IDE.tabs[IDE.active]; if (!t) return;
  const dirty = text !== t.orig; t.text = text;
  if (dirty !== t.dirty) { t.dirty = dirty; ideRenderTabs(); ideStatus(dirty ? 'Unsaved changes' : '', ''); }
}
async function ideSave() {
  const t = IDE.tabs[IDE.active]; if (!t || t.readOnly || IDE.busy) return;
  ideStash(); IDE.busy = true; ideStatus('Saving\u2026', '');
  try {
    const text = t.text, r = await post('/api/code/file', {project: t.project, path: t.path, text}); const j = await r.json().catch(() => ({}));
    if (!r.ok) { ideStatus((j.message || 'Could not save.') + (j.action ? ' ' + j.action : ''), 'bad'); return; }
    t.orig = t.disk = text.replace(/\r\n/g, '\n'); t.dirty = t.text !== t.orig; t.conflict = null; ideRenderTabs(); ideConflict(); ideStatus('Saved', 'good'); refreshFiles();
  } finally { IDE.busy = false; }
}
$('ideSave').onclick = ideSave;
function ideClose(i) {
  const t = IDE.tabs[i]; if (t.dirty && !confirm('Close ' + ideBase(t.path) + ' without saving your changes?')) return;
  if (i === IDE.active) ideStash();
  IDE.tabs.splice(i, 1);
  IDE.active = IDE.tabs.length ? Math.min(i === IDE.active ? Math.max(0, i - 1) : (i < IDE.active ? IDE.active - 1 : IDE.active), IDE.tabs.length - 1) : -1;
  ideRenderTabs(); ideShow(); ideTree();
}
$('ideNew').onclick = async () => {
  const name = (prompt('Name of the new file, like notes.txt or src/app.py') || '').trim(); if (!name) return;
  const r = await post('/api/code/file', {project: C.project, path: name, text: ''}); const j = await r.json().catch(() => ({}));
  if (!r.ok) { ideStatus((j.message || 'Could not make that file.') + (j.action ? ' ' + j.action : ''), 'bad'); return; }
  await refreshFiles(); ideOpen(j.path);
};
$('ideChanges').onclick = () => showDrawer(true, 'changes'); $('ideRewind').onclick = () => showDrawer(true, 'rewind');
// VryxCode changed files on disk: update the tabs that have no edits of yours; ask about the ones that do
function ideConflict() {
  const t = IDE.tabs[IDE.active], box = $('ideConf');
  if (!t || !t.conflict) { box.hidden = true; box.replaceChildren(); return; }
  box.hidden = false;
  box.replaceChildren(el('span', {}, t.conflict.gone ? 'This file was deleted on disk while you had changes.' : 'VryxCode changed this file while you had unsaved changes.'),
    t.conflict.gone ? '' : el('button', {class: 'chip', onclick: () => { t.text = t.orig = t.disk = t.conflict.text; t.dirty = false; t.conflict = null; t.state = null; ideRenderTabs(); ideShow(); }}, 'Use VryxCode\u2019s version'),
    el('button', {class: 'chip', onclick: () => { if (!t.conflict.gone) t.disk = t.conflict.text; t.conflict = null; ideConflict(); }}, 'Keep mine'));
}
async function ideSync() {
  if (!IDE.on || !IDE.tabs.length) return;
  const run = IDE.syncRun = (IDE.syncRun || 0) + 1;          // only the newest check may change a tab: an older, slower answer would put a stale file back
  for (const t of IDE.tabs.slice()) {
    if (t.readOnly) continue;
    const r = await api('/api/code/file?project=' + encodeURIComponent(t.project) + '&path=' + encodeURIComponent(t.path)); const j = await r.json().catch(() => ({}));
    if (run !== IDE.syncRun) return;
    const here = IDE.tabs[IDE.active] === t;
    if (!r.ok) { if (r.status === 400 && !t.dirty) { continue; } if (t.dirty) t.conflict = {gone: true}; continue; }
    if (j.text === t.disk) continue;
    if (!t.dirty) { const st = here && IDE.ed ? IDE.ed.state() : t.state; t.text = t.orig = t.disk = j.text; t.state = st; if (here) ideShow(); }
    else t.conflict = {text: j.text};
    if (here) ideConflict();
  }
}

// ---- Edit this selection / Explain this: the model proposes, you see the before and after, you Accept or Reject (Accept only changes the editor; Save is separate)
const AI = {open: false, mode: 'edit', sel: null, busy: false, token: 0};
function aiStat(text, bad) { const n = $('ideAiStat'); n.textContent = text; n.className = 'aistat' + (bad ? ' bad' : ''); }
function aiClose() { AI.open = false; AI.token++; AI.busy = false; $('ideAi').hidden = true; $('ideAiRes').replaceChildren(); if (IDE.ed) IDE.ed.focus(); }
function aiStart(mode) {
  const t = IDE.tabs[IDE.active]; if (!t || !IDE.ed) return;
  if (mode === 'edit' && t.readOnly) { ideStatus('This file is read-only here.', 'bad'); return; }
  const sel = IDE.ed.selection();
  if (mode === 'explain' && !sel.text.trim()) { ideStatus('Select the code you want explained.', 'bad'); return; }
  if (!C.model) { ideStatus('Pick a model for VryxCode first.', 'bad'); return; }
  AI.open = true; AI.mode = mode; AI.sel = sel; AI.token++; $('ideAi').hidden = false; $('ideAiRes').replaceChildren();
  $('ideAiIn').hidden = mode === 'explain'; $('ideAiGo').hidden = mode === 'explain';
  aiStat(mode === 'explain' ? 'Asking ' + (cModel() ? cModel().label : 'the model') + '\u2026' : sel.text ? 'Editing ' + sel.text.split('\n').length + ' selected line(s)' : 'Nothing selected: the new code will go at the cursor');
  if (mode === 'explain') aiRun(); else { $('ideAiIn').value = ''; $('ideAiIn').focus(); }
}
async function aiRun() {
  const t = IDE.tabs[IDE.active]; if (!t || AI.busy) return;
  const instruction = $('ideAiIn').value.trim();
  if (AI.mode === 'edit' && !instruction) { aiStat('Say what to change.', true); return; }
  const token = ++AI.token; AI.busy = true; $('ideAiRes').replaceChildren(); aiStat('Working\u2026 (' + (cModel() ? cModel().label : 'the model') + ')');
  const text = IDE.ed.getText(), sel = AI.sel;
  try {
    const r = await post('/api/code/edit', {project: t.project, path: t.path, model: C.model, text, start: sel.start, end: sel.end, instruction, mode: AI.mode}); const j = await r.json().catch(() => ({}));
    if (token !== AI.token) return;                                            // closed or restarted meanwhile
    if (!r.ok) { aiStat((j.message || 'Could not do that.') + (j.action ? ' ' + j.action : ''), true); return; }
    if (AI.mode === 'explain' || !j.replacement) { aiStat(j.model ? 'Answer from ' + j.model : ''); $('ideAiRes').replaceChildren(el('div', {class: 'text'}, j.message || 'No answer.'), el('div', {class: 'acts'}, el('button', {class: 'chip', onclick: aiClose}, 'Close'))); return; }
    if (j.replacement === sel.text) { aiStat('The model proposed no change.'); $('ideAiRes').replaceChildren(el('div', {class: 'acts'}, el('button', {class: 'chip', onclick: aiClose}, 'Close'))); return; }
    aiShowDiff(sel, text, j);
  } finally { if (token === AI.token) AI.busy = false; }
}
function aiShowDiff(sel, fileText, j) {
  const rows = EmvryxEditor.diffLines(sel.text, j.replacement), out = []; let run = 0;
  rows.forEach((d, i) => {
    if (d.t === '=') { run++; const near = rows.slice(Math.max(0, i - 2), i + 3).some((x) => x.t !== '='); if (near) out.push(el('div', {}, '  ' + d.s)); else if (run === 3) out.push(el('div', {class: 'gap'}, '  \u2026')); }
    else { run = 0; out.push(el('div', {class: d.t === '+' ? 'add' : 'del'}, d.t + ' ' + d.s)); }
  });
  aiStat('Proposed by ' + (j.model || 'the model') + ': nothing has changed yet.');
  $('ideAiRes').replaceChildren(el('pre', {class: 'idiff'}, ...out), el('div', {class: 'acts'},
    el('button', {class: 'chip ok', id: 'aiAccept', onclick: () => aiAccept(sel, j.replacement)}, 'Accept'), el('button', {class: 'chip', onclick: aiClose}, 'Reject'),
    el('button', {class: 'chip', onclick: () => { $('ideAiRes').replaceChildren(); aiStat('Describe the change again.'); $('ideAiIn').focus(); $('ideAiIn').select(); }}, 'Try again')));
}
function aiAccept(sel, replacement) {
  if (!IDE.ed || IDE.ed.getText().slice(sel.start, sel.end) !== sel.text) { aiStat('The text changed while the model was working. Select it again and try again.', true); $('ideAiRes').replaceChildren(); return; }
  IDE.ed.replaceRange(sel.start, sel.end, replacement);
  aiClose(); ideStatus('Edit applied. Press Save (Ctrl+S) to keep it, or Undo (Ctrl+Z).', 'good');
}
$('ideEditSel').onclick = () => aiStart('edit'); $('ideExplain').onclick = () => aiStart('explain');
$('ideAiGo').onclick = aiRun; $('ideAiX').onclick = aiClose;
$('ideAiIn').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); aiRun(); } if (ev.key === 'Escape') aiClose(); });

// ---- Output panel: results of tests and commands (yours, and the ones VryxCode ran)
const OUT = {open: false, items: [], busy: false, pending: null};
function outRender() {
  const log = $('ideOutLog');
  log.replaceChildren(...(OUT.items.length ? OUT.items.map((i) => el('div', {class: 'oi'},
    el('div', {class: 'oc1'}, el('span', {class: 'src'}, i.src === 'agent' ? 'VryxCode' : 'You'), el('span', {class: 'cmd'}, '$ ' + i.cmd),
      i.running ? el('span', {class: 'badge2'}, 'running\u2026') : el('span', {class: 'badge2 ' + (i.exit === 0 ? 'ok' : 'bad')}, i.exit === 0 ? 'ok' : 'exit ' + i.exit + (i.secs ? ' \u00b7 ' + i.secs + 's' : ''))),
    i.out ? el('pre', {}, i.out) : '')) : [el('div', {style: 'color:var(--muted)'}, 'Nothing run yet. Press Run tests or Run file, or type a command below. What VryxCode runs shows up here too.')]));
  log.scrollTop = log.scrollHeight;
}
function outAdd(item) { OUT.items.push(item); if (OUT.items.length > 60) OUT.items.shift(); outRender(); if (!OUT.open) $('ideOutBtn').classList.add('new'); return item; }
function outShow(on) { OUT.open = on; $('ideOut').hidden = !on; $('ideOutBtn').classList.remove('new'); if (on) { outRender(); } }
$('ideOutBtn').onclick = () => outShow(!OUT.open); $('outX').onclick = () => outShow(false); $('outClear').onclick = () => { OUT.items = []; outRender(); };
async function ideSaveDirty() {            // before running: keep what you typed (a failed save stops the run)
  for (const t of IDE.tabs.filter((x) => x.dirty && x.project === C.project && !x.readOnly)) {
    const at = IDE.tabs[IDE.active]; if (at !== t) { ideActivate(IDE.tabs.indexOf(t)); }
    await ideSave(); if (t.dirty) return false;
  }
  return true;
}
async function outRun(cmd) {
  if (!cmd || OUT.busy) return; if (!C.project) return;
  outShow(true); OUT.busy = true;
  try {
    if (!(await ideSaveDirty())) { outAdd({src: 'you', cmd, exit: 1, out: 'Not run: your unsaved changes could not be saved first (see the message under the editor).'}); return; }
    const item = outAdd({src: 'you', cmd, running: true, out: ''});
    const r = await post('/api/code/run', {project: C.project, command: cmd, env: C.env}); const j = await r.json().catch(() => ({}));
    item.running = false;
    if (!r.ok) { item.exit = 1; item.out = (j.message || 'Could not run it.') + (j.action ? ' ' + j.action : ''); } else { item.exit = j.exit; item.secs = j.secs; item.out = j.output; }
    outRender(); if (r.ok) refreshFiles();
  } finally { OUT.busy = false; }
}
$('outForm').onsubmit = (ev) => { ev.preventDefault(); const v = $('outCmd').value.trim(); if (v) { $('outCmd').value = ''; outRun(v); } };
$('outRunTests').onclick = () => outRun((C.files || []).some((f) => /(^|\/)(conftest\.py|pytest\.ini)$/.test(f)) ? 'python -m pytest -q' : 'python -m unittest');
const RUN_WITH = {py: 'python', js: 'node', mjs: 'node', rb: 'ruby', php: 'php', go: 'go run'};
$('outRunFile').onclick = () => {
  const t = IDE.tabs[IDE.active]; const run = t && RUN_WITH[EmvryxEditor.langOf(t.path) === 'py' ? 'py' : (t.path.split('.').pop() || '').toLowerCase()];
  if (!t || !run) { outShow(true); outAdd({src: 'you', cmd: '(run file)', exit: 1, out: 'Open a .py, .js, .go, .rb or .php file first, or type the command below.'}); return; }
  outRun(run + ' ' + t.path);
};
// what VryxCode runs (called from cEvent)
function outAgentStep(e) {
  const m = /"command"\s*:\s*"((?:[^"\\]|\\.)*)"/.exec(String(e.preview || '')); if (!m) { OUT.pending = null; return; }
  let cmd = m[1]; try { cmd = JSON.parse('"' + m[1] + '"'); } catch (x) {}
  OUT.pending = outAdd({src: 'agent', cmd, running: true, out: ''});
}
function outAgentResult(e) {
  const i = OUT.pending; if (!i) return; OUT.pending = null;
  const t = String(e.text || ''), first = t.split('\n')[0], m = /^exit code (-?\d+)/.exec(first);
  i.running = false; i.exit = m ? +m[1] : (/^error/.test(first) ? 1 : 0); i.out = m ? t.split('\n').slice(1).join('\n') : t; outRender();
}

// ---- Autocomplete: grey suggestions while you type (off by default; Tab accepts, Esc dismisses)
const AC = {on: false, timer: 0, token: 0, busy: false};
try { AC.on = localStorage.getItem('emvryx_ac') === '1'; } catch (e) {}
function acPaint() { $('ideAc').textContent = 'Autocomplete: ' + (AC.on ? 'On' : 'Off'); $('ideAc').classList.toggle('on', AC.on); }
$('ideAc').onclick = () => { AC.on = !AC.on; try { localStorage.setItem('emvryx_ac', AC.on ? '1' : '0'); } catch (e) {} AC.token++; clearTimeout(AC.timer); if (IDE.ed) IDE.ed.clearGhost(); $('acStat').textContent = ''; acPaint(); };
function acTyped(text, cursor) {
  AC.token++; clearTimeout(AC.timer); $('acStat').textContent = '';
  const t = IDE.tabs[IDE.active];
  if (!AC.on || !t || t.readOnly || !C.model || AI.open || !text.trim()) return;
  AC.timer = setTimeout(() => acFetch(t), 650);
}
async function acFetch(t) {
  if (!IDE.ed || IDE.tabs[IDE.active] !== t) return;
  if (AC.busy) { AC.timer = setTimeout(() => acFetch(t), 400); return; }           // one request at a time: ask again when it is done
  const text = IDE.ed.getText(), cursor = IDE.ed.cursor(), token = ++AC.token;
  AC.busy = true; $('acStat').textContent = 'suggesting\u2026';
  try {
    const r = await post('/api/code/complete', {project: t.project, path: t.path, model: C.model, text, cursor}); const j = await r.json().catch(() => ({}));
    $('acStat').textContent = '';
    if (!r.ok) {
      if (/Slow down/.test(j.message || '')) { if (token === AC.token) AC.timer = setTimeout(() => acFetch(t), 1100); return; }   // asked too soon after the last one: ask again in a moment (unless they typed on)
      if (!/Slow down/.test(j.message || '')) { $('acStat').textContent = (j.message || 'autocomplete paused').slice(0, 60); if (/usage|tank|week|ready|resting|not in your plan/i.test(j.message || '')) { AC.on = false; acPaint(); } }
      return;
    }
    if (token === AC.token && j.completion && IDE.ed && IDE.tabs[IDE.active] === t && IDE.ed.getText() === text && IDE.ed.cursor() === cursor) IDE.ed.setGhost(j.completion);
  } finally { AC.busy = false; }
}
acPaint();
addEventListener('beforeunload', (ev) => { if (IDE.tabs.some((t) => t.dirty)) { ev.preventDefault(); ev.returnValue = ''; } });
async function viewFile(f) {
  C.file = f; const r = await api('/api/code/file?project=' + encodeURIComponent(C.project) + '&path=' + encodeURIComponent(f)); const j = await r.json();
  $('codeView').textContent = r.ok ? j.text + (j.truncated ? '\n... (shortened)' : '') : j.message; refreshFiles();
}
function showUsage(u) {
  if (!u) return;
  $('codeUsage').textContent = u.exempt ? 'Owner: no limits' : u.plan[0].toUpperCase() + u.plan.slice(1) + ' · ' + u.tank_pct + '% left · about ' + fmt(u.steps_left) + ' coding steps';
}
function note(cls, k, text) { $('codeIn').append(el('div', {class: cls}, el('b', {}, k), el('div', {}, text))); scrollCode(); }
function scrollCode() { const f = $('codeFeed'); f.scrollTop = f.scrollHeight; }
// Past-tense words for finished actions (what the card says), and rotating present-tense words for the live line (what it is doing right now)
const DONE_VERB = {read_file: 'Read', write_file: 'Wrote', edit_file: 'Edited', run: 'Ran', list_files: 'Looked around', git: 'Git', diagnostics: 'Checked', github: 'GitHub'};
const NOW_WORDS = {
  thinking: ['Thinking', 'Pondering', 'Working it out', 'Mulling it over', 'Sketching a plan', 'Weighing it up', 'Figuring it out'],
  writing: ['Writing', 'Drafting', 'Composing', 'Putting it into words', 'Shaping a reply'],
  build: ['Building', 'Crafting', 'Assembling', 'Putting together', 'Shaping'],
  test: ['Running the tests', 'Testing it', 'Checking it works', 'Trying it out', 'Putting it through its paces'],
  run: ['Running', 'Executing', 'Trying', 'Working on'],
  read: ['Reading', 'Studying', 'Looking through', 'Taking a look at'],
  look: ['Looking around', 'Scanning the project', 'Seeing what is here'],
  git: ['Working with git', 'Handling git'], github: ['Talking to GitHub', 'Syncing with GitHub'], check: ['Checking', 'Looking for problems']};
const TOOL_KIND = {write_file: 'build', edit_file: 'build', run: 'run', read_file: 'read', list_files: 'look', git: 'git', github: 'github', diagnostics: 'check'};
function nowKind(l) {
  if (l.phase === 'thinking') return 'thinking';
  if (l.phase === 'writing') return 'writing';
  const k = TOOL_KIND[l.tool] || 'run';
  return k === 'run' && /unittest|pytest|\btest/i.test(l.target || '') ? 'test' : k;
}
function toolParts(preview, tool) {   // "Wrote" + "main.py" + "2 lines"
  const first = String(preview || '').split('\n')[0];
  const w = /^write (\S+)(?: \((\d+) lines?\))?/.exec(first); if (w) return [DONE_VERB.write_file, w[1], w[2] ? w[2] + ' lines' : ''];
  const e = /^edit (\S+)/.exec(first); if (e) return [DONE_VERB.edit_file, e[1], ''];
  const m = /^(\w+) (\{.*\})$/.exec(first);
  if (m) { try { const a = JSON.parse(m[2]); const arg = a.path || a.command || a.args || a.action || ''; return [DONE_VERB[m[1]] || m[1], String(arg), '']; } catch (x) { /* fall through */ } }
  return [DONE_VERB[tool] || tool || '', first.length > 90 ? first.slice(0, 90) + '...' : first, ''];
}
function diffNode(preview) {
  const lines = String(preview || '').split('\n').slice(1); if (!lines.length) return null;
  return el('div', {class: 'cc-diff'}, ...lines.map((l) => el('div', {class: /^\s*\+ /.test(l) ? 'add' : /^\s*- /.test(l) ? 'del' : 'hdr'}, l.replace(/^(\s*)([+-]) /, '$2 '))));
}
// the memory meter (feature flag context_meter): how full the model's memory is in this session, and when older steps get folded
function codeCtx(c, folding) {
  const b = $('codeCtx'); if (c) C.ctx = c; c = C.ctx;
  b.hidden = !(S.state && S.state.features && S.state.features.context_meter) || !c; if (b.hidden) return;
  b.style.setProperty('--p', Math.min(100, c.pct)); b.classList.toggle('near', c.used >= c.compact_at * 0.9); b.classList.toggle('busy', !!folding);
  b.textContent = Math.round(c.pct) + '%'; b.setAttribute('aria-label', 'Memory ' + Math.round(c.pct) + '% used, ' + kTok(c.used) + ' of ' + kTok(c.window) + ' tokens');
  if (folding) setTimeout(() => b.classList.remove('busy'), 2500);
}
$('codeCtx').onclick = () => {
  const m = $('codeCtxMenu'); if (!m.hidden || !C.ctx) { m.hidden = true; return; }
  m.replaceChildren(...ctxMenuNodes(C.ctx, ['Folds at', 'When the session gets near the limit, VryxCode folds its older steps into a short "Earlier steps" list so it can keep building. Your files and this log are unchanged.'], async () => {
    let j = {};
    try { const r = await post('/api/code/sessions/' + C.sid + '/compact', {}); j = await r.json().catch(() => ({})); } catch (e) { /* shown below */ }
    m.hidden = true;
    if (j.when === 'next_step') { $('codeIn').append(el('div', {class: 'cc-say', style: 'color:var(--muted);font-size:13px'}, 'VryxCode will fold its older steps before its next step.')); scrollCode(); }
    else if (j.when === 'now' && !j.folded) { $('codeIn').append(el('div', {class: 'cc-say', style: 'color:var(--muted);font-size:13px'}, 'Nothing old enough to fold yet.')); scrollCode(); }
    poll();
  }));
  m.hidden = false;
};
document.addEventListener('click', (e) => { if (!e.target.closest('#codeCtx, #codeCtxMenu')) $('codeCtxMenu').hidden = true; });
function cEvent(e) {
  if (e.kind === 'user' || e.kind === 'start') offerReply('');          // a new message: the last suggestion no longer fits
  const feed = $('codeIn'); C.events.push(e);
  if (e.kind === 'context') { codeCtx(e); return; }
  if (e.kind === 'model') { feed.append(el('div', {class: 'note', style: 'align-self:center;margin:6px auto'}, 'Now using ' + modelName(e.model) + (e.previous ? ' (was ' + modelName(e.previous) + ')' : ''))); C.last = null; return; }
  if (e.kind === 'note' || (e.kind === 'user' && e.auto)) { if (e.kind === 'note') feed.append(el('div', {class: 'note', style: 'align-self:center;margin:6px auto;max-width:92%'}, '\u21bb ' + e.text)); C.last = null; return; }
  if (e.kind === 'user') { feed.append(el('div', {class: 'cc-user'}, el('span', {class: 'ember'}), el('span', {}, (e.plan ? '[Plan] ' : '') + e.text), e.steer ? el('small', {style: 'color:var(--muted);margin-left:6px'}, '(while it worked)') : '')); C.last = null; return; }
  if (e.kind === 'choose') {          // the full agent asks the person to pick: one tap answers, or they write their own
    const pick = (choice) => { if (!String(choice || '').trim()) return; post('/api/code/sessions/' + C.sid + '/answer', {id: e.id, choice}).then(() => poll()); };
    const other = el('input', {type: 'text', placeholder: 'Or write your own answer', 'aria-label': 'Your own answer',
      style: 'flex:1;min-width:160px;background:var(--surface2);color:var(--text);border:1px solid var(--line);border-radius:12px;padding:10px 12px;font:inherit'});
    other.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); pick(other.value); } });
    feed.append(el('div', {class: 'cc-ask', id: 'ask' + e.id}, el('div', {class: 'q'}, e.question),
      el('div', {class: 'row'}, ...(e.options || []).map((o) => el('button', {class: 'chip', onclick: () => pick(o)}, o))),
      el('div', {class: 'row'}, other, el('button', {class: 'btn small', onclick: () => pick(other.value)}, 'Send'))));
    return;
  }
  if (e.kind === 'start') { feed.replaceChildren(el('div', {class: 'cc-user'}, el('span', {class: 'ember'}), el('span', {}, (e.plan ? '[Plan] ' : '') + e.task))); C.last = null; return; }
  if (e.kind === 'step') {
    if (C.retry) { C.retry.classList.replace('run', 'ok'); const v = C.retry.querySelector('.cc-verb'); if (v) v.textContent = 'Fixed a step'; C.retry = null; }   // vryxcode_fixes: the step it retried went through
    const prose = String(e.raw || '').split(/<\|tool_call\|>|<tool_call>/)[0].trim();
    if (e.tool === 'todo') { try { C.todo = JSON.parse(String(e.preview).replace(/^todo /, '')).items || C.todo; } catch (x) { /* a very long list was shortened: keep the last good one */ } renderTodo(); C.last = null; return; }
    if (e.tool === 'finish') { if (prose) feed.append(el('div', {class: 'cc-say'}, prose)); C.last = null; return; }
    if (!e.tool) { feed.append(el('div', {class: 'cc-say'}, e.preview)); C.last = null; return; }
    if (e.tool === 'run') outAgentStep(e); else OUT.pending = null;
    if (prose) feed.append(el('div', {class: 'cc-say'}, prose));
    const [name, arg, extra] = toolParts(e.preview, e.tool);
    const node = el('div', {class: 'cc-tool run'}, el('div', {class: 'cc-head'}, el('span', {class: 'cc-verb'}, name),
      el('span', {class: 'cc-arg'}, [arg, extra, e.secs != null ? Math.round(e.secs) + 's' : '', e.words ? fmt(e.words) + ' tokens' : ''].filter(Boolean).join('  \u00b7  '))));
    const d = (e.tool === 'write_file' || e.tool === 'edit_file') ? diffNode(e.preview) : null; if (d) node.append(d);
    feed.append(node); C.last = node; return;
  }
  if (e.kind === 'result') {
    outAgentResult(e);
    if (C.last) {
      const t = String(e.text || ''), bad = /^error|exit code [1-9]|Traceback|FAILED/m.test(t), lines = t.split('\n').filter((x) => x.trim());
      C.last.classList.remove('run'); C.last.classList.add(bad ? 'no' : 'ok');
      if (bad) { const v = C.last.querySelector('.cc-verb'); if (v) v.textContent = ({Wrote: 'Could not write', Edited: 'Could not edit', Read: 'Could not read', Ran: 'Ran, with a problem'})[v.textContent] || v.textContent; }       // a failed edit must not read like a finished one
      const head = (lines[0] || 'Done').slice(0, 200) + (lines.length > 1 ? '  (+' + (lines.length - 1) + ' lines)' : '');
      const res = el('div', {class: 'cc-res', title: 'Tap to show the whole output'}, el('span', {class: 'arrow'}, '\u2192'), el('span', {class: 'txt'}, head));
      const node = C.last; res.onclick = () => node.classList.toggle('open');
      node.append(res); if (lines.length > 1) node.append(el('div', {class: 'cc-more'}, t)); 
      const shot = /Screenshot: (check-\d+\.png)/.exec(t); if (shot) feed.append(shotCard(shot[1]));
      C.last = null;
    }
    return;
  }
  if (e.kind === 'retry') {                     // the model's tool call could not be read: keep what it said and that it is trying again
    if (S.state && S.state.features && S.state.features.vryxcode_fixes) {      // one line that counts the tries, instead of a red line for each
      const why = e.limit ? 'The reply ran out of room, so VryxCode kept what it wrote and asked for the rest' : 'A step could not be read, so VryxCode asked for it again';
      if (C.retry && C.retry.isConnected) { C.retry._n += 1; C.retry.querySelector('.cc-arg').textContent = why + '  \u00b7  ' + C.retry._n + ' tries'; }
      else { if (e.text) feed.append(el('div', {class: 'cc-say'}, e.text)); C.retry = el('div', {class: 'cc-tool run'}, el('div', {class: 'cc-head'}, el('span', {class: 'cc-verb'}, 'Fixing a step'), el('span', {class: 'cc-arg'}, why))); C.retry._n = 1; feed.append(C.retry); }
      C.last = null; return;
    }
    if (e.text) feed.append(el('div', {class: 'cc-say'}, e.text));
    feed.append(el('div', {class: 'cc-tool no'}, el('div', {class: 'cc-head'}, el('span', {class: 'cc-verb'}, 'Retrying'), el('span', {class: 'cc-arg'}, [e.limit ? 'The reply ran out of room while the model was writing, so VryxCode kept what it wrote and asked for the rest' : 'That step was garbled, so VryxCode asked the model to send it again', e.secs != null ? Math.round(e.secs) + 's' : ''].filter(Boolean).join('  \u00b7  ')))));
    C.last = null; return;
  }
  if (e.kind === 'compacted') { codeCtx(null, true); feed.append(el('div', {class: 'cc-say', style: 'color:var(--muted);font-size:13px'}, (e.manual ? 'As you asked, VryxCode folded' : 'The conversation was getting long, so VryxCode folded') + ' its older steps into a short "Earlier steps" list to save room. The files and this log are unchanged.' + (e.steps ? ' (' + e.steps + ' steps folded)' : ''))); C.last = null; return; }
  if (e.kind === 'queued') { feed.append(el('div', {class: 'cc-say', style: 'color:var(--muted);font-size:14px'}, 'Waiting in the queue' + (e.position ? ' (#' + e.position + ')' : '') + '. It starts by itself when your current session finishes.')); return; }
  if (e.kind === 'language') { feed.append(el('div', {class: 'cc-say', style: 'color:var(--muted);font-size:14px'}, e.text)); return; }
  if (e.kind === 'rewind') { feed.append(el('div', {class: 'cc-end stop'}, el('span', {class: 'mark'}, '\u21b6'), el('span', {}, 'Rewound the files to before: ' + (e.label || 'message ' + e.turn)))); C.last = null; return; }
  if (e.kind === 'answer') { const q = document.getElementById('ask' + e.id); if (q) q.remove(); return; }
  if (e.kind === 'ask') {
    const reply = (allow, always) => post('/api/code/sessions/' + C.sid + '/answer', {id: e.id, allow, always}).then(() => poll());
    const node = el('div', {class: 'cc-ask', id: 'ask' + e.id}, el('div', {class: 'q'}, 'Allow this?'), el('pre', {}, e.preview),
      el('div', {class: 'row'}, el('button', {class: 'btn small', onclick: () => reply(true, false)}, 'Yes'), el('button', {class: 'chip', onclick: () => reply(true, true)}, 'Yes, and don\'t ask again for this'),
        el('button', {class: 'chip', onclick: () => reply(false, false)}, 'No')));
    feed.append(node); return;
  }
  if (e.kind === 'end') {
    if (C.retry) { C.retry.classList.replace('run', e.finished ? 'ok' : 'no'); C.retry = null; }
    if (e.finished || e.said) {                       // the model talking to the person: what it did, what to run, what it suggests
      if (e.finished) setTimeout(() => { if (!$('codePv').hidden) reloadPreview(); else if (!$('codePreviewBtn').disabled) $('codePreviewBtn').classList.add('pulse'); }, 700);     // the page changed: refresh it, or point at Preview
      feed.append(renderMessage(e.summary || 'Done.', e.finished));
      if (e.report) feed.append(reportCard(e.report));
      if (e.plan) feed.append(el('div', {class: 'plan-actions'}, el('button', {class: 'btn small', onclick: () => { setMode(C.prevMode === 'plan' ? 'ask' : C.prevMode); $('codeTask').value = 'Go ahead and build it as planned.'; $('codeGo').click(); }}, 'Build it'), el('button', {class: 'chip', onclick: () => { $('codeTask').value = 'Change the plan: '; $('codeTask').focus(); }}, 'Change the plan')));
      if (e.finished || e.plan) offerReply(e.plan ? 'Go ahead and build it as planned.' : (e.next || [])[0]);
      if (e.next && e.next.length) feed.append(el('div', {class: 'cc-next'}, el('span', {class: 'lead'}, 'Suggested next:'),
        ...e.next.map((t) => el('button', {class: 'chip', onclick: () => { $('codeTask').value = t; $('codeGo').click(); }}, t))));
      return;
    }
    const cls = e.error || e.limited ? 'bad' : 'stop';
    if (e.report) feed.append(reportCard(e.report));
    feed.append(el('div', {class: 'cc-end ' + cls}, el('span', {class: 'mark'}, e.error || e.limited ? '\u2717' : '\u25a0'),
      el('span', {}, /^(Stopped|Paused)/i.test(e.summary || '') ? e.summary : (e.error ? 'Could not finish: ' : e.limited ? 'Paused: ' : 'Stopped: ') + (e.summary || (e.turns + ' steps used')))));
  }
}
// a screenshot from the browser check: a small picture, tap to open it full size
function shotCard(name) {
  const url = '/api/code/shot?project=' + encodeURIComponent(C.project) + '&name=' + encodeURIComponent(name);
  return el('a', {class: 'cc-shot', href: url, target: '_blank', rel: 'noopener', title: 'Open the screenshot'}, el('img', {src: url, alt: 'Screenshot of the page the browser check opened', loading: 'lazy'}));
}
// the verification report at the end of a turn that did work: how it was checked and what to look at
function reportCard(e) {
  const mark = {verified: '\u2713', checked: '\u25d0', not_verified: '!', no_changes: '\u2013'}[e.verdict] || '';
  const card = el('div', {class: 'cc-report ' + e.verdict}, el('div', {class: 'rh'}, el('span', {class: 'mark'}, mark), el('span', {}, e.label)));
  const section = (title, items) => { if (items.length) { card.append(el('div', {class: 'rs'}, title)); items.forEach((n) => card.append(n)); } };
  section('Files', (e.files || []).map((f) => el('div', {class: 'ri'}, f.path + ' \u00b7 ' + (f.created ? 'new' : 'edited') + (f.added ? ' +' + f.added : '') + (f.removed ? ' \u2212' + f.removed : '') + (f.checked ? ' \u00b7 syntax checked' : ''))));
  section('Tests', (e.tests || []).map((t) => el('div', {class: 'ri' + (t.passed ? '' : ' bad')}, (t.passed ? '\u2713 ' : '\u2717 ') + t.line + ' \u00b7 ', el('code', {}, t.command))));
  section('Look at', (e.look_at || []).map((t) => el('div', {class: 'ri'}, '\u2022 ' + t)));
  return card;
}
// a message from the model: paragraphs, `inline code`, and fenced blocks (commands to run) with a Copy button
function renderMessage(text, good) {
  const box = el('div', {class: 'cc-msg' + (good ? ' good' : '')});
  const parts = String(text).split(/```/);
  parts.forEach((part, i) => {
    if (i % 2 === 0) {
      part.split(/\n{2,}/).map((x) => x.trim()).filter(Boolean).forEach((para) => {
        const p = el('p', {}); para.split(/(`[^`\n]+`)/).forEach((bit) => p.append(bit.length > 2 && bit[0] === '`' && bit.endsWith('`') ? el('code', {class: 'in'}, bit.slice(1, -1)) : document.createTextNode(bit)));
        box.append(p);
      });
    } else {
      const nl = part.indexOf('\n'), first = nl >= 0 ? part.slice(0, nl).trim() : '', lang = /^[A-Za-z0-9_+-]{1,14}$/.test(first) ? first : '';
      const code = (lang || nl < 0 ? part.slice(nl + 1) : part).replace(/^\n|\n$/g, '');
      const btn = el('button', {class: 'copy', onclick: async () => { try { await navigator.clipboard.writeText(code); btn.textContent = 'Copied'; } catch (x) { btn.textContent = 'Select and copy'; } setTimeout(() => { btn.textContent = 'Copy'; }, 1500); }}, 'Copy');
      box.append(el('div', {class: 'cc-block'}, el('div', {class: 'bh'}, el('span', {}, lang || 'run this'), btn), el('pre', {}, code)));
    }
  });
  return box;
}
// the live "working" line: our ember mark pulsing, a word for what it is doing (it changes every few seconds), the file or command, seconds, and the text as it is written
function renderLive(live, state) {
  let n = document.getElementById('codeLive') || C.liveEl;       // the same line is moved, not rebuilt, so its words do not blank and fade in again each time the page asks the server
  if (!live || state === 'asking' || !['starting', 'working'].includes(state)) { if (n) n.remove(); C.liveEl = null; C.liveAt = null; return; }
  if (!n) { n = el('div', {class: 'cc-live', id: 'codeLive'}, el('div', {class: 'l1'}, el('span', {class: 'mark'}, logo(20, false, 'brand')), el('span', {class: 'what'}), el('span', {class: 'meta'})), el('div', {class: 'prose'})); }
  C.liveEl = n;
  $('codeIn').append(n);     // always the last thing in the feed
  const now = performance.now(), mine = C.liveAt == null ? null : (now - C.liveAt) / 1000;
  // the server counts whole seconds, so its number is often a second behind ours: keep ours unless the server is ahead or a new step has started (a clearly smaller number)
  if (mine == null || live.secs > mine || mine - live.secs > 2.5) C.liveAt = now - live.secs * 1000;
  C.live = live;
  paintLive();
}
function paintLive() {
  const n = document.getElementById('codeLive'); if (!n || !C.live || C.liveAt == null) return;
  const l = C.live, secs = Math.max(0, Math.floor((performance.now() - C.liveAt) / 1000));
  const kind = nowKind(l), words = NOW_WORDS[kind] || NOW_WORDS.thinking;
  const word = C.stopping ? 'Stopping' : words[Math.floor(secs / 3) % words.length];
  const what = n.querySelector('.what');
  if (!what.textContent) what.textContent = word + '\u2026';                                    // the first time: just show it
  else if (what.textContent !== word + '\u2026' && !what._swapping) { what._swapping = true; what.classList.add('swap'); setTimeout(() => { what.textContent = word + '\u2026'; what.classList.remove('swap'); what._swapping = false; }, 160); }
  const target = (l.target || '').split('\n')[0].slice(0, 60);
  n.querySelector('.meta').textContent = (target ? target + '  \u00b7  ' : '') + secs + 's' + (l.tokens ? '  \u00b7  ' + fmt(l.tokens) + ' tokens' : '');
  n.querySelector('.prose').textContent = l.text || '';
  const f = $('codeFeed'); if (f.scrollTop + f.clientHeight > f.scrollHeight - 160) scrollCode();
}
setInterval(() => { if (C && C.liveAt != null) paintLive(); }, 160);
async function poll() {
  clearTimeout(C.timer); if (!C.sid || !cOn()) return;
  const r = await api('/api/code/sessions/' + C.sid + '?after=' + C.seen);
  if (!r.ok) { C.sid = null; return; }
  const j = await r.json(), feed = $('codeFeed'), atEnd = feed.scrollTop + feed.clientHeight > feed.scrollHeight - 120;
  const old = document.getElementById('codeLive'); if (old) old.remove();      // the live line sits below the newest step, so take it out while steps are added
  for (const e of j.events) cEvent(e); C.seen += j.events.length;
  C.saved = !!j.saved; C.state = j.state; C.checkpoints = j.checkpoints || C.checkpoints || [];
  $('codeTask').placeholder = C.offer || 'Ask, answer, or tell VryxCode what to build or fix';
  if (j.events.some((e) => e.kind === 'result' || e.kind === 'end' || e.kind === 'rewind')) refreshFiles().then(() => livePreview(j.events));
  if (j.events.length && !$('codeDrawer').hidden && C.tab !== 'files') showDrawer(true, C.tab);
  renderLive(j.live, j.state);
  if (j.events.length && atEnd) scrollCode();
  showUsage(j.usage);
  const live = ['starting', 'working', 'asking', 'queued'].includes(j.state);
  C.full = !!j.full; C.live = live;
  $('codeGo').hidden = live && !(C.full && j.state !== 'queued'); $('codeStop').hidden = !live;      // the full agent can be told something while it works if (!live) { C.stopping = false; $('codeStop').disabled = false; }
  if (live) C.timer = setTimeout(poll, j.state === 'asking' ? 1500 : 350);
}
$('codeGo').onclick = async () => {
  const task = $('codeTask').value.trim(); if ((!task && !C.startTemplate) || !C.model) return;
  offerReply('');
  if (C.sid && C.live && C.full) {     // it is working: the message is read before its next step, without stopping it
    const r = await post('/api/code/sessions/' + C.sid + '/steer', {text: task}); const j = await r.json().catch(() => ({}));
    if (r.ok) { $('codeTask').value = ''; poll(); return; }
    note('bad', 'Could not send', (j.message || '') + ' ' + (j.action || '')); return;
  }
  if (C.sid) {         // a session is open: this is its next message, whatever the model (a different model takes over the same conversation; an old session comes back to life)
    const r = await post('/api/code/sessions/' + C.sid + '/message', {text: task, plan: C.mode === 'plan', notify: vxNotifyOn(), model: C.model, effort: C.effort, auto_edits: C.mode === 'auto', images: C.pics.length ? C.pics : undefined}); const j = await r.json().catch(() => ({}));
    if (r.ok) { C.pics = []; renderPics(); C.stopping = false; $('codeStop').disabled = false; $('codeTask').value = ''; C.chatKey = C.project + '|' + C.model; if (j.revived) { C.saved = false; C.seen = 0; $('codeIn').replaceChildren(); } poll(); return; }
    if (r.status === 400 && /still working/i.test(j.message || '')) { note('bad', 'Still working', 'Press Stop first, or wait for it to finish.'); return; }
    note('bad', 'Could not send', (j.message || '') + ' ' + (j.action || '')); return;
  }
  const r = await post('/api/code/start', {project: C.project, task, model: C.model, effort: C.effort, images: C.pics.length ? C.pics : undefined, auto_edits: C.mode === 'auto', plan: C.mode === 'plan', env: C.env, queue: true, notify: vxNotifyOn(), template: C.startTemplate || undefined}); const j = await r.json(); C.startTemplate = null;
  if (!r.ok) { note('bad', 'Could not start', j.message + ' ' + (j.action || '')); return; }
  C.pics = []; renderPics(); C.sid = j.id; C.saved = false; C.checkpoints = []; C.pvAuto = false; C.chatKey = C.project + '|' + C.model; C.seen = 0; C.stopping = false; $('codeStop').disabled = false; $('codeTask').value = ''; $('codeIn').replaceChildren(); poll();
};
// the preview follows the work: on a wide screen it opens beside the chat by itself and refreshes after each change; on a phone the Preview button lights up
function livePreview(events) {
  if ($('codePreviewBtn').disabled) return;
  const wrote = events.some((e) => e.kind === 'result') || events.some((e) => e.kind === 'end' && e.finished);
  if (!wrote) return;
  if (matchMedia('(min-width: 1000px)').matches) {
    if ($('codePv').hidden && !C.pvAuto) { C.pvAuto = true; openPreview(); } else if (!$('codePv').hidden) { clearTimeout(C.pvTimer); C.pvTimer = setTimeout(reloadPreview, 800); }
  } else if ($('codePv').hidden) $('codePreviewBtn').classList.add('pulse');
}
