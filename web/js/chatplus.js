/* Chat parts that work like Claude's and Cursor's, each behind its own feature flag (app/chat_plus.py is the server side):
   the side panel (chat_panel), edit and keep both (chat_versions), quiet lines and sources (chat_lines), suggested follow-ups (chat_followups),
   projects (chat_projects), / and @ (chat_commands), steering while it answers (chat_steer), search everything (search_all), the task box for long
   answers (chat_taskbox) and voice (chat_voice). */

// ---------------------------------------------------------------- what each message gets (called by chat.js bubble)
function plusMsg(m, node, last) {
  if (m.role === 'user') {
    const v = S.plus && S.plus.versions && S.plus.versions[m.id];
    if (featureOn('chat_versions') && v && v[1] > 1) node.append(versionNav(m, v));
    return node;
  }
  const bubbleEl = node.querySelector('.bubble'), acts = node.querySelector('.acts');
  if (featureOn('chat_lines')) {
    const lines = quietLines(m); if (lines) node.insertBefore(lines, bubbleEl);
    const chips = sourceChips(m); if (chips) node.insertBefore(chips, acts);
  }
  if (featureOn('chat_panel') && m.content && acts) { const a = artifactOf(m.content); if (a) acts.prepend(el('button', {class: 'chip on', title: 'Show it next to the chat', onclick: () => openPanel(a, m.id)}, '◨ Open in panel')); }
  if (featureOn('chat_voice') && acts && m.content && 'speechSynthesis' in window) acts.append(el('button', {class: 'chip', title: 'Read this answer aloud', onclick: (e) => readAloud(m.content, e.currentTarget)}, '🔊 Read aloud'));
  if (last && featureOn('chat_followups') && m.status === 'done' && !S.busy) node.append(el('div', {class: 'cp-follow', id: 'cpFollow'}));
  return node;
}
function plusAfterThread() {   // after the thread is drawn: the follow-ups under the last answer, and the panel follows a change it asked for
  const box = $('cpFollow');
  if (box && S.chatId != null) { const id = S.chatId; api('/api/chats/' + id + '/followups').then((r) => r.json()).then((j) => {
    if (id !== S.chatId || !box.isConnected) return;
    box.replaceChildren(...(j.items || []).map((t) => el('button', {class: 'chip', onclick: () => { input.value = t; send(); }}, t)));
  }).catch(() => {}); }
  if (PANEL.follow && !S.busy) {
    const ans = [...S.messages].reverse().find((x) => x.role === 'assistant' && x.status === 'done'), a = ans && artifactOf(ans.content);
    if (a) openPanel(a, ans.id);
    PANEL.follow = false;
  }
}

// ---------------------------------------------------------------- chat_versions: ‹ 1/2 › under an edited question
function versionNav(m, v) {
  const go = async (i) => {
    if (S.busy) return toast('Wait for the answer to finish.');
    const r = await post('/api/chats/' + S.chatId + '/messages/' + m.id + '/version', {index: i}); const j = await r.json().catch(() => ({}));
    if (!r.ok) return toast(j.message || 'That did not work.');
    const c = await (await api('/api/chats/' + S.chatId)).json(); S.messages = c.messages; S.plus = {versions: c.versions || {}, project: c.project || null}; renderThread(false);
  };
  return el('div', {class: 'cp-ver', role: 'group', 'aria-label': 'Versions of this message'},
    el('button', {class: 'icon', 'aria-label': 'Earlier version', disabled: v[0] <= 1, onclick: () => go(v[0] - 2)}, '‹'),
    el('span', {}, v[0] + '/' + v[1]),
    el('button', {class: 'icon', 'aria-label': 'Later version', disabled: v[0] >= v[1], onclick: () => go(v[0])}, '›'));
}

