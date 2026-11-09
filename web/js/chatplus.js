/* Chat parts that work like Claude's and Cursor's, each behind its own feature flag (app/chat_plus.py is the server side):
   the side panel (chat_panel), edit and keep both (chat_versions), quiet lines and sources (chat_lines), suggested follow-ups (chat_followups),
   projects (chat_projects), / and @ (chat_commands), steering while it answers (chat_steer), search everything (search_all), the task box for long
   answers (chat_taskbox) and voice (chat_voice). */

// ---------------------------------------------------------------- what each message gets (called by chat.js bubble)
// plusMsg: called for every message when it is drawn; it adds the extra parts that belong to the switched-on features (version arrows, quiet lines, source chips, links, notes, panel, voice, follow-ups).
function plusMsg(m, node, last) {
  // A message you wrote: show the "1/2" version arrows if the question was edited and kept both versions.
  if (m.role === 'user') {
    const v = S.plus && S.plus.versions && S.plus.versions[m.id];
    if (featureOn('chat_versions') && v && v[1] > 1) node.append(versionNav(m, v));
    return node;
  }
  // The reply's text bubble and its row of buttons, so new parts can be placed before or after them.
  const bubbleEl = node.querySelector('.bubble'), acts = node.querySelector('.acts');
  // chat_lines: a quiet line saying what it did (thought, looked up) above the reply, and the source chips under it.
  if (featureOn('chat_lines')) {
    const lines = quietLines(m); if (lines) node.insertBefore(lines, bubbleEl);
    const chips = sourceChips(m); if (chips) node.insertBefore(chips, acts);
  }
  // chat_cite: turn [1] in the text into links to the sources.
  if (featureOn('chat_cite') && (m.cites || []).length) linkCites(bubbleEl, m.cites);
  // chat_verify: a warning when some figures in the reply are not in any source.
  if (featureOn('chat_verify') && (m.unsupported || []).length && acts) node.insertBefore(verifyNote(m.unsupported), acts);
  // chat_calc: a note when the exact calculator corrected a figure.
  if (featureOn('chat_calc') && (m.calc_fixed || []).length && acts) node.insertBefore(el('div', {class: 'cp-note ok'}, '\u2713 Sum corrected with a calculator: ' + m.calc_fixed.map((f) => f.was + ' \u2192 ' + f.now.split(/=|\bis\b|equals|comes to/i).pop().trim()).join('; ')), acts);
  // chat_panel: if the reply holds a web page, code, a table or a long document, add an "Open in panel" button.
  if (featureOn('chat_panel') && m.content && acts) { const a = artifactOf(m.content); if (a) acts.prepend(el('button', {class: 'chip on', title: 'Show it next to the chat', onclick: () => openPanel(a, m.id)}, '◨ Open in panel')); }
  // chat_voice: a "Read aloud" button when the browser can speak.
  if (featureOn('chat_voice') && acts && m.content && 'speechSynthesis' in window) acts.append(el('button', {class: 'chip', title: 'Read this answer aloud', onclick: (e) => readAloud(m.content, e.currentTarget)}, '🔊 Read aloud'));
  // chat_followups: suggested next questions under the newest finished reply.
  if (last && featureOn('chat_followups') && m.status === 'done' && !S.busy) node.append(el('div', {class: 'cp-follow', id: 'cpFollow'}));
  return node;
}
// plusAfterThread: after the thread is drawn: fetch the follow-up questions for the last reply and, if the panel was following, open the newest result in it.
function plusAfterThread() {   // after the thread is drawn: the follow-ups under the last answer, and the panel follows a change it asked for
  const box = $('cpFollow');
  // Ask the server for follow-ups for this chat.
  if (box && S.chatId != null) { const id = S.chatId; api('/api/chats/' + id + '/followups').then((r) => r.json()).then((j) => {
    // Ignore the answer if the person has moved to another chat meanwhile.
    if (id !== S.chatId || !box.isConnected) return;
    // Each follow-up becomes a button that sends it.
    box.replaceChildren(...(j.items || []).map((t) => el('button', {class: 'chip', onclick: () => { input.value = t; send(); }}, t)));
  }).catch(() => {}); }
  // If the panel asked for a change, show the changed result when the reply is done.
  if (PANEL.follow && !S.busy) {
    const ans = [...S.messages].reverse().find((x) => x.role === 'assistant' && x.status === 'done'), a = ans && artifactOf(ans.content);
    if (a) openPanel(a, ans.id);
    PANEL.follow = false;
  }
}

