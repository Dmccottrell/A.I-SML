/* Documents, saving answers, Teacher mode, Skills, connected apps, saved notes and memory. */
// ---------------------------------------------------------------- documents (files you add so a chat can answer about them)
function sizeText(chars) { return chars < 1000 ? chars + ' letters' : chars < 1e6 ? Math.round(chars / 1000) + 'K letters' : (chars / 1e6).toFixed(1) + 'M letters'; }
const DOC_ACCEPT = '.pdf,.docx,.txt,.md,.csv,.tsv,.json,.html,.htm,.log,.py,.js,.ts,.java,.c,.cpp,.cs,.go,.rs,.sql,.yaml,.yml,.xml,.css,.sh,.tex';
const SKIP_DIRS = /(^|\/)(\.git|node_modules|__pycache__|\.venv|venv|dist|build|\.idea|\.vscode)\//;
async function fileToB64(f) { const buf = new Uint8Array(await f.arrayBuffer()); let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000)); return btoa(bin); }
function pickFile(onDone) {
  const inp = el('input', {type: 'file', accept: DOC_ACCEPT + ',image/*', style: 'display:none'});
  inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return;
    if (f.size > 10e6) return alert('That file is too big. The limit is 10 MB.');
    await onDone(f.name, await fileToB64(f));
  };
  document.body.append(inp); inp.click(); setTimeout(() => inp.remove(), 60000);
}
function pickMany({accept, folder}) {   // files, photos or a whole folder: each one is added to your documents and attached to this chat
  const inp = el('input', {type: 'file', multiple: true, style: 'display:none'});
  if (accept) inp.accept = accept; if (folder) inp.setAttribute('webkitdirectory', '');
  inp.onchange = () => { const list = [...inp.files]; inp.remove(); if (list.length) addFiles(list); };
  document.body.append(inp); inp.click(); setTimeout(() => inp.remove(), 60000);
}
function imageFilesFrom(data) {   // screenshots and photos from a paste or a drop, given a name and the right ending so they can be read
  const out = [];
  for (const f of [...((data && data.files) || [])]) {
    if (!f.type || !f.type.startsWith('image/')) continue;
    const ext = (f.type.split('/')[1] || 'png').replace('jpeg', 'jpg').replace(/[^a-z0-9].*$/, '');
    out.push(f.name && /\.[a-z0-9]+$/i.test(f.name) && f.name !== 'image.png' ? f : new File([f], 'screenshot-' + Date.now() + '-' + out.length + '.' + ext, {type: f.type}));
  }
  return out;
}
document.addEventListener('paste', (e) => {   // Ctrl+V or paste after taking a screenshot, like other chat apps
  if (!S.state || $('app').hidden) return; const files = imageFilesFrom(e.clipboardData); if (!files.length) return;
  e.preventDefault(); addFiles(files);
});
['dragover', 'drop'].forEach((ev) => document.addEventListener(ev, (e) => {
  if (!S.state || $('app').hidden || !e.dataTransfer || ![...(e.dataTransfer.types || [])].includes('Files')) return;
  e.preventDefault(); if (ev === 'drop' && e.dataTransfer.files.length) addFiles([...e.dataTransfer.files]);
}));
async function shrinkImage(f) {   // a phone photo is several MB: send a smaller copy (long side 2000 px), which uploads and reads much faster
  if (!f.type || !f.type.startsWith('image/') || f.type === 'image/gif' || f.size < 400e3 || !window.createImageBitmap) return f;
  try {
    const bmp = await createImageBitmap(f); const k = Math.min(1, 2000 / Math.max(bmp.width, bmp.height));
    if (k === 1 && f.size < 1.5e6) return f;
    const c = document.createElement('canvas'); c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
    const blob = await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.88));
    return blob && blob.size < f.size ? new File([blob], f.name.replace(/\.[a-z0-9]+$/i, '') + '.jpg', {type: 'image/jpeg'}) : f;
  } catch (e) { return f; }
}
async function addFiles(list) {
  const box = $('attached'); const note = el('span', {class: 'chip', role: 'status'}, ''); box.hidden = false; box.append(note);
  const added = []; const skipped = [];
  const files = list.filter((f) => { const p = f.webkitRelativePath || f.name; if (SKIP_DIRS.test(p) || /(^|\/)\.[^/]+$/.test(p)) return false; return true; });
  let n = 0;
  for (const f of files) {
    n++; note.textContent = (f.type && f.type.startsWith('image/') ? 'Reading the picture ' : 'Reading ') + n + ' of ' + files.length + '...';
    const g = await shrinkImage(f);
    if (g.size > 10e6) { skipped.push(f.name + ' (over 10 MB)'); continue; }
    try {
      const r = await post('/api/documents', {name: g.name, data: await fileToB64(g)}); const j = await r.json().catch(() => ({}));
      if (r.ok) added.push({id: j.id, name: j.name}); else skipped.push(f.name + ' (' + (j.message || 'could not be added').replace(/\.$/, '') + ')');
    } catch (e) { skipped.push(f.name); }
    if (added.length >= 40) break;
  }
  note.remove();
  if (added.length) await setDocs([...S.docs, ...added.filter((a) => !S.docs.some((d) => d.id === a.id))]);
  if (skipped.length) alert((added.length ? 'Added ' + added.length + '. ' : 'Nothing was added. ') + 'Skipped ' + skipped.length + ':\n' + skipped.slice(0, 8).join('\n') + (skipped.length > 8 ? '\n...' : ''));
  input.focus();
}
async function uploadDoc(status) {
  return new Promise((resolve) => pickFile(async (name, data) => {
    status.textContent = 'Reading ' + name + '...';
    const r = await post('/api/documents', {name, data}); const j = await r.json().catch(() => ({}));
    status.textContent = r.ok ? 'Added ' + j.name + '. ' + (j.note || '') : (j.message || 'That file could not be added.');
    resolve(r.ok ? j : null);
  }));
}
async function openDocs() {
  closeModals(); document.body.classList.remove('menu-open');
  const j = await (await api('/api/documents')).json();
  const status = el('div', {style: 'color:var(--muted);font-size:14px', role: 'status'}, 'Add a PDF, Word or text file, or a picture of text, then ask questions about it, or have it summarized. It stays on this computer, in your own space.');
  const kids = [el('h2', {}, 'Documents'), status,
    el('button', {class: 'btn', onclick: async () => { if (await uploadDoc(status)) setTimeout(openDocs, 900); }}, 'Add a document')];
  if (!j.documents.length) kids.push(el('div', {style: 'color:var(--muted)'}, 'No documents yet.'));
  for (const d of j.documents) kids.push(el('div', {class: 'opt', style: 'cursor:default'},
    el('span', {class: 'grow'}, el('b', {style: 'overflow-wrap:anywhere'}, d.name), el('small', {}, d.kind.toUpperCase() + ' \u00b7 ' + sizeText(d.chars))),
    el('button', {class: 'chip', onclick: () => { closeModals(); newChat(false, '', [{id: d.id, name: d.name}]); renderComposer(); input.focus(); }}, 'Ask'),
    el('button', {class: 'chip', 'aria-label': 'Delete ' + d.name, onclick: async () => { if (confirm('Delete "' + d.name + '"?')) { await api('/api/documents/' + d.id, {method: 'DELETE'}); S.docs = S.docs.filter((x) => x.id !== d.id); openDocs(); } }}, '\u00d7')));
  dialog(kids, 'Close');
}
async function openAttach() {
  closeModals();
  const j = await (await api('/api/documents')).json();
  const chosen = new Set(S.docs.map((d) => d.id));
  const status = el('div', {style: 'color:var(--muted);font-size:14px', role: 'status'}, 'Pick the documents this chat should read. Its answers will come from them.');
  const rows = el('div', {style: 'display:flex;flex-direction:column;gap:8px'});
  const draw = (docs) => rows.replaceChildren(...docs.map((d) => el('button', {class: 'opt' + (chosen.has(d.id) ? ' sel' : ''), onclick: (e) => {
      chosen.has(d.id) ? chosen.delete(d.id) : chosen.add(d.id); e.currentTarget.classList.toggle('sel'); }},
    el('span', {class: 'grow'}, el('b', {style: 'overflow-wrap:anywhere'}, d.name), el('small', {}, d.kind.toUpperCase() + ' \u00b7 ' + sizeText(d.chars))))));
  let docs = j.documents; draw(docs.length ? docs : []);
  if (!docs.length) rows.append(el('div', {style: 'color:var(--muted)'}, 'No documents yet. Add one below.'));
  const done = el('button', {class: 'btn', onclick: async () => { await setDocs(docs.filter((d) => chosen.has(d.id)).map((d) => ({id: d.id, name: d.name}))); closeModals(); input.focus(); }}, 'Use these');
  dialog([el('h2', {}, 'Attach documents'), status, rows,
    el('button', {class: 'btn ghost', onclick: async () => { const d = await uploadDoc(status); if (d) { docs = [d, ...docs]; chosen.add(d.id); draw(docs); } }}, 'Add a new document'), done], 'Cancel');
}