// ---------------------------------------------------------------- chat_lines: quiet lines and source chips
function quietLines(m) {
  const lk = m.looked, parts = [];
  if (m.thought_s) parts.push('Thought ' + Math.max(1, Math.round(m.thought_s)) + 's');
  if (lk) {
    if (lk.live) parts.push('Used live data' + ((lk.names || []).length ? ': ' + lk.names.join(', ') : ''));
    if (lk.saved) parts.push('Read ' + lk.saved + (lk.saved === 1 ? ' saved note' : ' saved notes'));
    if (lk.wiki) parts.push('Read ' + lk.wiki + ' from Wikipedia');
    if (lk.web) parts.push('Searched the web: ' + lk.web + (lk.web === 1 ? ' source' : ' sources'));
    else if (lk.web_tried && !lk.wiki && !lk.saved) parts.push('Searched, found nothing useful');
  }
  if (!parts.length) return null;
  const list = (lk && lk.sources) || [];
  const head = el('button', {class: 'cp-q', 'aria-expanded': 'false'}, parts.join(', ') + (list.length ? ' ›' : ''));
  const box = el('div', {class: 'cp-ql'}, head);
  if (list.length) head.onclick = () => { const open = head.getAttribute('aria-expanded') !== 'true'; head.setAttribute('aria-expanded', String(open));
    const old = box.querySelector('.cp-src'); if (old) { old.remove(); return; }
    box.append(el('div', {class: 'cp-src'}, ...list.map((x) => el('div', {}, x.url ? el('a', {href: x.url, target: '_blank', rel: 'noopener noreferrer'}, x.title || x.url) : x.title)))); };
  return box;
}
function sourceChips(m) {
  const list = ((m.looked || {}).sources || []).filter((x) => /^https?:\/\//.test(x.url || ''));
  if (!list.length) return null;
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return u; } };
  return el('div', {class: 'cp-chips'}, ...list.slice(0, 6).map((x) => el('a', {class: 'chip', href: x.url, target: '_blank', rel: 'noopener noreferrer', title: x.title}, host(x.url))));
}