// chat_cite and chat_verify: [1] links to its source
// ---------------------------------------------------------------- chat_cite and chat_verify: [1] links to its source; figures not in the sources are marked
// linkCites: replace [1], [2]... in the reply with links to their sources, but not inside code.
function linkCites(root, cites) {
  // Index the sources by their number.
  const by = {}; cites.forEach((c) => { by[c.n] = c; });
  // Walk through every piece of text in the reply, skipping code blocks.
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {acceptNode: (t) => (t.parentElement.closest('pre, code, a') ? NodeFilter.FILTER_REJECT : /\[\d{1,2}\]/.test(t.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP)});
  // Collect the text pieces first (changing the page while walking would confuse the walk).
  const found = []; while (walk.nextNode()) found.push(walk.currentNode);
  for (const t of found) {
    const frag = document.createDocumentFragment();
    // Split the text at each [n]; the odd parts are the markers.
    t.nodeValue.split(/(\[\d{1,2}\])/).forEach((part) => {
      // See whether this part is a marker with a known source.
      const c = /^\[(\d{1,2})\]$/.exec(part), cite = c && by[+c[1]];
      // Not a marker: keep the text as it is.
      if (!cite) { if (part) frag.append(part); return; }
      frag.append(cite.url ? el('a', {class: 'cp-cite', href: cite.url, target: '_blank', rel: 'noopener noreferrer', title: cite.title}, c[1]) : el('sup', {class: 'cp-cite', title: cite.title}, c[1]));
    });
    // Put the pieces back in place of the old text.
    t.replaceWith(frag);
  }
}
// verifyNote: a fold-out warning listing the sentences whose figures no source backs up.
function verifyNote(list) {
  const figs = [...new Set(list.flatMap((x) => x.figures))];
  return el('details', {class: 'cp-note warn'}, el('summary', {}, '\u26a0 ' + figs.length + (figs.length === 1 ? ' figure was' : ' figures were') + ' not found in the sources: ' + figs.slice(0, 4).join(', ') + ' \u203a'),
    ...list.map((x) => el('div', {class: 'cp-unsup'}, x.sentence)));
}

// chat_versions: ‹ 1/2 › under an edited question
// ---------------------------------------------------------------- chat_versions: ‹ 1/2 › under an edited question
// versionNav: the arrows under an edited question to switch between its versions.
function versionNav(m, v) {
  // go switches to another version: the server swaps the messages and the page reloads the chat.
  const go = async (i) => {
    if (S.busy) return toast('Wait for the answer to finish.');
    const r = await post('/api/chats/' + S.chatId + '/messages/' + m.id + '/version', {index: i}); const j = await r.json().catch(() => ({}));
    if (!r.ok) return toast(j.message || 'That did not work.');
    const c = await (await api('/api/chats/' + S.chatId)).json(); S.messages = c.messages; S.plus = {versions: c.versions || {}, project: c.project || null}; renderThread(false);
  };
  // The arrows and the "1/2" counter; an arrow is disabled at the first or last version.
  return el('div', {class: 'cp-ver', role: 'group', 'aria-label': 'Versions of this message'},
    el('button', {class: 'icon', 'aria-label': 'Earlier version', disabled: v[0] <= 1, onclick: () => go(v[0] - 2)}, '‹'),
    el('span', {}, v[0] + '/' + v[1]),
    el('button', {class: 'icon', 'aria-label': 'Later version', disabled: v[0] >= v[1], onclick: () => go(v[0])}, '›'));
}