// ---------------------------------------------------------------- saving documents (PDF, Word, Google Docs)
function closeModals() { document.querySelectorAll('.modal').forEach((m) => m.remove()); }
async function downloadDoc(text, format, title) {
  const r = await post('/api/export-doc', {text, format, title});
  if (!r.ok) { const j = await r.json().catch(() => ({})); alert(j.message || 'Could not save that.'); return false; }
  const blob = await r.blob(), a = el('a', {href: URL.createObjectURL(blob), download: ((r.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/) || [])[1] || 'document.' + format});
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); return true;
}
function saveAs(text, title) {
  const note = el('div', {style: 'color:var(--muted);font-size:14px'}, 'Worksheets keep the answer key and teacher notes on their own pages, so you can print page 1 for the class.');
  const done = (msg) => note.replaceChildren(msg);
  const m = dialog([el('h2', {}, 'Save as'), note, el('div', {class: 'btnrow'},
    el('button', {class: 'btn', onclick: async () => { if (await downloadDoc(text, 'pdf', title)) done('Saved as a PDF.'); }}, 'PDF'),
    el('button', {class: 'btn', onclick: async () => { if (await downloadDoc(text, 'docx', title)) done('Saved as a Word file.'); }}, 'Word'),
    el('button', {class: 'btn', onclick: async () => { if (await downloadDoc(text, 'docx', title)) { done('Saved as a Word file. To make it a Google Doc: on a phone, tap the file and choose Docs; on a computer open docs.google.com, then File > Open > Upload and pick it.'); window.open('https://docs.google.com/document/', '_blank', 'noopener'); } }}, 'Google Docs'),
    el('button', {class: 'btn ghost', onclick: () => { navigator.clipboard && navigator.clipboard.writeText(text); done('Copied.'); }}, 'Copy text'))], 'Close');
}