// ---------------------------------------------------------------- chat_panel: the side panel
const PANEL = {node: null, follow: false};
function artifactOf(text) {   // what in an answer is worth a panel: a web page, a long piece of code, a table, a long document
  const blocks = [...String(text).matchAll(/```([\w+#.-]*)[^\n]*\n([\s\S]*?)```/g)].map((b) => ({lang: (b[1] || '').toLowerCase(), code: b[2]}));
  const web = blocks.find((b) => b.lang === 'html' || b.lang === 'svg' || /^\s*(<!doctype html|<html|<svg)/i.test(b.code));
  if (web) {   // a page with its own CSS and JavaScript blocks next to it: put them in
    let html = web.code; const css = blocks.filter((b) => b.lang === 'css').map((b) => b.code).join('\n'), js = blocks.filter((b) => b.lang === 'js' || b.lang === 'javascript').map((b) => b.code).join('\n');
    if (css && !/<style/i.test(html)) html = html.replace(/<\/head>/i, '<style>' + css + '</style></head>') + (/<\/head>/i.test(html) ? '' : '<style>' + css + '</style>');
    if (js && !/<script/i.test(html)) html += '<script>' + js + '<\/script>';
    return {kind: 'web', title: 'Web page', text: html, ext: web.lang === 'svg' ? 'svg' : 'html'};
  }
  const big = blocks.filter((b) => b.code.split('\n').length >= 8).sort((a, b) => b.code.length - a.code.length)[0];
  if (big) return {kind: 'code', title: 'Code' + (big.lang ? ' (' + big.lang + ')' : ''), text: big.code, ext: EXT[big.lang] || 'txt'};
  if (/^\s*\|.+\|\s*$/m.test(text) && /^\s*\|?\s*:?-{3,}/m.test(text)) return {kind: 'table', title: 'Table', text, ext: 'md'};
  if (text.length > 1500 && /^#{1,3} /m.test(text)) return {kind: 'doc', title: (text.match(/^#{1,3} +(.+)$/m) || [, 'Document'])[1].slice(0, 60), text, ext: 'md'};
  return null;
}
const EXT = {python: 'py', py: 'py', javascript: 'js', js: 'js', typescript: 'ts', ts: 'ts', css: 'css', json: 'json', bash: 'sh', sh: 'sh', sql: 'sql', java: 'java', go: 'go', rust: 'rs', c: 'c', cpp: 'cpp', 'c++': 'cpp', csharp: 'cs', 'c#': 'cs', ruby: 'rb', php: 'php', kotlin: 'kt', swift: 'swift', yaml: 'yml', xml: 'xml', markdown: 'md', md: 'md'};
async function openPanel(a, msgId) {
  closePanel(); let view = a.kind === 'web' ? 'preview' : 'show';
  const body = el('div', {class: 'cp-body'});
  const draw = async () => {
    if (a.kind === 'web' && view === 'preview') {
      const r = await post('/api/panel', {html: a.text}); const j = await r.json().catch(() => ({}));
      if (!r.ok) { body.replaceChildren(el('p', {class: 'err'}, j.message || 'It could not be shown.')); return; }
      body.replaceChildren(el('iframe', {class: 'cp-frame', src: j.url, title: 'Preview of the page', sandbox: 'allow-scripts allow-forms allow-modals allow-popups', referrerpolicy: 'no-referrer'}));
    } else if (a.kind === 'code' || (a.kind === 'web' && view === 'code')) body.replaceChildren(el('pre', {class: 'cp-code'}, a.text));
    else { const d = el('div', {class: 'cp-doc bubble'}); d.append(richText(a.text)); body.replaceChildren(d); }
  };
  const ask = el('input', {type: 'text', placeholder: 'Ask for a change…', 'aria-label': 'Ask for a change to what is in the panel'});
  const change = () => { const t = ask.value.trim(); if (!t || S.busy) return;
    PANEL.follow = true; input.value = 'Change the ' + a.title.toLowerCase() + ' you gave me: ' + t + '. Reply with the whole updated version in one code block.'; ask.value = ''; send(); };
  ask.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); change(); } });
  const tabs = a.kind === 'web' ? el('div', {class: 'seg'}, ...[['preview', 'Preview'], ['code', 'Code']].map(([id, n]) => el('button', {type: 'button', class: view === id ? 'on' : '', onclick: (e) => { view = id; [...e.currentTarget.parentNode.children].forEach((b) => b.classList.toggle('on', b === e.currentTarget)); draw(); }}, n))) : '';
  PANEL.node = el('aside', {class: 'cp-panel', role: 'complementary', 'aria-label': a.title},
    el('div', {class: 'cp-head'}, el('b', {}, a.title), tabs,
      el('button', {class: 'chip', onclick: (e) => { navigator.clipboard && navigator.clipboard.writeText(a.text); e.currentTarget.textContent = 'Copied'; }}, 'Copy'),
      el('button', {class: 'chip', onclick: () => downloadText(a.text, (S.title || 'emvryx').replace(/[^\w -]+/g, '').trim().slice(0, 40) + '.' + a.ext)}, 'Download'),
      el('button', {class: 'icon', 'aria-label': 'Close the panel', onclick: closePanel}, '×')),
    body, el('div', {class: 'cp-ask'}, ask, el('button', {class: 'btn small', onclick: change}, 'Change')));
  document.body.append(PANEL.node); document.body.classList.add('cp-open'); PANEL.msg = msgId; draw();
}
function closePanel() { if (PANEL.node) PANEL.node.remove(); PANEL.node = null; document.body.classList.remove('cp-open'); }
function downloadText(text, name) {
  const a = el('a', {href: URL.createObjectURL(new Blob([text], {type: 'text/plain;charset=utf-8'})), download: name}); document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// ---------------------------------------------------------------- chat_taskbox: the steps of a long answer, ticked off as they happen
const TASK = {box: null, steps: null};
function plusEvent(ev, data, think) {
  if (!featureOn('chat_taskbox')) return;
  const tick = (id, state, label) => { const st = TASK.steps && TASK.steps.find((x) => x.id === id); if (st) { st.state = state; if (label) st.label = label; } else if (TASK.steps) TASK.steps.push({id, state, label}); drawTask(); };
  if (ev === 'thinking') {
    TASK.steps = [{id: 'read', state: 'done', label: 'Read your question'}]; TASK.deep = data && data.effort === 'deep'; TASK.box = null; TASK.think = think;
    if (TASK.deep) { tick('think', 'now', 'Think it through'); tick('write', 'todo', 'Write the answer'); }
  } else if (ev === 'notes' && TASK.steps) {
    const n = (data.wiki || 0) + (data.web || 0) + (data.saved || 0) + (data.live || 0) + ((data.apps || []).length);
    tick('look', 'done', data.pictures ? 'Look at the picture' : n ? 'Look it up: ' + n + (n === 1 ? ' source' : ' sources') : 'Look it up');
    if (!TASK.steps.some((x) => x.id === 'write')) tick('write', 'now', 'Write the answer');
  } else if (ev === 'piece' && TASK.steps) {
    if (TASK.steps.some((x) => x.id === 'think' && x.state === 'now')) tick('think', 'done');
    if (TASK.steps.some((x) => x.id === 'write' && x.state !== 'now')) tick('write', 'now');
  } else if (ev === 'done' && TASK.steps) {
    TASK.steps.forEach((x) => { x.state = 'done'; }); drawTask();
  } else if (ev === 'end') { TASK.steps = null; TASK.box = null; }
}
function drawTask() {   // shown only for answers that look things up or think (a quick answer needs no list)
  if (!TASK.steps || TASK.steps.length < 3) return;
  const box = TASK.box && TASK.box.isConnected ? TASK.box : el('div', {class: 'cp-tasks', role: 'list', 'aria-label': 'Steps'});
  box.replaceChildren(...TASK.steps.map((x) => el('div', {class: 'vt is-' + x.state, role: 'listitem'}, el('span', {class: 'dot', 'aria-hidden': 'true'}, x.state === 'done' ? '✓' : ''), el('span', {}, x.label))));
  if (!box.isConnected) { const at = (TASK.think && TASK.think.isConnected) ? TASK.think : null;
    if (at) $('thread').insertBefore(box, at); else $('thread').append(box); }
  TASK.box = box;
}

// ---------------------------------------------------------------- chat_steer: send while it answers
async function steer() {
  const text = input.value.trim(); if (!text) return;
  input.value = ''; stop();
  for (let i = 0; i < 100 && S.busy; i++) await new Promise((r) => setTimeout(r, 100));
  if (S.busy) { input.value = text; return toast('It is still stopping. Try again in a moment.'); }
  input.value = '(While you were answering) ' + text; send();
}

// ---------------------------------------------------------------- chat_commands: / and @ in the message box
const SLASH_CHAT = [['summarize', 'Summarize this chat so far', 'Summarize this chat so far in a few short points.'], ['shorter', 'Make the last answer shorter', 'Say that again, much shorter.'],
  ['explain', 'Explain the last answer more simply', 'Explain that more simply, as if I am new to it.'], ['checklist', 'Turn the last answer into a checklist', 'Turn that into a short checklist.'],
  ['translate', 'Translate the last answer (type the language)', 'Translate that into '], ['email', 'Write it as an email', 'Write that as a short, friendly email.'],
  ['table', 'Put it in a table', 'Put that in a table.'], ['eli5', 'Explain like I am five', 'Explain that like I am five years old.']];
const CMD = {box: null, items: [], at: 0};
function plusMenuOpen() { return !!(CMD.box && CMD.box.isConnected && CMD.items.length); }
function closeCmd() { if (CMD.box) CMD.box.remove(); CMD.box = null; CMD.items = []; }
async function cmdMenu() {
  if (!featureOn('chat_commands')) return;
  const v = input.value, slash = /^\/(\w*)$/.exec(v), at = /(^|\s)@(\w*)$/.exec(v);
  if (!slash && !at) return closeCmd();
  let items = [];
  if (slash) items = SLASH_CHAT.filter((c) => c[0].startsWith(slash[1].toLowerCase())).map((c) => ({label: '/' + c[0], sub: c[1], run: () => { input.value = c[2]; input.focus(); }}));
  else {
    if (!CMD.docs) { try { CMD.docs = (await (await api('/api/documents')).json()).documents || []; } catch (e) { CMD.docs = []; } }
    const word = at[2].toLowerCase(), cut = () => v.slice(0, v.length - at[2].length - 1).replace(/\s$/, '');
    if ('memory'.startsWith(word)) items.push({label: '@memory', sub: 'Use what Emvryx remembers about you', run: () => { input.value = (cut() + ' (Use what you remember about me.)').trim(); }});
    items.push(...CMD.docs.filter((d) => d.name.toLowerCase().includes(word)).slice(0, 8).map((d) => ({label: '@' + d.name, sub: 'Attach this document', run: () => {
      input.value = cut(); if (!S.docs.some((x) => x.id === d.id)) setDocs([...S.docs, {id: d.id, name: d.name, kind: d.kind}]); }})));
  }
  closeCmd(); if (!items.length) return;
  CMD.items = items; CMD.at = 0;
  CMD.box = el('div', {class: 'menu cp-cmd', role: 'listbox'}, ...items.map((x, i) => el('button', {class: 'opt' + (i === 0 ? ' sel' : ''), role: 'option', onmousedown: (e) => { e.preventDefault(); x.run(); closeCmd(); }}, el('span', {class: 'grow'}, el('b', {}, x.label), el('small', {}, x.sub)))));
  $('box').append(CMD.box);
}
input.addEventListener('input', () => { if (featureOn('chat_commands')) cmdMenu(); });
input.addEventListener('keydown', (e) => {
  if (!plusMenuOpen()) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); CMD.at = (CMD.at + (e.key === 'ArrowDown' ? 1 : CMD.items.length - 1)) % CMD.items.length; [...CMD.box.children].forEach((b, i) => b.classList.toggle('sel', i === CMD.at)); }
  else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopImmediatePropagation(); const x = CMD.items[CMD.at]; closeCmd(); x.run(); }     // picks it; never also sends
  else if (e.key === 'Escape') closeCmd();
}, true);