// chat_lines: quiet lines and source chips
// ---------------------------------------------------------------- chat_lines: quiet lines and source chips
// quietLines: a short grey line above a reply such as "Thought 6s, Read 2 from Wikipedia" that opens to show the sources.
function quietLines(m) {
  // lk is what the reply looked up; parts collects the phrases.
  const lk = m.looked, parts = [];
  // How long it thought (at least one second).
  if (m.thought_s) parts.push('Thought ' + Math.max(1, Math.round(m.thought_s)) + 's');
  // What it looked up: live data, saved notes, Wikipedia, the web.
  if (lk) {
    if (lk.live) parts.push('Used live data' + ((lk.names || []).length ? ': ' + lk.names.join(', ') : ''));
    if (lk.saved) parts.push('Read ' + lk.saved + (lk.saved === 1 ? ' saved note' : ' saved notes'));
    if (lk.wiki) parts.push('Read ' + lk.wiki + ' from Wikipedia');
    if (lk.web) parts.push('Searched the web: ' + lk.web + (lk.web === 1 ? ' source' : ' sources'));
    else if (lk.web_tried && !lk.wiki && !lk.saved) parts.push('Searched, found nothing useful');
  }
  // Nothing to say: no line.
  if (!parts.length) return null;
  // The sources to show when the line is opened.
  const list = (lk && lk.sources) || [];
  // The line is a button; it shows a small arrow when there is something to open.
  const head = el('button', {class: 'cp-q', 'aria-expanded': 'false'}, parts.join(', ') + (list.length ? ' ›' : ''));
  const box = el('div', {class: 'cp-ql'}, head);
  // Opening or closing the line shows or hides the list of sources.
  if (list.length) head.onclick = () => { const open = head.getAttribute('aria-expanded') !== 'true'; head.setAttribute('aria-expanded', String(open));
    const old = box.querySelector('.cp-src'); if (old) { old.remove(); return; }
    box.append(el('div', {class: 'cp-src'}, ...list.map((x) => el('div', {}, x.url ? el('a', {href: x.url, target: '_blank', rel: 'noopener noreferrer'}, x.title || x.url) : x.title)))); };
  return box;
}
// sourceChips: small link buttons for the web sources, shown under the reply (at most six, with the site's name).
function sourceChips(m) {
  // Keep only real web addresses.
  const list = ((m.looked || {}).sources || []).filter((x) => /^https?:\/\//.test(x.url || ''));
  if (!list.length) return null;
  // host: the site's name without www.
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return u; } };
  return el('div', {class: 'cp-chips'}, ...list.slice(0, 6).map((x) => el('a', {class: 'chip', href: x.url, target: '_blank', rel: 'noopener noreferrer', title: x.title}, host(x.url))));
}