// ---------------------------------------------------------------- teacher mode
async function loadTeacher() { if (!S.tools) S.tools = (await (await api('/api/teacher/tools')).json()).tools; return S.tools; }
async function openTeacher(side) {
  const tools = await loadTeacher(); side = side || S.teacherSide || 'teacher'; S.teacherSide = side; closeModals(); document.body.classList.remove('menu-open');
  const tab = (id, label) => el('button', {class: 'chip' + (side === id ? ' on' : ''), onclick: () => openTeacher(id)}, label);
  const kids = [el('h2', {}, 'Teacher tools'), el('div', {style: 'color:var(--muted)'}, side === 'teacher' ? 'Make classroom materials, check the numbers and get suggestions. Every number comes from an exact calculator, never a guess.' : 'Learn it, practise it and plan your studying. It guides you to the answer instead of just giving it.'),
    el('div', {class: 'tabs'}, tab('teacher', 'For teachers'), tab('student', 'For students'))];
  for (const [kind, label] of [['make', 'MAKE'], ['calc', 'CALCULATE']]) {
    const list = tools.filter((t) => t.side === side && t.kind === kind); if (!list.length) continue;
    kids.push(el('div', {class: 'label', style: 'padding:4px 0 0'}, label));
    for (const t of list) kids.push(el('button', {class: 'opt', onclick: () => openTool(t)}, el('span', {class: 'grow'}, el('b', {}, t.name), el('small', {}, t.blurb))));
  }
  dialog(kids, 'Close');
}
function openTool(t) {
  closeModals();
  const inputs = {}, fields = t.fields.map((f) => {
    let c;
    if (f.type === 'choice') { c = el('select', {}); for (const o of f.options) c.append(el('option', {value: o, selected: o === f.default ? 'selected' : null}, o)); }
    else if (f.type === 'area') c = el('textarea', {class: 'f', placeholder: f.placeholder || ''}, '');
    else if (f.type === 'number') c = el('input', {type: 'number', value: f.default, min: f.min, max: f.max, inputmode: 'decimal'});
    else c = el('input', {type: 'text', value: f.default || '', placeholder: f.placeholder || ''});
    inputs[f.key] = c; return el('label', {class: 'f'}, f.label, c);
  });
  const err = el('div', {style: 'color:var(--danger);font-size:14px', role: 'alert'});
  const values = () => Object.fromEntries(Object.entries(inputs).map(([k, c]) => [k, c.value]));
  const go = el('button', {class: 'btn', onclick: async () => {
    go.disabled = true; err.textContent = '';
    try { t.kind === 'make' ? await runMake(t, values()) : await runCalc(t, values(), err); } finally { go.disabled = false; }
  }}, t.kind === 'make' ? 'Make it' : 'Calculate');
  dialog([el('h2', {}, t.name), el('div', {style: 'color:var(--muted)'}, t.blurb), ...fields, err, go,
    el('button', {class: 'btn ghost', onclick: () => openTeacher(t.side)}, 'Back')], 'Close');
}
async function runMake(t, values) {
  const r = await post('/api/teacher/prompt', {tool: t.id, values}); const j = await r.json(); if (!r.ok) return alert(j.message || 'Something went wrong.');
  closeModals(); if (!isTeacherChat() || S.skill !== j.skill || S.busy) await newChat(false, j.skill); input.value = j.prompt; send();
}
async function runCalc(t, values, err) {
  const r = await post('/api/teacher/calc', {tool: t.id, values}); const j = await r.json();
  if (!r.ok) { err.textContent = j.message || 'Check the numbers and try again.'; return; }
  closeModals();
  const shown = j.text.split('\n').filter((l) => !l.startsWith('# ')).map((l) => l.replace(/^## /, '').replace(/^- /, '\u2022 ')).join('\n');
  const kids = [el('h2', {}, j.title), el('div', {class: 'report'}, shown)], row = el('div', {class: 'btnrow'});
  if (j.advice_prompt) row.append(el('button', {class: 'btn', onclick: async () => { closeModals(); const sk = t.side === 'teacher' ? 'teacher' : 'study'; if (S.skill !== sk || S.busy) await newChat(false, sk); input.value = j.advice_prompt; send(); }}, 'Get suggestions'));
  row.append(el('button', {class: 'btn ghost', onclick: () => saveAs(j.text, j.title)}, 'Save as\u2026'), el('button', {class: 'btn ghost', onclick: () => openTool(t)}, 'Change numbers'));
  dialog([...kids, row], 'Close');
}

// ---------------------------------------------------------------- skills
async function openSkills() {
  const kids = [el('h2', {}, 'Skills'), el('div', {style: 'color:var(--muted)'}, 'Pick one to start a chat where Emvryx works as that specialist. It works with every model.')];
  for (const k of S.skills) kids.push(el('button', {class: 'opt', onclick: () => { document.querySelectorAll('.modal').forEach((m) => m.remove()); newChat(false, k.id); }},
    el('span', {class: 'grow'}, el('b', {}, k.name), el('small', {}, k.does), el('small', {style: 'font-size:13px'}, 'For: ' + k.for))));
  dialog(kids, 'Close');
}

// ---------------------------------------------------------------- connected apps
async function openApps() {
  const r = await api('/api/apps'); const c = await r.json(); const conn = c.connections || {}; APPS_ENCRYPTED = c.encrypted !== false;
  const kids = [el('h2', {}, 'Connected apps'), el('div', {style: 'color:var(--muted)'}, 'Connect the apps you use and just ask: \u201cwhat is on my calendar tomorrow?\u201d, \u201csearch my Notion for the trip plan\u201d. Everything is read-only, and a private chat never uses them.')];
  const close = () => document.querySelectorAll('.modal').forEach((m) => m.remove());
  for (const cat of c.categories) {
    const list = c.apps.filter((a) => a.category === cat); if (!list.length) continue;
    kids.push(el('div', {class: 'label', style: 'padding:6px 0 0'}, cat.toUpperCase()));
    for (const a of list) {
      const x = conn[a.id] || {}, on = x.connected;
      const open = a.id === 'github' ? () => { close(); openGithubConnect(); } : () => { close(); openAppConnect(a, x); };
      const right = a.status === 'available' ? el('button', {class: 'chip', onclick: open}, on ? 'Manage' : 'Connect') : el('small', {style: 'text-align:right'}, 'Coming soon');
      kids.push(el('div', {class: 'opt', style: 'cursor:default;opacity:.95'},
        el('span', {class: 'grow'}, el('b', {}, a.name + (on ? '  \u00b7  connected' + (x.label ? ' as ' + x.label : '') : '')), el('small', {}, a.does), el('small', {style: 'font-size:13px'}, 'Permission: ' + a.permission)), right));
    }
  }
  kids.push(el('b', {}, 'How connections work'), ...c.rules.map((t) => el('div', {style: 'color:var(--muted);font-size:14px'}, '\u2022 ' + t)));
  dialog(kids, 'Close');
}

// Any app that connects with a pasted token, link or app password
async function openAppConnect(a, x) {
  const close = () => document.querySelectorAll('.modal').forEach((m) => m.remove());
  const kids = [el('h2', {}, a.name), el('div', {style: 'color:var(--muted)'}, a.does)];
  const out = el('div', {role: 'alert', style: 'color:var(--muted);font-size:14px;word-break:break-word'});
  const fail = (j) => { out.style.color = 'var(--danger)'; out.textContent = (j.message || 'Something went wrong.') + ' ' + (j.action || ''); };
  if (x && x.connected) {
    const q = el('input', {type: 'text', placeholder: 'Try it: type what to look for, or leave empty for the latest', 'aria-label': 'Try it'}), res = el('div', {style: 'display:flex;flex-direction:column;gap:8px'});
    const go = async () => { out.textContent = ''; res.replaceChildren(el('div', {style: 'color:var(--muted)'}, 'Looking...')); const rr = await post('/api/apps/' + a.id + '/ask', {query: q.value}); const j = await rr.json();
      if (!rr.ok) { res.replaceChildren(); return fail(j); }
      res.replaceChildren(...(j.items.length ? j.items.map((i) => el('div', {class: 'opt', style: 'cursor:default'}, el('span', {class: 'grow'}, el('b', {}, i.title), el('small', {}, i.text || ''), i.url ? el('a', {href: i.url, target: '_blank', rel: 'noopener', style: 'color:var(--accenttext);font-size:13px'}, 'Open') : null))) : [el('div', {style: 'color:var(--muted)'}, 'Nothing found.')])); };
    q.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    kids.push(el('div', {}, 'Connected as ', el('b', {}, x.label || a.name), '. Ask about it in a chat, or try it here.'), q, el('button', {class: 'btn', type: 'button', onclick: go}, 'Try it'), res, out,
      el('b', {}, 'What was read'), ...((x.log || []).length ? x.log.map((l) => el('div', {style: 'color:var(--muted);font-size:14px'}, new Date(l.at * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) + '  ' + l.what)) : [el('div', {style: 'color:var(--muted);font-size:14px'}, 'Nothing yet.')]),
      el('button', {class: 'btn danger', type: 'button', onclick: async () => { if (!confirm('Disconnect ' + a.name + '? The saved secret is deleted now.')) return; await post('/api/apps/' + a.id + '/disconnect'); close(); openApps(); }}, 'Disconnect and delete the secret'));
  } else {
    const inputs = {};
    kids.push(el('div', {style: 'color:var(--muted);font-size:14px'}, el('b', {style: 'color:var(--text)'}, 'How to get it: '), a.steps));
    for (const f of a.fields) {
      const inp = f.choices ? el('select', {'aria-label': f.label}, ...f.choices.map((c) => el('option', {value: c}, c[0].toUpperCase() + c.slice(1)))) : f.multiline ? el('textarea', {class: 'f', placeholder: f.placeholder || '', 'aria-label': f.label}) : el('input', {type: f.secret ? 'password' : 'text', placeholder: f.placeholder || '', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', 'aria-label': f.label});
      inputs[f.id] = inp; kids.push(el('label', {class: 'f'}, f.label, inp));
    }
    kids.push(el('div', {style: 'color:var(--muted);font-size:14px'}, 'It is checked once, kept on this server' + (c_encrypted() ? ' encrypted' : ' (NOT encrypted: ask the owner to install the cryptography package)') + ', never shown again, never given to the model, and deleted the moment you disconnect. Read-only.'), out,
      el('button', {class: 'btn', type: 'button', onclick: async (e) => { e.target.disabled = true; out.style.color = 'var(--muted)'; out.textContent = 'Checking...';
        const rr = await post('/api/apps/' + a.id + '/connect', {fields: Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, v.value]))}); const j = await rr.json(); e.target.disabled = false;
        if (!rr.ok) return fail(j); close(); openAppConnect(a, j.connection); }}, 'Connect'));
  }
  const m = dialog(kids, 'Back'); m.querySelector('.dialog').lastElementChild.onclick = () => { m.remove(); openApps(); };
}
let APPS_ENCRYPTED = true; const c_encrypted = () => APPS_ENCRYPTED;

// GitHub: connect with a token you make and can delete any time
async function openGithubConnect(after) {
  const r = await api('/api/apps'); const g = (await r.json()).connections.github;
  const kids = [el('h2', {}, 'GitHub')];
  const out = el('div', {style: 'color:var(--muted);font-size:14px;word-break:break-word'});
  const close = () => document.querySelectorAll('.modal').forEach((m) => m.remove());
  if (g.connected) {
    kids.push(el('div', {}, 'Connected as ', el('b', {}, '@' + g.login), '. VryxCode can create repositories for your projects and pull and push. Pulling, pushing and creating always ask you first, and the model never sees your token.'));
    kids.push(el('b', {}, 'Recent activity'));
    kids.push(...(g.log.length ? g.log.map((l) => el('div', {style: 'color:var(--muted);font-size:14px'}, new Date(l.at * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) + '  ' + l.what)) : [el('div', {style: 'color:var(--muted);font-size:14px'}, 'Nothing yet.')]));
    kids.push(el('button', {class: 'btn danger', onclick: async () => { if (!confirm('Disconnect GitHub? The saved token is deleted now.')) return; await post('/api/apps/github/disconnect'); close(); if (after) after(); }}, 'Disconnect and delete the token'));
  } else {
    if (g.device) {
      const status = el('div', {style: 'color:var(--muted);font-size:14px'});
      kids.push(el('div', {style: 'color:var(--muted)'}, 'The easy way: sign in with GitHub. You get a short code, type it on github.com, and say yes. You never handle a token.'),
        el('button', {class: 'btn', onclick: async (e) => {
          e.target.disabled = true; status.style.color = 'var(--muted)'; status.textContent = 'Starting...';
          const r = await post('/api/apps/github/device/start'); const d = await r.json();
          if (!r.ok) { e.target.disabled = false; status.style.color = 'var(--danger)'; status.textContent = d.message + ' ' + (d.action || ''); return; }
          status.replaceChildren('Open ', el('a', {href: d.verification_uri, target: '_blank', rel: 'noopener', style: 'color:var(--accenttext)'}, d.verification_uri.replace('https://', '')), ' and enter ', el('b', {style: 'font-size:20px;letter-spacing:.1em;color:var(--text)'}, d.user_code), '. Waiting for you to say yes...');
          const stop = Date.now() + d.expires_in * 1000;
          const tick = async () => {
            if (!document.body.contains(status)) return;
            if (Date.now() > stop) { status.textContent = 'That code ran out. Try again.'; e.target.disabled = false; return; }
            const pr = await post('/api/apps/github/device/poll'); const pj = await pr.json();
            if (pj.status === 'done') { close(); if (after) after(); else openGithubConnect(); return; }
            if (pj.status === 'denied' || pj.status === 'expired' || !pr.ok) { status.style.color = 'var(--danger)'; status.textContent = pj.status === 'denied' ? 'You said no on GitHub.' : (pj.message || 'That sign-in ended. Try again.'); e.target.disabled = false; return; }
            setTimeout(tick, Math.max(2, pj.wait || d.interval) * 1000);
          };
          setTimeout(tick, d.interval * 1000);
        }}, 'Sign in with GitHub'), status, el('div', {style: 'color:var(--muted);font-size:14px'}, 'Or paste a token instead:'));
    }
    const tok = el('input', {type: 'password', placeholder: 'Paste your GitHub token', autocomplete: 'off', 'aria-label': 'GitHub token'});
    kids.push(el('div', {style: 'color:var(--muted)'}, 'Make a token on GitHub (Settings > Developer settings > Personal access tokens) and paste it here. Give it the least it needs: a fine-grained token limited to the repositories you choose, with Contents read and write, is enough to pull and push. Creating new repositories needs a classic token with the repo permission (GitHub’s rule).'),
      el('div', {style: 'color:var(--muted);font-size:14px'}, 'The token is kept on this server encrypted' + (g.encrypted ? '' : ' (NOT encrypted: ask the owner to install the cryptography package)') + ', never shown again, never given to the model, and deleted the moment you disconnect.'),
      tok, out, el('button', {class: 'btn', onclick: async () => {
        const rr = await post('/api/apps/github/connect', {token: tok.value}); const j = await rr.json();
        if (!rr.ok) { out.style.color = 'var(--danger)'; out.textContent = j.message + ' ' + (j.action || ''); return; }
        close(); if (after) after(); else openGithubConnect();
      }}, 'Connect'));
  }
  dialog(kids, 'Close');
}

// Pick one of your own GitHub repositories and copy it into a new project (VryxCode > project menu > Import from GitHub)
async function openRepoPicker() {
  const r = await api('/api/code/git?project=' + encodeURIComponent(C.project)); const g = await r.json();
  if (!g.connected) { openGithubConnect(() => openRepoPicker()); return; }
  const list = el('div', {style: 'display:flex;flex-direction:column;gap:8px;max-height:52vh;overflow:auto'}, el('div', {style: 'color:var(--muted)'}, 'Loading your repositories...'));
  const find = el('input', {type: 'text', placeholder: 'Search your repositories', 'aria-label': 'Search your repositories', style: 'width:100%'});
  const out = el('div', {style: 'color:var(--muted);font-size:14px;word-break:break-word'}), note = el('div', {});
  const close = () => document.querySelectorAll('.modal').forEach((m) => m.remove());
  const typed = el('input', {type: 'text', placeholder: 'owner/name, for one that is not listed', 'aria-label': 'Repository to import by name', style: 'width:100%', autocapitalize: 'none', spellcheck: 'false'});
  const importByName = async (name, btn) => {
    if (btn) btn.disabled = true; out.style.color = 'var(--muted)'; out.textContent = 'Copying ' + name + '... this can take a minute for a big repository.';
    const rr = await post('/api/code/git', {project: C.project, action: 'import', repo: name}); const j = await rr.json().catch(() => ({}));
    if (!rr.ok) { if (btn) btn.disabled = false; out.style.color = 'var(--danger)'; out.textContent = (j.message || 'That did not work.') + ' ' + (j.action || ''); return; }
    if (!C.info.projects.includes(j.project)) C.info.projects.push(j.project);
    C.project = j.project; C.file = null; close(); renderCodeBar(); refreshFiles(); toast(j.message);
  };
  let repos = [];
  const draw = () => {
    const q = find.value.trim().toLowerCase(), shown = repos.filter((x) => !q || (x.full_name + ' ' + x.description).toLowerCase().includes(q));
    list.replaceChildren(...(shown.length ? shown.map((x) => el('div', {class: 'srow stack', style: 'border:1px solid var(--line);border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;gap:6px'},
      el('div', {}, el('b', {style: 'word-break:break-all'}, x.full_name), ' ', x.private ? el('small', {style: 'color:var(--muted)'}, '\u00b7 private') : null),
      x.description ? el('small', {style: 'color:var(--muted)'}, x.description) : null,
      el('div', {style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center'},
        el('button', {class: 'btn small', onclick: (e) => importByName(x.full_name, e.currentTarget)}, 'Import as a new project'), x.updated ? el('small', {style: 'color:var(--muted)'}, 'updated ' + x.updated) : null))) : [el('div', {style: 'color:var(--muted)'}, repos.length ? 'No repository matches that.' : 'No repositories found for this GitHub account.')]));
  };
  find.oninput = draw;
  dialog([el('h2', {}, 'Import from GitHub'), el('div', {style: 'color:var(--muted);font-size:14px'}, 'Connected as @' + g.login + '. Pick a repository: it is copied into a new VryxCode project of its own, and stays linked to GitHub so you can pull and push.'), find, note, list, el('b', {style: 'margin-top:6px'}, 'Or type its name'), typed, el('button', {class: 'btn ghost', type: 'button', onclick: (e) => importByName(typed.value.trim(), e.currentTarget)}, 'Import it'), out], 'Close');
  try {
    const rr = await api('/api/code/github/repos'); const j = await rr.json();
    if (!rr.ok) throw new Error((j.message || 'Could not load your repositories.') + ' ' + (j.action || ''));
    repos = j.repos; draw();
    const total = repos.length, privateSeen = j.private_seen || 0;
    const hint = !total ? 'No repositories came back. This connection may not be allowed to see any.' :
      (!privateSeen ? 'Only public repositories are showing (' + total + '). This connection cannot see your private ones.' : total + ' repositories shown (' + privateSeen + ' private).');
    const fix = (!privateSeen || j.token_kind === 'fine-grained') ? el('div', {style: 'color:var(--muted);font-size:13px;margin-top:4px'},
      j.token_kind === 'fine-grained' ? 'This is a fine-grained token: it only sees the repositories you ticked when you made it. ' : '',
      'To see private ones: Disconnect GitHub in Menu > Connected apps, then connect again with a classic token that has the "repo" permission (GitHub > Settings > Developer settings > Personal access tokens > Tokens (classic)), or a fine-grained token set to "All repositories" with Contents: Read and write.') : null;
    note.replaceChildren(el('div', {style: 'color:var(--muted);font-size:14px'}, hint), fix);
  } catch (e) { list.replaceChildren(el('div', {style: 'color:var(--danger)'}, e.message)); }
}

// GitHub for one VryxCode project: create / link / clone, pull, push
async function openProjectGithub() {
  const r = await api('/api/code/git?project=' + encodeURIComponent(C.project)); const g = await r.json();
  const close = () => document.querySelectorAll('.modal').forEach((m) => m.remove());
  const kids = [el('h2', {}, 'GitHub · ' + C.project)];
  const out = el('div', {style: 'color:var(--muted);font-size:14px;word-break:break-word;white-space:pre-wrap'});
  const act = async (body, then) => {
    out.style.color = 'var(--muted)'; out.textContent = 'Working...';
    const rr = await post('/api/code/git', Object.assign({project: C.project}, body)); const j = await rr.json();
    if (!rr.ok) { out.style.color = 'var(--danger)'; out.textContent = j.message + ' ' + (j.action || ''); return; }
    out.textContent = j.message; refreshFiles(); if (then) then();
  };
  if (!g.connected) {
    kids.push(el('div', {style: 'color:var(--muted)'}, 'Connect your GitHub account first. Then VryxCode can create a repository for this project and pull and push.'),
      el('button', {class: 'btn', onclick: () => { close(); openGithubConnect(() => openProjectGithub()); }}, 'Connect GitHub'));
  } else if (!g.linked) {
    const name = el('input', {type: 'text', value: C.project, 'aria-label': 'New repository name'}), priv = el('input', {type: 'checkbox', checked: 'checked'});
    const repo = el('input', {type: 'text', placeholder: 'owner/name', 'aria-label': 'Existing repository'});
    kids.push(el('div', {style: 'color:var(--muted)'}, 'Connected as @' + g.login + '. This project is not linked to a repository yet.'),
      el('b', {}, 'Create a new repository'), name, el('label', {style: 'display:flex;gap:8px;align-items:center;color:var(--muted)'}, priv, 'Private'),
      el('button', {class: 'btn', onclick: () => { if (confirm('Create the repository "' + name.value + '" on your GitHub account?')) act({action: 'create_repo', name: name.value, private: priv.checked}, () => { close(); openProjectGithub(); }); }}, 'Create and link'),
      el('b', {}, 'Or use one you already have'), el('button', {class: 'btn ghost', onclick: () => { close(); openRepoPicker(); }}, 'Browse my repositories...'), repo,
      el('div', {class: 'row', style: 'display:flex;gap:8px;flex-wrap:wrap'},
        el('button', {class: 'btn ghost', onclick: () => act({action: 'link', repo: repo.value}, () => { close(); openProjectGithub(); })}, 'Link this project to it'),
        el('button', {class: 'btn ghost', onclick: () => { if (confirm('Copy that repository into this project? (The project must be empty.)')) act({action: 'clone', repo: repo.value}, () => { close(); openProjectGithub(); }); }}, 'Clone it into this project')));
  } else {
    const prot = ['main', 'master'].includes(g.branch);
    kids.push(el('div', {}, 'Linked to ', el('b', {}, g.owner + '/' + g.name), '. Branch ', el('b', {}, g.branch || '(none)'), '.'),
      el('div', {style: 'color:var(--muted);font-size:14px'}, (g.ahead ? g.ahead + ' commit' + (g.ahead > 1 ? 's' : '') + ' not pushed yet. ' : 'Nothing waiting to push. ') + (g.changed_files ? g.changed_files + ' changed file' + (g.changed_files > 1 ? 's' : '') + ' not committed yet (VryxCode commits when you ask it to).' : '')),
      el('div', {style: 'display:flex;gap:8px;flex-wrap:wrap'},
        el('button', {class: 'btn ghost', onclick: () => { if (confirm('Fetch new work from ' + g.owner + '/' + g.name + ' into this project? (Fast-forward only: it never rewrites your work.)')) act({action: 'pull'}, () => { close(); openProjectGithub(); }); }}, 'Pull'),
        el('button', {class: 'btn', onclick: () => {
          if (!confirm('Send the branch "' + g.branch + '" to ' + g.owner + '/' + g.name + ' on GitHub?')) return;
          let sure = false; if (prot) { sure = confirm('"' + g.branch + '" is the main branch. Push straight to it?'); if (!sure) return; }
          act({action: 'push', confirm_protected: sure}, () => { close(); openProjectGithub(); });
        }}, 'Push')),
      el('button', {class: 'chip', onclick: () => { close(); openGithubConnect(); }}, 'Manage the GitHub connection'));
  }
  kids.push(out); dialog(kids, 'Close');
}

// ---------------------------------------------------------------- saved notes
async function openSaved() {
  const r = await api('/api/saved-notes'); const j = await r.json();
  const kids = [el('h2', {}, 'Saved notes')];
  if (!j.notes.length) kids.push(el('div', {style: 'color:var(--muted)'}, 'Nothing saved yet. Tap \ud83d\udc4d Right under an answer to keep the notes it used.'));
  for (const n of j.notes) {
    const row = el('div', {class: 'opt', style: 'cursor:default'}, el('span', {class: 'grow'}, el('b', {}, n.title), el('small', {}, 'For: ' + n.question),
      el('small', {style: 'font-size:13px'}, (n.origin === 'web' ? 'From the web' : 'From Wikipedia') + ' \u00b7 saved ' + new Date(n.saved_at * 1000).toLocaleDateString() + ' \u00b7 kept until ' + new Date(n.expires_at * 1000).toLocaleDateString())),
      el('button', {class: 'chip', onclick: async () => { await post('/api/saved-notes/delete', {id: n.id}); row.remove(); }}, 'Delete'));
    kids.push(row);
  }
  if (j.notes.length) kids.push(el('button', {class: 'btn danger', onclick: async () => { if (confirm('Delete every saved note?')) { await post('/api/saved-notes/clear'); document.querySelectorAll('.modal').forEach((m) => m.remove()); } }}, 'Delete all saved notes'));
  dialog(kids, 'Close');
}

// ---------------------------------------------------------------- memory (facts about you, shared by every model)
async function openMemory() {
  const r = await api('/api/memory'); const j = await r.json();
  const list = el('div', {style: 'display:flex;flex-direction:column;gap:8px'});
  const draw = (facts) => {
    list.replaceChildren(...(facts.length ? facts.map((f) => { const row = el('div', {class: 'opt', style: 'cursor:default'}, el('span', {class: 'grow'}, f.text),
      el('button', {class: 'chip', onclick: async () => { await post('/api/memory/delete', {id: f.id}); row.remove(); }}, 'Delete')); return row; })
      : [el('div', {style: 'color:var(--muted)'}, 'Nothing yet. Say something like "my name is Sam" or "remember that I prefer Python" in any chat and every model will know it.')]));
  };
  draw(j.facts);
  const input = el('input', {type: 'text', placeholder: 'Add something, e.g. I live in Austin', maxlength: 200, style: 'width:100%;padding:12px;border-radius:12px;border:1px solid var(--line);background:transparent;color:var(--text)'});
  const msg = el('div', {style: 'color:var(--muted);font-size:14px'});
  const add = async () => { if (!input.value.trim()) return; const rr = await post('/api/memory/add', {text: input.value}); const jj = await rr.json().catch(() => ({}));
    if (rr.ok) { input.value = ''; msg.textContent = ''; draw(jj.facts); } else msg.textContent = (jj.message || 'Not saved.') + ' ' + (jj.action || ''); };
  const kids = [el('h2', {}, 'Memory'),
    el('div', {style: 'color:var(--muted);font-size:14px'}, 'These are kept on the server and given to whichever model you talk to, so a new chat or a different model already knows them. Private chats never save or read them. Passwords, card numbers and the like are never kept. Turn memory off in Settings.' + (j.on ? '' : ' It is OFF right now.')),
    list, input, el('button', {class: 'btn', onclick: add}, 'Add'), msg];
  if (j.facts.length) kids.push(el('button', {class: 'btn danger', onclick: async () => { if (confirm('Forget everything the app knows about you?')) { await post('/api/memory/clear'); draw([]); } }}, 'Forget everything'));
  dialog(kids, 'Close');
}