// ---------------------------------------------------------------- chat_projects: folders with instructions and files
function plusProjects(box, all, group) {
  const projects = (S.projectsList || []), names = [...new Set([...projects.map((p) => p.name), ...all.filter((c) => c.folder && !c.pinned).map((c) => c.folder)])];
  box.append(el('div', {class: 'label cp-plabel'}, el('span', {}, 'PROJECTS'), el('button', {class: 'chip', title: 'A new project: a folder of chats with its own instructions and files', onclick: () => projectDialog(null)}, '+ New')));
  for (const n of names) {
    const p = projects.find((x) => x.name === n);
    box.append(el('div', {class: 'cp-proj'}, el('span', {class: 'grow'}, '📁 ' + n),
      el('button', {class: 'icon', title: 'New chat in ' + n, 'aria-label': 'New chat in ' + n, onclick: () => { newChat(false); S.newProject = n; toast('New chat in ' + n + ': it uses the project\u2019s instructions and files.'); }}, '+'),
      el('button', {class: 'icon', title: 'Project settings', 'aria-label': 'Settings of ' + n, onclick: () => projectDialog(p || {name: n, instructions: '', docs: []})}, '⚙')));
    const list = all.filter((c) => c.folder === n && !c.pinned);
    if (list.length) group('', list);
  }
}
async function loadProjects() {
  if (!featureOn('chat_projects')) return;
  try { S.projectsList = (await (await api('/api/projects')).json()).projects; renderChats(); } catch (e) {}
}
async function projectDialog(p) {
  const docs = ((await (await api('/api/documents')).json()).documents) || [];
  const name = el('input', {type: 'text', maxlength: 30, value: p ? p.name : '', placeholder: 'Bakery, Homework, Novel…', 'aria-label': 'Project name', style: 'width:100%'});
  const ins = el('textarea', {rows: 4, maxlength: 2000, placeholder: 'How Emvryx should answer in this project, e.g. "Friendly and short. UK spelling. I run a small bakery."', 'aria-label': 'Instructions', style: 'width:100%;border-radius:12px;padding:10px;background:var(--surface2);color:var(--text);border:1px solid var(--line);font:inherit'});
  ins.value = p ? p.instructions : '';
  const picked = new Set(p ? p.docs : []);
  const list = el('div', {style: 'display:flex;flex-direction:column;gap:6px;max-height:180px;overflow:auto'}, ...(docs.length ? docs.map((d) => el('label', {style: 'display:flex;gap:8px;align-items:center'},
    el('input', {type: 'checkbox', checked: picked.has(d.id), onchange: (e) => { e.target.checked ? picked.add(d.id) : picked.delete(d.id); }}), d.name)) : [el('small', {style: 'color:var(--muted)'}, 'No documents yet: add them under Documents, then pick them here.')]));
  const save = async (body) => { const r = await post('/api/projects', body); const j = await r.json().catch(() => ({})); if (!r.ok) return toast(j.message || 'That did not work.'); S.projectsList = j.projects; m.remove(); await load(); };
  const m = dialog([el('h2', {}, p ? 'Project: ' + p.name : 'New project'), el('b', {}, 'Name'), name, el('b', {}, 'Instructions'), ins, el('b', {}, 'Files every new chat in it starts with (up to 10)'), list], 'Cancel',
    el('div', {style: 'display:flex;flex-direction:column;gap:8px;margin-bottom:8px'},
      el('button', {class: 'btn', onclick: () => save({name: name.value, old: p ? p.name : '', instructions: ins.value, docs: [...picked].slice(0, 10)})}, 'Save'),
      p ? el('button', {class: 'btn ghost', onclick: () => { if (confirm('Remove the project "' + p.name + '"? Its chats stay, just out of the folder.')) save({name: p.name, delete: true}); }}, 'Remove the project') : ''));
}