// chat_panel: the side panel
// ---------------------------------------------------------------- chat_panel: the side panel
// PANEL remembers the open panel and whether it should follow the next reply.
const PANEL = {node: null, follow: false};
// artifactOf: decide whether a reply holds something worth a panel: a web page, a long piece of code, a table or a long document; gives its kind, title and text.
function artifactOf(text) {   // what in an answer is worth a panel: a web page, a long piece of code, a table, a long document
  // Find the code blocks (language and code).
  const blocks = [...String(text).matchAll(/```([\w+#.-]*)[^\n]*\n([\s\S]*?)```/g)].map((b) => ({lang: (b[1] || '').toLowerCase(), code: b[2]}));
  // A block that is a web page or an SVG picture.
  const web = blocks.find((b) => b.lang === 'html' || b.lang === 'svg' || /^\s*(<!doctype html|<html|<svg)/i.test(b.code));
  // A web page with CSS and JavaScript blocks next to it: put them inside the page.
  if (web) {   // a page with its own CSS and JavaScript blocks next to it: put them in
    let html = web.code; const css = blocks.filter((b) => b.lang === 'css').map((b) => b.code).join('\n'), js = blocks.filter((b) => b.lang === 'js' || b.lang === 'javascript').map((b) => b.code).join('\n');
    if (css && !/<style/i.test(html)) html = html.replace(/<\/head>/i, '<style>' + css + '</style></head>') + (/<\/head>/i.test(html) ? '' : '<style>' + css + '</style>');
    if (js && !/<script/i.test(html)) html += '<script>' + js + '<\/script>';
    return {kind: 'web', title: 'Web page', text: html, ext: web.lang === 'svg' ? 'svg' : 'html'};
  }
  // The biggest code block of eight lines or more.
  const big = blocks.filter((b) => b.code.split('\n').length >= 8).sort((a, b) => b.code.length - a.code.length)[0];
  // A big code block becomes a Code panel.
  if (big) return {kind: 'code', title: 'Code' + (big.lang ? ' (' + big.lang + ')' : ''), text: big.code, ext: EXT[big.lang] || 'txt'};
  // A table written in Markdown becomes a Table panel.
  if (/^\s*\|.+\|\s*$/m.test(text) && /^\s*\|?\s*:?-{3,}/m.test(text)) return {kind: 'table', title: 'Table', text, ext: 'md'};
  // A long text with headings becomes a Document panel.
  if (text.length > 1500 && /^#{1,3} /m.test(text)) return {kind: 'doc', title: (text.match(/^#{1,3} +(.+)$/m) || [, 'Document'])[1].slice(0, 60), text, ext: 'md'};
  return null;
}
// EXT: the file extension for each language, for the Download button.
const EXT = {python: 'py', py: 'py', javascript: 'js', js: 'js', typescript: 'ts', ts: 'ts', css: 'css', json: 'json', bash: 'sh', sh: 'sh', sql: 'sql', java: 'java', go: 'go', rust: 'rs', c: 'c', cpp: 'cpp', 'c++': 'cpp', csharp: 'cs', 'c#': 'cs', ruby: 'rb', php: 'php', kotlin: 'kt', swift: 'swift', yaml: 'yml', xml: 'xml', markdown: 'md', md: 'md'};
// openPanel: open the side panel for one result, with a Preview or Code switch for web pages.
async function openPanel(a, msgId) {
  closePanel(); let view = a.kind === 'web' ? 'preview' : 'show';
  const body = el('div', {class: 'cp-body'});
  // draw shows what the panel holds: the web page in a sealed frame, code as plain text, or a formatted document.
  const draw = async () => {
    if (a.kind === 'web' && view === 'preview') {
      // A web page is sent to the server, which returns a safe address to show in the sealed frame.
      const r = await post('/api/panel', {html: a.text}); const j = await r.json().catch(() => ({}));
      if (!r.ok) { body.replaceChildren(el('p', {class: 'err'}, j.message || 'It could not be shown.')); return; }
      body.replaceChildren(el('iframe', {class: 'cp-frame', src: j.url, title: 'Preview of the page', sandbox: 'allow-scripts allow-forms allow-modals allow-popups', referrerpolicy: 'no-referrer'}));
    } else if (a.kind === 'code' || (a.kind === 'web' && view === 'code')) body.replaceChildren(el('pre', {class: 'cp-code'}, a.text));
    else { const d = el('div', {class: 'cp-doc bubble'}); d.append(richText(a.text)); body.replaceChildren(d); }
  };
  // The "Ask for a change" box under the panel.
  const ask = el('input', {type: 'text', placeholder: 'Ask for a change…', 'aria-label': 'Ask for a change to what is in the panel'});
  // change sends a request to change what the panel shows, and the next reply follows into the panel.
  const change = () => { const t = ask.value.trim(); if (!t || S.busy) return;
    PANEL.follow = true; input.value = 'Change the ' + a.title.toLowerCase() + ' you gave me: ' + t + '. Reply with the whole updated version in one code block.'; ask.value = ''; send(); };
  // Enter in that box does the same.
  ask.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); change(); } });
  // The Preview and Code switch (web pages only).
  const tabs = a.kind === 'web' ? el('div', {class: 'seg'}, ...[['preview', 'Preview'], ['code', 'Code']].map(([id, n]) => el('button', {type: 'button', class: view === id ? 'on' : '', onclick: (e) => { view = id; [...e.currentTarget.parentNode.children].forEach((b) => b.classList.toggle('on', b === e.currentTarget)); draw(); }}, n))) : '';
  // Build the panel: title, switch, Copy, Download, Close, the content and the change box.
  PANEL.node = el('aside', {class: 'cp-panel', role: 'complementary', 'aria-label': a.title},
    el('div', {class: 'cp-head'}, el('b', {}, a.title), tabs,
      el('button', {class: 'chip', onclick: (e) => { navigator.clipboard && navigator.clipboard.writeText(a.text); e.currentTarget.textContent = 'Copied'; }}, 'Copy'),
      el('button', {class: 'chip', onclick: () => downloadText(a.text, (S.title || 'emvryx').replace(/[^\w -]+/g, '').trim().slice(0, 40) + '.' + a.ext)}, 'Download'),
      el('button', {class: 'icon', 'aria-label': 'Close the panel', onclick: closePanel}, '×')),
    body, el('div', {class: 'cp-ask'}, ask, el('button', {class: 'btn small', onclick: change}, 'Change')));
  // Show the panel and make room for it.
  document.body.append(PANEL.node); document.body.classList.add('cp-open'); PANEL.msg = msgId; draw();
}
// closePanel: remove the panel and give the room back.
function closePanel() { if (PANEL.node) PANEL.node.remove(); PANEL.node = null; document.body.classList.remove('cp-open'); }
// downloadText: save text as a file with the given name by clicking a temporary link.
function downloadText(text, name) {
  const a = el('a', {href: URL.createObjectURL(new Blob([text], {type: 'text/plain;charset=utf-8'})), download: name}); document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// chat_taskbox: the steps of a long answer, ticked off
// ---------------------------------------------------------------- chat_taskbox: the steps of a long answer, ticked off as they happen
// TASK holds the checklist and its box.
const TASK = {box: null, steps: null};
// plusEvent: called for each progress event of a reply; it builds the list "Read your question, Look it up, Think it through, Write the answer".
function plusEvent(ev, data, think) {
  if (!featureOn('chat_taskbox')) return;
  // tick sets one step's state (todo, now or done) and its label.
  const tick = (id, state, label) => { const st = TASK.steps && TASK.steps.find((x) => x.id === id); if (st) { st.state = state; if (label) st.label = label; } else if (TASK.steps) TASK.steps.push({id, state, label}); drawTask(); };
  // Thinking starts: the first step is done; a deep reply also lists thinking and writing.
  if (ev === 'thinking') {
    TASK.steps = [{id: 'read', state: 'done', label: 'Read your question'}]; TASK.deep = data && data.effort === 'deep'; TASK.box = null; TASK.think = think;
    if (TASK.deep) { tick('think', 'now', 'Think it through'); tick('write', 'todo', 'Write the answer'); }
  // Notes found: count the sources and tick the look-up step.
  } else if (ev === 'notes' && TASK.steps) {
    const n = (data.wiki || 0) + (data.web || 0) + (data.saved || 0) + (data.live || 0) + ((data.apps || []).length);
    tick('look', 'done', data.pictures ? 'Look at the picture' : n ? 'Look it up: ' + n + (n === 1 ? ' source' : ' sources') : 'Look it up');
    if (!TASK.steps.some((x) => x.id === 'write')) tick('write', 'now', 'Write the answer');
  // Words arrive: the thinking is over and the writing step starts.
  } else if (ev === 'piece' && TASK.steps) {
    if (TASK.steps.some((x) => x.id === 'think' && x.state === 'now')) tick('think', 'done');
    if (TASK.steps.some((x) => x.id === 'write' && x.state !== 'now')) tick('write', 'now');
  // The reply is done: everything is ticked.
  } else if (ev === 'done' && TASK.steps) {
    TASK.steps.forEach((x) => { x.state = 'done'; }); drawTask();
  // The reply ended: forget the list.
  } else if (ev === 'end') { TASK.steps = null; TASK.box = null; }
}
// drawTask: draw the checklist, only for replies that look things up or think (a quick answer needs no list).
function drawTask() {   // shown only for answers that look things up or think (a quick answer needs no list)
  if (!TASK.steps || TASK.steps.length < 3) return;
  // Reuse the box if it is on screen, otherwise make it.
  const box = TASK.box && TASK.box.isConnected ? TASK.box : el('div', {class: 'cp-tasks', role: 'list', 'aria-label': 'Steps'});
  box.replaceChildren(...TASK.steps.map((x) => el('div', {class: 'vt is-' + x.state, role: 'listitem'}, el('span', {class: 'dot', 'aria-hidden': 'true'}, x.state === 'done' ? '✓' : ''), el('span', {}, x.label))));
  // Place it above the thinking line if there is one, otherwise at the end.
  if (!box.isConnected) { const at = (TASK.think && TASK.think.isConnected) ? TASK.think : null;
    if (at) $('thread').insertBefore(box, at); else $('thread').append(box); }
  TASK.box = box;
}

// chat_steer: send while it answers
// ---------------------------------------------------------------- chat_steer: send while it answers
// steer: send a new message while a reply is being written: stop the reply, wait until it has really stopped (up to ten seconds), then send the text with a note.
async function steer() {
  const text = input.value.trim(); if (!text) return;
  input.value = ''; stop();
  for (let i = 0; i < 100 && S.busy; i++) await new Promise((r) => setTimeout(r, 100));
  if (S.busy) { input.value = text; return toast('It is still stopping. Try again in a moment.'); }
  input.value = '(While you were answering) ' + text; send();
}

// chat_commands: / and @ in the message box
// ---------------------------------------------------------------- chat_commands: / and @ in the message box
// SLASH_CHAT: the / commands: name, what it does, and the text it puts in the box.
const SLASH_CHAT = [['summarize', 'Summarize this chat so far', 'Summarize this chat so far in a few short points.'], ['shorter', 'Make the last answer shorter', 'Say that again, much shorter.'],
  ['explain', 'Explain the last answer more simply', 'Explain that more simply, as if I am new to it.'], ['checklist', 'Turn the last answer into a checklist', 'Turn that into a short checklist.'],
  ['translate', 'Translate the last answer (type the language)', 'Translate that into '], ['email', 'Write it as an email', 'Write that as a short, friendly email.'],
  ['table', 'Put it in a table', 'Put that in a table.'], ['eli5', 'Explain like I am five', 'Explain that like I am five years old.']];
// CMD holds the open command menu, its items and the highlighted one.
const CMD = {box: null, items: [], at: 0};
// plusMenuOpen: is the command menu showing (chat.js asks so Enter picks an item instead of sending)?
function plusMenuOpen() { return !!(CMD.box && CMD.box.isConnected && CMD.items.length); }
// closeCmd: close the command menu.
function closeCmd() { if (CMD.box) CMD.box.remove(); CMD.box = null; CMD.items = []; }
// cmdMenu: after each keystroke, show the / commands or the @ documents that match what was typed.
async function cmdMenu() {
  if (!featureOn('chat_commands')) return;
  // slash: the text is "/word"; at: the text ends with "@word".
  const v = input.value, slash = /^\/(\w*)$/.exec(v), at = /(^|\s)@(\w*)$/.exec(v);
  if (!slash && !at) return closeCmd();
  let items = [];
  // / commands that begin with what was typed.
  if (slash) items = SLASH_CHAT.filter((c) => c[0].startsWith(slash[1].toLowerCase())).map((c) => ({label: '/' + c[0], sub: c[1], run: () => { input.value = c[2]; input.focus(); }}));
  else {
    // Load the person's documents once for @.
    if (!CMD.docs) { try { CMD.docs = (await (await api('/api/documents')).json()).documents || []; } catch (e) { CMD.docs = []; } }
    const word = at[2].toLowerCase(), cut = () => v.slice(0, v.length - at[2].length - 1).replace(/\s$/, '');
    // @memory uses what Emvryx remembers; @name attaches a document.
    if ('memory'.startsWith(word)) items.push({label: '@memory', sub: 'Use what Emvryx remembers about you', run: () => { input.value = (cut() + ' (Use what you remember about me.)').trim(); }});
    items.push(...CMD.docs.filter((d) => d.name.toLowerCase().includes(word)).slice(0, 8).map((d) => ({label: '@' + d.name, sub: 'Attach this document', run: () => {
      input.value = cut(); if (!S.docs.some((x) => x.id === d.id)) setDocs([...S.docs, {id: d.id, name: d.name, kind: d.kind}]); }})));
  }
  // Close the old menu and, if there is something to show, build the new one.
  closeCmd(); if (!items.length) return;
  CMD.items = items; CMD.at = 0;
  CMD.box = el('div', {class: 'menu cp-cmd', role: 'listbox'}, ...items.map((x, i) => el('button', {class: 'opt' + (i === 0 ? ' sel' : ''), role: 'option', onmousedown: (e) => { e.preventDefault(); x.run(); closeCmd(); }}, el('span', {class: 'grow'}, el('b', {}, x.label), el('small', {}, x.sub)))));
  $('box').append(CMD.box);
}
// Show the menu while typing.
input.addEventListener('input', () => { if (featureOn('chat_commands')) cmdMenu(); });
// Arrow keys move in the menu, Enter or Tab picks, Escape closes (this runs before the normal Enter handler).
input.addEventListener('keydown', (e) => {
  if (!plusMenuOpen()) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); CMD.at = (CMD.at + (e.key === 'ArrowDown' ? 1 : CMD.items.length - 1)) % CMD.items.length; [...CMD.box.children].forEach((b, i) => b.classList.toggle('sel', i === CMD.at)); }
  else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopImmediatePropagation(); const x = CMD.items[CMD.at]; closeCmd(); x.run(); }     // picks it; never also sends
  else if (e.key === 'Escape') closeCmd();
}, true);

// chat_projects: folders with instructions and files
// ---------------------------------------------------------------- chat_projects: folders with instructions and files
// plusProjects: draw the projects in the chat list, each with its chats, a "new chat in" button and a settings button.
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
// loadProjects: fetch the list of projects from the server.
async function loadProjects() {
  if (!featureOn('chat_projects')) return;
  try { S.projectsList = (await (await api('/api/projects')).json()).projects; renderChats(); } catch (e) {}
}
// projectDialog: a window to make or edit a project: its name, how Emvryx should answer in it and which documents it uses.
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

// search_all: one box for chats, documents and settings
// ---------------------------------------------------------------- search_all: one box for chats, documents and settings
// openSearchAll: one search box over chats, documents and settings.
async function openSearchAll() {
  const q = el('input', {type: 'search', placeholder: 'Search chats, documents and settings', 'aria-label': 'Search everything', style: 'width:100%'});
  const out = el('div', {class: 'cp-results'});
  // t is the delay timer; seq numbers the searches so an old answer never replaces a newer one.
  let t = null, seq = 0;
  // run: search now.
  const run = async () => {
    const term = q.value.trim(), mine = ++seq; if (!term) { out.replaceChildren(); return; }
    const low = term.toLowerCase(), rows = [];
    // Ask for chats and documents at the same time.
    const [chats, docs] = await Promise.all([api('/api/chats/search?q=' + encodeURIComponent(term)).then((r) => r.json()).catch(() => ({results: []})),
      CMD.docs ? Promise.resolve({documents: CMD.docs}) : api('/api/documents').then((r) => r.json()).catch(() => ({documents: []}))]);
    // If a newer search has started, drop this answer.
    if (mine !== seq) return;
    CMD.docs = docs.documents || [];
    // Chats first, then documents, then settings.
    for (const c of (chats.results || []).slice(0, 8)) rows.push(['Chat', c.title, c.snippet, () => { m.remove(); openChat(c.id); }]);
    for (const d of CMD.docs.filter((d) => d.name.toLowerCase().includes(low)).slice(0, 6)) rows.push(['Document', d.name, 'Ask about it in a new chat', () => { m.remove(); newChat(false, '', [{id: d.id, name: d.name}]); renderComposer(); input.focus(); }]);
    try { for (const [id, page] of SX_NAV) for (const sec of sxSections(id)) for (const r of sec.rows) if (((r.title || '') + ' ' + (r.desc || '') + ' ' + (r.keys || '')).toLowerCase().includes(low)) rows.push(['Setting', r.title, page, () => { m.remove(); openSettings(id); }]); } catch (e) { /* settings not loaded yet */ }
    out.replaceChildren(...(rows.length ? rows.slice(0, 20).map(([kind, title, sub, go]) => el('button', {class: 'opt', onclick: go}, el('span', {class: 'adm-tag'}, kind), el('span', {class: 'grow'}, el('b', {}, title || 'Untitled'), sub ? el('small', {}, sub) : ''))) : [el('p', {style: 'color:var(--muted)'}, 'Nothing found.')]));
  };
  // Search 0.2 seconds after the last keystroke.
  q.addEventListener('input', () => { clearTimeout(t); t = setTimeout(run, 200); });
  const m = dialog([el('h2', {}, 'Search everything'), q, out], 'Close'); q.focus();
}
// Ctrl+K or Cmd+K opens the search.
document.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && S.state && featureOn('search_all')) { e.preventDefault(); if (!document.querySelector('.modal')) openSearchAll(); } });