// ---------------------------------------------------------------- search_all: one box for chats, documents and settings
async function openSearchAll() {
  const q = el('input', {type: 'search', placeholder: 'Search chats, documents and settings', 'aria-label': 'Search everything', style: 'width:100%'});
  const out = el('div', {class: 'cp-results'});
  let t = null, seq = 0;
  const run = async () => {
    const term = q.value.trim(), mine = ++seq; if (!term) { out.replaceChildren(); return; }
    const low = term.toLowerCase(), rows = [];
    const [chats, docs] = await Promise.all([api('/api/chats/search?q=' + encodeURIComponent(term)).then((r) => r.json()).catch(() => ({results: []})),
      CMD.docs ? Promise.resolve({documents: CMD.docs}) : api('/api/documents').then((r) => r.json()).catch(() => ({documents: []}))]);
    if (mine !== seq) return;
    CMD.docs = docs.documents || [];
    for (const c of (chats.results || []).slice(0, 8)) rows.push(['Chat', c.title, c.snippet, () => { m.remove(); openChat(c.id); }]);
    for (const d of CMD.docs.filter((d) => d.name.toLowerCase().includes(low)).slice(0, 6)) rows.push(['Document', d.name, 'Ask about it in a new chat', () => { m.remove(); newChat(false, '', [{id: d.id, name: d.name}]); renderComposer(); input.focus(); }]);
    try { for (const [id, page] of SX_NAV) for (const sec of sxSections(id)) for (const r of sec.rows) if (((r.title || '') + ' ' + (r.desc || '') + ' ' + (r.keys || '')).toLowerCase().includes(low)) rows.push(['Setting', r.title, page, () => { m.remove(); openSettings(id); }]); } catch (e) { /* settings not loaded yet */ }
    out.replaceChildren(...(rows.length ? rows.slice(0, 20).map(([kind, title, sub, go]) => el('button', {class: 'opt', onclick: go}, el('span', {class: 'adm-tag'}, kind), el('span', {class: 'grow'}, el('b', {}, title || 'Untitled'), sub ? el('small', {}, sub) : ''))) : [el('p', {style: 'color:var(--muted)'}, 'Nothing found.')]));
  };
  q.addEventListener('input', () => { clearTimeout(t); t = setTimeout(run, 200); });
  const m = dialog([el('h2', {}, 'Search everything'), q, out], 'Close'); q.focus();
}
document.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && S.state && featureOn('search_all')) { e.preventDefault(); if (!document.querySelector('.modal')) openSearchAll(); } });

// ---------------------------------------------------------------- chat_voice: hold to talk, read aloud
function readAloud(text, btn) {
  if (speechSynthesis.speaking) { speechSynthesis.cancel(); btn.textContent = '🔊 Read aloud'; return; }
  const plain = String(text).replace(/```[\s\S]*?```/g, ' (code) ').replace(/[#*_`>|]/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  const u = new SpeechSynthesisUtterance(plain); u.onend = () => { btn.textContent = '🔊 Read aloud'; };
  btn.textContent = '■ Stop'; speechSynthesis.speak(u);
}
const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
function voiceButton() {
  if (!Rec || $('cpMic')) return;
  let rec = null, before = '';
  const b = el('button', {class: 'pill plain', id: 'cpMic', 'aria-label': 'Hold to talk', title: 'Hold to talk (your browser’s own speech typing)', style: 'width:44px;justify-content:center'}, '🎤');
  const start = (e) => { e.preventDefault(); if (rec) return; before = input.value ? input.value + ' ' : ''; rec = new Rec(); rec.interimResults = true; rec.continuous = true; rec.lang = navigator.language || 'en-US';
    rec.onresult = (ev) => { let t = ''; for (const r of ev.results) t += r[0].transcript; input.value = before + t; };
    rec.onend = () => { rec = null; b.classList.remove('on'); }; rec.onerror = () => { rec = null; b.classList.remove('on'); };
    b.classList.add('on'); try { rec.start(); } catch (x) { rec = null; b.classList.remove('on'); } };
  const end = () => { if (rec) rec.stop(); };
  b.addEventListener('pointerdown', start); b.addEventListener('pointerup', end); b.addEventListener('pointerleave', end); b.addEventListener('pointercancel', end);
  $('plus').after(b);
}
function searchButton() {
  if ($('cpSearchAll')) return;
  $('chatSearchBox').after(el('button', {class: 'chip', id: 'cpSearchAll', style: 'margin:6px 12px 0', onclick: openSearchAll, title: 'Search chats, documents and settings (Ctrl+K)'}, '🔍 Search everything'));
}
function plusSetup() {   // after sign-in and after the switches change: the buttons that belong to switched-on parts
  if (!S.state) return;
  if (featureOn('chat_voice')) voiceButton(); else if ($('cpMic')) $('cpMic').remove();
  if (featureOn('search_all')) searchButton(); else if ($('cpSearchAll')) $('cpSearchAll').remove();
  if (!featureOn('chat_panel')) closePanel();
  loadProjects();
}
setInterval(() => { if (S.state && S.state !== plusSetup.seen) { plusSetup.seen = S.state; plusSetup(); } }, 500);