// chat_voice: hold to talk, read aloud
// ---------------------------------------------------------------- chat_voice: hold to talk, read aloud
// readAloud: speak a reply out loud; pressing again stops.
function readAloud(text, btn) {
  if (speechSynthesis.speaking) { speechSynthesis.cancel(); btn.textContent = '🔊 Read aloud'; return; }
  // Make the text speakable: code becomes "(code)", markdown signs go, links keep their words.
  const plain = String(text).replace(/```[\s\S]*?```/g, ' (code) ').replace(/[#*_`>|]/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  const u = new SpeechSynthesisUtterance(plain); u.onend = () => { btn.textContent = '🔊 Read aloud'; };
  btn.textContent = '■ Stop'; speechSynthesis.speak(u);
}
// Rec: the browser's speech recognition, if it has one.
const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
// voiceButton: a hold-to-talk microphone button; what is heard is typed into the message box.
function voiceButton() {
  if (!Rec || $('cpMic')) return;
  let rec = null, before = '';
  const b = el('button', {class: 'pill plain', id: 'cpMic', 'aria-label': 'Hold to talk', title: 'Hold to talk (your browser’s own speech typing)', style: 'width:44px;justify-content:center'}, '🎤');
  // start: begin listening when the button is pressed.
  const start = (e) => { e.preventDefault(); if (rec) return; before = input.value ? input.value + ' ' : ''; rec = new Rec(); rec.interimResults = true; rec.continuous = true; rec.lang = navigator.language || 'en-US';
    rec.onresult = (ev) => { let t = ''; for (const r of ev.results) t += r[0].transcript; input.value = before + t; };
    rec.onend = () => { rec = null; b.classList.remove('on'); }; rec.onerror = () => { rec = null; b.classList.remove('on'); };
    b.classList.add('on'); try { rec.start(); } catch (x) { rec = null; b.classList.remove('on'); } };
  // end: stop listening when it is released.
  const end = () => { if (rec) rec.stop(); };
  b.addEventListener('pointerdown', start); b.addEventListener('pointerup', end); b.addEventListener('pointerleave', end); b.addEventListener('pointercancel', end);
  $('plus').after(b);
}
// searchButton: the "Search everything" button in the sidebar.
function searchButton() {
  if ($('cpSearchAll')) return;
  $('chatSearchBox').after(el('button', {class: 'chip', id: 'cpSearchAll', style: 'margin:6px 12px 0', onclick: openSearchAll, title: 'Search chats, documents and settings (Ctrl+K)'}, '🔍 Search everything'));
}
// plusSetup: after sign-in and after the switches change: the buttons that belong to switched-on parts
function plusSetup() {   // after sign-in and after the switches change: the buttons that belong to switched-on parts
  if (!S.state) return;
  if (featureOn('chat_voice')) voiceButton(); else if ($('cpMic')) $('cpMic').remove();
  if (featureOn('search_all')) searchButton(); else if ($('cpSearchAll')) $('cpSearchAll').remove();
  if (!featureOn('chat_panel')) closePanel();
  loadProjects();
}
// Every half second, check whether the page's state changed and, if so, run plusSetup again.
setInterval(() => { if (S.state && S.state !== plusSetup.seen) { plusSetup.seen = S.state; plusSetup(); } }, 500);
