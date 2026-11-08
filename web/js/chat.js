/* Chats list, the thread of messages, the composer and the usage line. */
// ---------------------------------------------------------------- chats
// newChat: start an empty chat (private if asked, with a skill and attached documents), unless a reply is still being written.
async function newChat(isPrivate, skill, docs) {
  // S is the page's one shared state object; busy means a reply is streaming right now.
  if (S.busy) return;
  // Reset the chat: no id yet (it is created when the first message is sent), no messages, and the title.
  S.skill = skill || ''; S.docs = docs || []; S.chatId = null; S.messages = []; S.title = isPrivate ? 'Private chat' : 'New chat'; S.private = !!isPrivate;
  // Close the phone menu, save what to remember, draw the empty thread and the attachments, focus the message box and refresh the chat list.
  document.body.classList.remove('menu-open'); remember(); renderThread(); renderAttached(); $('input').focus(); renderChats(); warmModel();
}
// openChat: load one saved chat from the server and show it.
async function openChat(id) {
  if (S.busy) return;
  // Ask the server for the chat; if that fails, reload everything.
  const r = await api('/api/chats/' + id); if (!r.ok) return load();
  // Copy the chat's id, messages, title, private flag and skill into the page state.
  const c = await r.json(); S.chatId = c.id; S.messages = c.messages; S.title = c.title; S.private = c.private; S.skill = c.skill || ''; S.docs = c.docs || []; S.chatCtx = c.ctx || null; S.plus = {versions: c.versions || {}, project: c.project || null};
  remember(); document.body.classList.remove('menu-open'); renderThread(true); renderAttached(); renderChats();
  // If the server is still writing a reply in this chat (for example after a reload), follow it live.
  if (c.generating) followReply();
}
// archive: out of the chat list, but kept, searchable, and still remembered (questions like "what did we talk about last time" can use it)
// archiveChat: move a chat in or out of the archive (kept and searchable, just out of the list).
async function archiveChat(c, on) {
  await post('/api/chats/' + c.id + '/archive', {archived: on});
  // If the open chat was archived, show an empty new chat instead.
  if (on && S.chatId === c.id) { S.chatId = null; S.messages = []; S.title = 'New chat'; remember(); }
  await load();
}
// openArchived: a window that lists the archived chats, each with Open, Unarchive and Delete.
async function openArchived() {
  const box = el('div', {class: 'arch'}, el('p', {style: 'color:var(--muted)'}, 'Loading\u2026'));
  // fill (re)loads the archived list from the server.
  const fill = async () => {
    const j = await (await api('/api/chats/archived')).json().catch(() => ({chats: []}));
    // Nothing archived: say how to archive.
    if (!j.chats.length) { box.replaceChildren(el('p', {style: 'color:var(--muted)'}, 'Nothing archived. Archive a chat from its \u22ef menu, or everything at once in Settings > Data controls.')); return; }
    // One row per archived chat.
    box.replaceChildren(...j.chats.map((c) => el('div', {class: 'srow'}, el('div', {class: 'stxt'}, el('b', {}, c.title || 'Untitled'), el('small', {}, new Date(c.updated * 1000).toLocaleDateString())),
      el('div', {class: 'sctl'},
        sxBtn('Open', async () => { m.remove(); closeSettings(); await openChat(c.id); }),
        sxBtn('Unarchive', async () => { await archiveChat(c, false); fill(); }),
        sxBtn('Delete', async () => { await delChat(c); fill(); }, 'bad')))));
  };
  // The dialog that holds the list.
  const m = dialog([el('h2', {}, 'Archived chats'), el('div', {style: 'color:var(--muted);margin-bottom:8px'}, 'Out of your chat list, but kept, searchable and still remembered.'), box], 'Close');
  fill();
}
// delChat: delete a chat for good, after asking.
async function delChat(c) {
  if (!confirm('Delete "' + c.title + '"? This cannot be undone.')) return;
  await api('/api/chats/' + c.id, {method: 'DELETE'});
  // If the deleted chat was open, show an empty new chat.
  if (S.chatId === c.id) { S.chatId = null; S.messages = []; S.title = 'New chat'; remember(); }
  await load();
}

// ---------------------------------------------------------------- thread
// bullets: turn "- item" lines into real bullet points.
const bullets = (t) => String(t || '').replace(/^(\s*)[-*] (?=\S)/gm, '$1\u2022 ');      // "- item" lines show as real bullet points (Copy keeps the plain text)
// fixesOn: is the chat_fixes switch on for this person?
const fixesOn = () => !!(S.state && S.state.features && S.state.features.chat_fixes);
// richText: show **bold** and # headings as formatted text; with the newer formatting switch on, a full Markdown renderer is used.
function richText(t) {   // **bold** and "# heading" lines show as bold text instead of stars and hashes (Copy keeps the plain text); with chat_fixes, full formatting (markdown.js)
  if (fixesOn()) return mdRender(t);
  // Build the text inside a fragment (a piece of page not on screen yet).
  const f = document.createDocumentFragment();
  bullets(String(t || '').replace(/^\s+/, '')).replace(/^#{1,4} +(.+)$/gm, '**$1**').split(/(\*\*[^*\n]+\*\*)/g).forEach((p) => { if (p) f.append(/^\*\*[^*\n]+\*\*$/.test(p) ? el('b', {}, p.slice(2, -2)) : p); });
  return f;
}
// The two texts saved for a picture or file sent without words.
const ONLY_SENT = ['(sent a picture)', '(sent a file)'];   // saved for a picture or file sent without words (documents.PICTURE_ONLY_TEXT, FILE_ONLY_TEXT): only it is shown
// bubble: build one message as it appears on screen (your own message, or the AI's reply with its buttons).
function bubble(m, last) {
  // A summary note replaces the early messages that were folded away.
  if (m.role === 'user' && m.content.startsWith(SUMMARY_MARK)) return el('div', {class: 'note'}, 'Earlier messages were summarized to save room');
  // Your own message: shows attached documents and a button to edit it.
  if (m.role === 'user') return plusMsgOr(m, last, el('div', {class: 'msg user'}, (m.docs && m.docs.length) ? el('div', {class: 'pics'}, ...m.docs.map((d) => isPic(d) ? el('img', {src: picUrl(d), alt: d.name, onclick: () => window.open(picUrl(d), '_blank', 'noopener')}) : el('span', {class: 'chip', title: d.name}, '\ud83d\udcc4 ' + d.name))) : '', m.content && !ONLY_SENT.includes(m.content) ? el('div', {class: 'bubble'}, m.content) : '', (S.chatId != null && !S.busy && typeof m.id === 'number' && m.content && !ONLY_SENT.includes(m.content)) ? el('div', {class: 'acts'}, el('button', {class: 'chip', title: 'Change this message and ask again', onclick: (e) => editMessage(m, e.currentTarget.closest('.msg'))}, 'Edit')) : ''));
  // Find the model that wrote this reply, for its name and logo.
  const model = allModels().find((c) => c.id === m.model_id);
  // The small header over a reply: logo, model name and whether the reply was cut short.
  const meta = el('div', {class: 'meta'}, logo(14, false, model ? model.name : 'brand'), mname(model) + (m.status === 'partial' ? ' · stopped' : ''));
  // The buttons under a reply: Copy first.
  const acts = el('div', {class: 'acts'}, el('button', {class: 'chip', onclick: (e) => { navigator.clipboard && navigator.clipboard.writeText(m.content); e.target.textContent = 'Copied'; setTimeout(() => e.target.textContent = 'Copy', 1500); }}, 'Copy'));
  // A thumbs-up style "Right answer" button, only in a saved chat and once the reply is done.
  if (S.chatId != null && S.chatId >= 0 && m.status === 'done') acts.append(el('button', {class: 'chip', title: 'Right answer: keep the notes it used, so it can answer this again offline', onclick: async (e) => {
    const b = e.currentTarget; b.disabled = true; try { const r = await post('/api/chats/' + S.chatId + '/messages/' + m.id + '/like'); const j = await r.json(); b.textContent = j.saved ? 'Saved' : 'Thanks'; } catch (x) { b.disabled = false; } }}, '\ud83d\udc4d Right'));
  // The less-used actions go behind one "More" button so the answer stays calm.
  const more = [];            // the less-used actions go behind one "More" button so the answer stays calm
  if (m.status === 'done' && (S.skill || m.content.length > 300)) more.push(['Save as\u2026', () => saveAs(m.content)]);
  // If the last reply was cut off, offer to continue it.
  if (last && !S.busy && m.cut && S.chatId != null) acts.append(el('button', {class: 'chip on', title: 'The answer stopped at its length limit: carry on from there', onclick: () => { S.cont = true; $('input').value = 'Continue'; send(); }}, 'Continue \u2192'));
  // up: the next stronger model, if there is one that is ready.
  const up = last && !S.busy && m.status === 'done' ? strongerModel(m.model_id) : null;
  // Add "Ask a stronger model" to the More list.
  if (up) more.push(['Ask ' + up.name + ' (a stronger model)', () => { S.model = up.id; remember(); renderComposer(); send(true); }]);
  // Add "Branch: new chat from here".
  if (S.chatId != null && typeof m.id === 'number' && m.status === 'done' && !S.busy) more.push(['Branch: new chat from here', () => branchChat(m)]);
  // Add "Report a problem".
  if (S.chatId != null && S.chatId >= 0 && m.status === 'done') more.push([m.fb ? 'Reported (thanks)' : 'Report a problem\u2026', (btn) => reportAnswer(m, btn)]);
  // Only the last reply can be regenerated.
  if (last && !S.busy) acts.append(el('button', {class: 'chip', 'aria-haspopup': 'true', onclick: (e) => regenMenu(e.currentTarget)}, 'Regenerate \u25be'));
  // Show the More button when it has anything in it.
  if (more.length) acts.append(el('button', {class: 'chip', 'aria-haspopup': 'true', 'aria-label': 'More actions', title: 'More', onclick: (e) => moreMenu(e.currentTarget, more)}, '\u22ef'));
  // Put it together: header, the formatted reply and the buttons.
  return plusMsgOr(m, last, el('div', {class: 'msg ai', 'data-id': m.id}, meta, el('div', {class: 'bubble'}, richText(m.content)), acts));
}
// Other files (chatplus.js) may add more to a message; this passes it through if they did.
const plusMsgOr = (m, last, node) => (typeof plusMsg === 'function' ? plusMsg(m, node, last) : node);     // chatplus.js adds its parts (switched on by their flags)
// moreMenu: a small floating menu of actions placed under a button.
function moreMenu(btn, items) {   // a small menu of the less-used answer actions
  // Remove any menu that is already open.
  document.querySelectorAll('.chatmenu').forEach((x) => x.remove());
  // Build the menu next to the button, kept inside the screen.
  const menu = el('div', {class: 'acctmenu chatmenu', role: 'menu', style: 'position:fixed;left:' + Math.max(8, Math.min(btn.getBoundingClientRect().left, innerWidth - 248)) + 'px;top:' + Math.min(btn.getBoundingClientRect().bottom + 4, innerHeight - 60 - items.length * 42) + 'px;right:auto;bottom:auto;width:240px;z-index:60'},
    ...items.map(([label, fn]) => el('button', {class: 'link', role: 'menuitem', style: 'min-height:40px', onclick: async () => { menu.remove(); await fn(btn); }}, label)));
  // Show it.
  document.body.append(menu);
  // Close it on the next click anywhere.
  setTimeout(() => document.addEventListener('click', function off() { menu.remove(); document.removeEventListener('click', off); }, {once: false}), 0);
}
// The models from smallest and quickest to strongest and slowest.
const MODEL_RANK = ['Flare', 'Equinox', 'Solstice', 'Apogee'];   // small and quick to strong and slow
// strongerModel: the next stronger ready model, or null.
function strongerModel(modelId) {   // the next stronger model that is ready for this person, or null
  const cur = allModels().find((x) => x.id === modelId); if (!cur) return null;
  // A model's rank is its place in that list plus a small bonus for a newer version.
  const rank = (x) => MODEL_RANK.indexOf(x.name) + (x.version ? x.version / 100 : 0);
  return allModels().filter((x) => x.state === 'ready' && MODEL_RANK.includes(x.name) && rank(x) > rank(cur) && x.name !== cur.name).sort((a, b) => rank(a) - rank(b))[0] || null;
}
// editMessage: replace your message with a text box so you can change what you asked, then forget the answers after it and ask again.
function editMessage(m, node) {   // change what you asked, forget the answers after it, and ask again
  const ta = el('textarea', {class: 'f', style: 'width:100%;min-height:80px;background:var(--bg);border:1px solid var(--line);border-radius:12px;color:var(--text);padding:10px;font:inherit', 'aria-label': 'Edit your message'}, m.content);
  // How many messages come after this one (they will be replaced).
  const later = S.messages.length - 1 - S.messages.findIndex((x) => x.id === m.id);
  // The save button.
  const go = el('button', {class: 'btn small', onclick: async () => {
    if (!ta.value.trim()) return;
    // Ask before throwing away later answers.
    if (later > 0 && !confirm('This replaces the ' + (later === 1 ? 'answer' : 'answers') + ' after it with a new one. Continue?')) return;
    // Send the edit to the server.
    const r = await post('/api/chats/' + S.chatId + '/messages/' + m.id + '/edit', {text: ta.value}); const j = await r.json().catch(() => ({}));
    if (!r.ok) { alert(j.message || 'That did not work.'); return; }
    // Reload the chat and ask the question again.
    const c = await (await api('/api/chats/' + S.chatId)).json(); S.messages = c.messages; renderThread(); send(true);
  }}, 'Save and ask again');
  // Swap the message for the box and its buttons.
  node.replaceChildren(ta, el('div', {class: 'acts'}, go, el('button', {class: 'chip', onclick: () => renderThread()}, 'Cancel'))); ta.focus();
}
// branchChat: copy the chat up to one message into a new chat and open it.
async function branchChat(m) {
  const r = await post('/api/chats/' + S.chatId + '/branch', {message_id: m.id}); const j = await r.json().catch(() => ({}));
  if (!r.ok) { alert(j.message || 'That did not work.'); return; }
  await load(); openChat(j.id);
}
// reportAnswer: a window to tell us what was wrong with a reply (wrong fact, too long, and so on) with an optional note.
function reportAnswer(m, btn) {
  // The kinds of problem you can pick.
  const KINDS = [['wrong_fact', 'Wrong fact'], ['ignored', 'Ignored my question'], ['too_long', 'Too long'], ['too_short', 'Too short or vague'], ['cut_off', 'Cut off'], ['unsafe', 'Not appropriate'], ['other', 'Something else']];
  let kind = m.cut ? 'cut_off' : 'wrong_fact'; const note = el('textarea', {class: 'f', maxlength: '500', placeholder: 'Optional: what should it have said?', 'aria-label': 'What was wrong', style: 'width:100%;min-height:70px;background:var(--bg);border:1px solid var(--line);border-radius:12px;color:var(--text);padding:10px;font:inherit'});
  const out = el('div', {role: 'status', style: 'color:var(--muted);font-size:14px'});
  // One button per kind.
  const kinds = el('div', {class: 'kinds'}, ...KINDS.map(([id, label]) => el('button', {class: 'chip' + (id === kind ? ' on' : ''), type: 'button', onclick: (e) => { kind = id; [...kinds.children].forEach((b) => b.classList.remove('on')); e.currentTarget.classList.add('on'); }}, label)));
  const d = dialog([el('h2', {}, 'What went wrong?'), el('div', {style: 'color:var(--muted);font-size:14px'}, 'This sends the question and the answer to the owner of this Emvryx, to help fix it. Nothing else from your chat is sent, and private chats can\u2019t be reported.'), kinds, note, out,
    el('button', {class: 'btn', type: 'button', onclick: async () => { const r = await post('/api/chats/' + S.chatId + '/messages/' + m.id + '/feedback', {kind, note: note.value}); const j = await r.json().catch(() => ({}));
      if (!r.ok) { out.style.color = 'var(--danger)'; out.textContent = j.message || 'That did not work.'; return; } m.fb = kind; btn.textContent = 'Reported'; d.remove(); toast('Thanks. The owner will see it.'); }}, 'Send report')], 'Cancel');
}
// dayCard: "Your day": one tap reads today from the connected apps (nothing is read until you tap).
function dayCard() {   // "Your day": one tap reads today from the connected apps (nothing is read until you tap)
  const box = el('div', {class: 'sx-card', style: 'max-width:560px;margin:18px auto 0;padding:14px 16px;display:flex;flex-direction:column;gap:10px'});
  // show reads the day and displays it.
  const show = async (btn) => {
    btn.disabled = true; btn.textContent = 'Reading your apps...';
    let j; try { j = await (await api('/api/briefing')).json(); } catch (e) { btn.disabled = false; btn.textContent = 'Show my day'; return; }
    const text = j.sections.map((s) => s.kind + ' (' + s.app + '):\n' + (s.items.length ? s.items.map((i) => '- ' + i.title + (i.text ? ' (' + i.text + ')' : '')).join('\n') : s.error ? '- (could not be read: ' + s.error + ')' : '- nothing')).join('\n');
    box.replaceChildren(el('b', {}, 'Your day'), ...j.sections.map((s) => el('div', {}, el('div', {style: 'font-weight:600;font-size:14px'}, s.kind + '  \u00b7  ' + s.app),
      ...(s.items.length ? s.items.map((i) => el('div', {style: 'font-size:14px;color:var(--muted)'}, '\u2022 ' + i.title + (i.text ? '  (' + i.text + ')' : ''))) : [el('div', {style: s.error ? 'color:var(--danger);font-size:14px' : 'color:var(--muted);font-size:14px'}, s.error ? 'Could not read it: ' + s.error : 'Nothing.')]))),
      el('div', {style: 'display:flex;gap:8px;flex-wrap:wrap'}, el('button', {class: 'chip on', onclick: () => { $('input').value = 'Here is my day. Please give me a short plan: what to do first, and anything I should not forget.\n\n' + text; send(); }}, 'Plan my day with Emvryx'), el('button', {class: 'chip', onclick: () => renderThread(false)}, 'Hide')));
  };
  box.append(el('b', {}, 'Your day'), el('div', {style: 'color:var(--muted);font-size:14px'}, 'See today\u2019s calendar, open tasks and newest mail from the apps you connected. Nothing is read until you tap.'), el('button', {class: 'btn small', style: 'align-self:flex-start', onclick: (e) => show(e.currentTarget)}, 'Show my day'));
  return box;
}
// chatAsText: the whole chat as plain text, for saving as a file.
function chatAsText() {
  const names = {}; allModels().forEach((m) => { names[m.id] = mname(m); });
  return '# ' + S.title + '\n\n' + S.messages.filter((m) => m.content && !m.content.startsWith(SUMMARY_MARK)).map((m) => (m.role === 'user' ? '**You:** ' : '**' + (names[m.model_id] || 'Emvryx') + ':** ') + m.content).join('\n\n');
}
// The chat's "..." menu: share a link, save as PDF or Word, and so on.
$('chatMore').onclick = (e) => {
  e.stopPropagation(); document.querySelectorAll('.chatmenu').forEach((m) => m.remove());
  const r = e.currentTarget.getBoundingClientRect(), item = (label, fn) => el('button', {class: 'link', style: 'min-height:42px', onclick: () => { menu.remove(); fn(); }}, label);
  const menu = el('div', {class: 'acctmenu chatmenu', style: 'position:fixed;top:' + (r.bottom + 4) + 'px;right:10px;left:auto;bottom:auto;width:220px;z-index:60'},
    ...(S.chatId >= 0 ? [item('Share a link\u2026', shareDialog)] : []), item('Save as PDF or Word\u2026', () => saveAs(chatAsText(), S.title)), ...(S.chatId >= 0 ? [item('Delete this chat', () => delChat({id: S.chatId, title: S.title}))] : []));
  document.body.append(menu); setTimeout(() => document.addEventListener('click', () => menu.remove(), {once: true}), 0);
};
// shareDialog: make read-only links to a copy of this chat, and list or revoke earlier links.
async function shareDialog() {
  const j = await (await api('/api/shares')).json(), out = el('div', {role: 'status', style: 'color:var(--muted);font-size:14px;word-break:break-all'}), listBox = el('div', {style: 'display:flex;flex-direction:column;gap:8px'});
  const refresh = (shares) => listBox.replaceChildren(...(shares.length ? [el('b', {}, 'Your links')] : []), ...shares.map((s) => el('div', {class: 'opt', style: 'cursor:default'}, el('span', {class: 'grow'}, el('b', {}, s.title), el('small', {}, 'Works until ' + new Date(s.expires * 1000).toLocaleDateString())),
    el('button', {class: 'chip', onclick: async () => { await post('/api/shares/revoke', {id: s.id}); refresh((await (await api('/api/shares')).json()).shares); }}, 'Cancel link'))));
  refresh(j.shares);
  if (!j.on) { dialog([el('h2', {}, 'Share a link'), el('p', {style: 'margin:0;color:var(--muted)'}, 'Sharing links is switched off on this Emvryx. The owner can turn it on in Admin > Overview.'), listBox], 'Close'); return; }
  // How many days a new link works: 1, 7 or 30.
  let days = 7;
  const seg = el('div', {class: 'seg'}, ...[[1, '1 day'], [7, '7 days'], [30, '30 days']].map(([d, t]) => el('button', {class: d === 7 ? 'on' : '', type: 'button', onclick: (e) => { days = d; [...seg.children].forEach((b) => b.classList.remove('on')); e.currentTarget.classList.add('on'); }}, t)));
  dialog([el('h2', {}, 'Share a link'), el('p', {style: 'margin:0;color:var(--muted)'}, 'Anyone who has the link can read a copy of this chat as it is now: only the words, not pictures, files or later messages. You can cancel the link any time. Private chats can\u2019t be shared.'), seg,
    el('button', {class: 'btn', onclick: async (e) => { const r = await post('/api/chats/' + S.chatId + '/share', {days}); const k = await r.json().catch(() => ({})); if (!r.ok) { out.style.color = 'var(--danger)'; out.textContent = (k.message || 'That did not work.') + ' ' + (k.action || ''); return; }
      const url = location.origin + k.url; out.style.color = 'var(--text)'; out.replaceChildren(el('div', {style: 'margin-bottom:8px'}, url), el('button', {class: 'chip', onclick: async (b) => { try { await navigator.clipboard.writeText(url); b.target.textContent = 'Copied'; } catch (x) { b.target.textContent = 'Press and hold the link to copy'; } }}, 'Copy link')); refresh(k.shares); }}, 'Make a link'), out, listBox], 'Close');
}
// isTeacherChat: is this a Teacher mode chat?
function isTeacherChat() { return S.skill === 'teacher' || S.skill === 'study'; }
// teacherHome: the start page of a Teacher mode chat: type anything, or tap a tool.
function teacherHome(sk) {   // the start of a Teacher mode chat: type anything, or tap a tool
  const side = S.skill === 'study' ? 'student' : 'teacher';
  const tab = (id, skill, label) => el('button', {class: 'chip' + (side === id ? ' on' : ''), onclick: () => { S.skill = skill; remember(); renderThread(false); }}, label);
  const box = el('div', {class: 'empty', style: 'padding:24px 0'}, logo(56), el('h1', {}, 'Teacher mode'),
    el('div', {}, side === 'teacher' ? 'Ask for anything in your own words, or tap a tool below. Every number comes from an exact calculator, never a guess.' : 'Ask anything, or tap a tool. It guides you to the answer instead of just giving it.'),
    el('div', {class: 'tabs', style: 'justify-content:center;margin:14px 0 6px'}, tab('teacher', 'teacher', 'For teachers'), tab('student', 'study', 'For students')));
  if (!S.tools) { loadTeacher().then(() => { if (!S.messages.length && isTeacherChat()) renderThread(false); }).catch(() => {}); return box; }
  // Two groups of tools: ones that make things and ones that calculate.
  for (const [kind, label] of [['make', 'MAKE'], ['calc', 'CALCULATE']]) {
    const list = S.tools.filter((t) => t.side === side && t.kind === kind); if (!list.length) continue;
    box.append(el('div', {class: 'label', style: 'padding:12px 0 6px'}, label),
      el('div', {style: 'display:flex;flex-wrap:wrap;gap:8px;justify-content:center'}, ...list.map((t) => el('button', {class: 'chip', title: t.blurb, onclick: () => openTool(t)}, t.name))));
  }
  return box;
}
// renderThread: draw the whole chat on screen: notes, the empty welcome page when there are no messages, then every message.
function renderThread(jump) {
  // Clear the thread and show the "..." button only when there is a saved chat with messages.
  const t = $('thread'); t.replaceChildren(); $('chatMore').hidden = !(S.chatId != null && S.messages.length);
  $('title').textContent = S.title;
  const sk = S.skills.find((x) => x.id === S.skill);
  // A private chat says it is not saved.
  if (S.private) t.append(el('div', {class: 'note'}, 'Private chat: not saved, and gone when you leave it'));
  const tc = isTeacherChat();
  if (sk) t.append(el('div', {class: 'note'}, sk.name + ' is on for this chat', tc ? el('button', {class: 'chip', style: 'margin-left:10px;min-height:30px;padding:2px 12px', onclick: () => openTeacher()}, 'Tools') : ''));
  // Teacher mode shows its own start page; otherwise an empty chat shows the welcome and ideas.
  if (!S.messages.length && tc) { t.append(teacherHome(sk)); }
  else if (!S.messages.length) t.append(el('div', {class: 'empty'}, logo(64), el('h1', {}, sk ? sk.name : 'How can I help?'),
    el('div', {}, sk ? sk.does : 'Ask anything. Pick a model and how much it should think under the box.'),
    sk ? el('button', {class: 'chip', style: 'margin-top:12px', onclick: () => { $('input').value = sk.try; $('input').focus(); }}, 'Try: ' + sk.try) : '',
    !sk && !S.private ? mlIdeas() : ''));
  // On an empty chat the "Your day" card may appear.
  if (!S.messages.length && !tc && !sk && !S.private && S.state && S.state.briefing) t.append(dayCard());
  // The last reply in the chat (only it gets the Regenerate button).
  const last = [...S.messages].reverse().find((m) => m.role === 'assistant');
  // Draw every message.
  S.messages.forEach((m) => t.append(bubble(m, last && m.id === last.id && m === S.messages[S.messages.length - 1])));
  // Scroll to the bottom unless the person scrolled away.
  if (jump !== false) scrollDown(true);
  renderCtx(null, S.compacting);
  if (typeof plusAfterThread === 'function') plusAfterThread();
  if (typeof pwaKeep === 'function') pwaKeep();                     // pwa_offline: kept for reading with no connection
}
// scrollDown: go to the bottom (always when forced, otherwise only if the person is already near the bottom).
function scrollDown(force) { const s = $('scroll'); if (force || S.stick) s.scrollTop = s.scrollHeight; }
// Remember whether the person is near the bottom, so new words do not pull the page away from what they are reading.
$('scroll').addEventListener('scroll', () => { const s = $('scroll'); S.stick = s.scrollHeight - s.scrollTop - s.clientHeight < 60; $('down').classList.toggle('show', !S.stick); });
$('down').onclick = () => { S.stick = true; scrollDown(true); };

// ---------------------------------------------------------------- composer
// The picture file types the message box accepts.
const IMG_KINDS = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'heic'];
const isPic = (d) => IMG_KINDS.includes(String(d.kind || (d.name || '').split('.').pop()).toLowerCase());
const picUrl = (d) => '/api/documents/' + d.id + '/image';
// sentIds: the ids of the documents already sent with earlier messages.
function sentIds() { return new Set(S.messages.flatMap((m) => (m.docs || []).map((d) => d.id))); }
// renderAttached: show what will go with the next message (pictures as small previews); what was already sent is left out.
function renderAttached() {   // what will go with the next message: pictures show as small previews; what was already sent now sits in its message
  const sent = sentIds(), pending = S.docs.filter((d) => !sent.has(d.id)); const box = $('attached'); box.hidden = !pending.length;
  box.replaceChildren(...pending.map((d) => el('span', {class: 'chip' + (isPic(d) ? ' pic' : ''), title: d.name},
    isPic(d) ? el('img', {src: picUrl(d), alt: d.name, class: 'thumb'}) : '\ud83d\udcc4 ', isPic(d) ? '' : el('span', {}, d.name),
    el('button', {class: 'icon', style: 'width:22px;height:22px;min-height:0', 'aria-label': 'Remove ' + d.name, onclick: () => setDocs(S.docs.filter((x) => x.id !== d.id))}, '\u00d7'))));
}
// setDocs: replace the list of attached documents and tell the server.
async function setDocs(list) {
  S.docs = list; renderAttached();
  if (S.chatId != null) { const r = await post('/api/chats/' + S.chatId + '/docs', {ids: list.map((d) => d.id)}); if (r.ok) { S.docs = (await r.json()).docs; renderAttached(); } }
}
// renderComposer: update the message box area: model button, effort button, memory meter and the send or stop button.
function renderComposer() {
  renderAttached();
  // curModel is the picked model; stop if there is none yet.
  const m = curModel(); if (!m) return;
  $('modelBtn').replaceChildren(logo(22), mname(m), el('span', {style: 'color:var(--muted)'}, '▾'));
  $('modelBtn').setAttribute('aria-label', 'Choose model: ' + mname(m));
  // The effort that is picked ("Auto" also says what it chose).
  const ef = S.state.efforts.find((e) => e.id === S.effort) || S.state.efforts.find((e) => e.id === 'balanced');
  const shown = S.effort === 'auto' && S.autoNote ? 'Auto \u00b7 ' + S.autoNote.effort[0].toUpperCase() + S.autoNote.effort.slice(1) : ef.name;
  $('effortBtn').replaceChildren(shown, el('span', {}, '▾'));
  renderCtx(null, S.compacting);
  // The send button shows an arrow, or a stop square while a reply is being written.
  const s = $('send'); s.className = 'send' + (S.busy ? ' stop' : ''); s.innerHTML = S.busy ? '&#9632;' : '&uarr;'; s.setAttribute('aria-label', S.busy ? 'Stop' : 'Send');
}
// closeMenus: close every pop-up menu of the message box.
function closeMenus() { $('modelMenu').hidden = true; $('effortMenu').hidden = true; $('attachMenu').hidden = true; $('ctxMenu').hidden = true; }
// ---------------------------------------------------------------- the memory meter (feature flag context_meter)
// How full the model's memory (context window) is after the last reply, and when the older messages will be summarized to make room.
// kTok: a token count in short form (12.3K).
const kTok = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1).replace(/\.0$/, '') + 'K' : String(n));
// lastCtx: how full the model's memory was after the last reply (a stand-in estimate when the server has not measured it yet).
function lastCtx() {   // the last reply's reading; for a chat from before the meter the server measures it; a new chat starts empty
  for (let i = S.messages.length - 1; i >= 0; i--) if (S.messages[i].ctx) return S.messages[i].ctx;
  if (S.messages.length && S.chatCtx) return S.chatCtx;
  const w = S.state && S.state.window && S.state.window.window; if (!w) return null;
  const used = Math.round(S.messages.reduce((n, m) => n + String(m.content || '').length, 0) / 3.5);   // an estimate until the next reply measures it exactly
  return {used, window: w, pct: Math.min(100, Math.round(1000 * used / w) / 10), compact_at: Math.floor(Math.min(0.75 * Math.max(64, w - 1024), 96000))};
}
// renderCtx: draw the memory ring button: how full the chat is, whether it is nearly at the point where older messages get summarized.
function renderCtx(ctx, busy) {
  const b = $('ctxBtn'), on = !!(S.state && S.state.features && S.state.features.context_meter);
  ctx = ctx || lastCtx(); S.ctx = ctx;
  b.hidden = !on || !ctx; if (b.hidden) return;
  b.style.setProperty('--p', Math.min(100, ctx.pct)); b.classList.toggle('near', ctx.used >= ctx.compact_at * 0.9); b.classList.toggle('busy', !!busy);
  b.textContent = Math.round(ctx.pct) + '%';
  b.setAttribute('aria-label', busy ? 'Summarizing earlier messages to make room' : 'Memory ' + Math.round(ctx.pct) + '% used, ' + kTok(ctx.used) + ' of ' + kTok(ctx.window) + ' tokens');
}
// ctxMenuNodes: the contents of the memory pop-up (used by chat and VryxCode).
function ctxMenuNodes(c, how, compact) {   // the meter's details (the chat and VryxCode share them); `compact` runs the "Compact now" button
  const left = Math.max(0, c.compact_at - c.used);
  return [el('div', {class: 'head'}, 'MEMORY (CONTEXT WINDOW)'),
    el('div', {class: 'ctxbar'}, el('div', {style: 'width:' + Math.min(100, c.pct) + '%'})),
    el('div', {class: 'ctxrow'}, el('b', {}, Math.round(c.pct) + '% used'), el('span', {}, kTok(c.used) + ' of ' + kTok(c.window) + ' tokens')),
    el('div', {class: 'ctxrow'}, el('span', {}, 'Free'), el('span', {}, kTok(Math.max(0, c.window - c.used)))),
    el('div', {class: 'ctxrow'}, el('span', {}, how[0]), el('span', {}, kTok(c.compact_at) + (left ? ' (' + kTok(left) + ' to go)' : ' (next step)'))),
    el('div', {class: 'head', style: 'text-transform:none;letter-spacing:0;font-weight:400'}, how[1]),
    compact ? el('button', {class: 'btn small', id: 'compactNow', style: 'align-self:flex-start;margin:2px 6px 4px', onclick: (ev) => { ev.stopPropagation(); ev.currentTarget.disabled = true; ev.currentTarget.textContent = 'Compacting\u2026'; compact(); }}, 'Compact now') : ''];
}
// compactChat: "Compact now": summarize the older messages of this chat at once.
async function compactChat() {   // "Compact now": summarize the older messages of this chat at once
  if (S.busy || S.chatId == null) return;
  S.compacting = true; renderCtx(null, true);
  let j = {};
  try { const r = await post('/api/chats/' + S.chatId + '/compact', {model: S.model}); j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.message || 'Could not compact.'); }
  catch (e) { S.compacting = false; closeMenus(); renderCtx(); $('thread').append(el('div', {class: 'note'}, e.message)); scrollDown(true); return; }
  S.compacting = false; closeMenus();
  try { const r = await api('/api/chats/' + S.chatId); if (r.ok) { const c = await r.json(); S.messages = c.messages; } } catch (e) { /* the meter below still updates */ }
  renderThread(false); renderCtx(j.context);
  $('thread').append(el('div', {class: 'note'}, j.folded ? 'Earlier messages were summarized to save room (' + j.folded + ' folded). You still see every message.' : 'Nothing old enough to summarize yet.')); scrollDown(true);
}
// The memory button opens or closes its pop-up.
$('ctxBtn').onclick = () => {
  const open = !$('ctxMenu').hidden; closeMenus(); if (open || !S.ctx) return;
  if (!S.messages.length) { $('ctxMenu').replaceChildren(...ctxMenuNodes(S.ctx, ['Summarizes at', 'This chat is empty. As it grows, the ring fills; near the limit the older messages are summarized so the chat can keep going.'])); $('ctxMenu').hidden = false; return; }
  $('ctxMenu').replaceChildren(...ctxMenuNodes(S.ctx, ['Summarizes at', 'When the chat gets near the limit, the older messages are summarized so the chat can keep going and answers stay sharp. You still see every message.'], S.busy ? null : compactChat));
  $('ctxMenu').hidden = false;
};
// The model button opens a list of models to pick, each with its tagline, and What's new if there is any.
$('modelBtn').onclick = () => {
  const open = !$('modelMenu').hidden; closeMenus(); if (open) return;
  const m = $('modelMenu'); m.replaceChildren(el('div', {class: 'head'}, 'SELECT MODEL'));
  // row builds one model line; it is greyed out when that model is not ready.
  const row = (c) => el('button', {class: 'opt' + (c.id === S.model ? ' sel' : ''), disabled: c.state !== 'ready', onclick: () => chooseModel(c)},
    logo(30, false, c.name), el('span', {class: 'grow'}, el('b', {}, mname(c)), el('small', {}, c.tagline || '')), el('small', {style: 'text-align:right'}, c.badge));
  // The main models first, then the "other" ones.
  for (const c of S.state.models.cards) m.append(row(c));
  if ((S.state.models.other || []).length) { m.append(el('div', {class: 'head'}, 'OTHER MODELS')); for (const c of S.state.models.other) m.append(row(c)); }
  const news = featureOn('whats_new') ? S.state.models.cards.filter((c) => c.whats_new) : [];
  if (news.length) { m.append(el('div', {class: 'head'}, 'WHAT\u2019S NEW'));
    for (const c of news) m.append(el('button', {class: 'opt', onclick: (ev) => { ev.stopPropagation(); whatsNew(c); }}, logo(30, false, c.name),
      el('span', {class: 'grow'}, el('b', {}, 'What\u2019s new in ' + mname(c)), el('small', {}, 'What is better than the version before')), '\u203a')); }
  m.hidden = false;
};
// What is better in a new model than the version before it (models.json "whats_new", feature flag whats_new): the points, then the scores.
// What is better in a new model than the version before it (models.json "whats_new", feature flag whats_new): the points, then the measured numbers side by side
function whatsNew(c) {
  const w = c.whats_new, all = [...S.state.models.cards, ...(S.state.models.other || [])], old = all.find((x) => x.id === w.vs);
  const oldName = old ? mname(old) : String(w.vs || 'the last version').replace(/-/g, ' ').replace(/^\w/, (x) => x.toUpperCase());
  const cell = (v, cls) => el('td', {style: 'padding:6px 8px;text-align:right' + (cls ? ';' + cls : '')}, v == null ? 'being measured' : v);
  const m = $('modelMenu'); m.replaceChildren(el('div', {class: 'head'}, 'WHAT\u2019S NEW IN ' + mname(c).toUpperCase()),
    el('div', {style: 'padding:0 6px;color:var(--muted);font-size:14px'}, 'Compared with ' + oldName + (c.preview ? '. In preview: only you and your admins see it until you publish it.' : '.')),
    el('ul', {style: 'margin:4px 0;padding-left:22px;display:flex;flex-direction:column;gap:6px'}, ...w.points.map((t) => el('li', {}, t))),
    (w.scores || []).length ? el('table', {style: 'width:100%;border-collapse:collapse;font-size:14px'},
      el('tr', {style: 'color:var(--muted)'}, el('td', {style: 'padding:6px 8px'}, ''), cell(oldName), cell(mname(c), 'font-weight:700;color:var(--text)')),
      ...w.scores.map((r) => el('tr', {style: 'border-top:1px solid var(--line)'}, el('td', {style: 'padding:6px 8px'}, r[0]), cell(r[1], 'color:var(--muted)'), cell(r[2], 'font-weight:700')))) : '',
    el('div', {class: 'row', style: 'gap:8px;margin-top:6px'}, el('button', {class: 'chip', onclick: (ev) => { ev.stopPropagation(); closeMenus(); $('modelBtn').click(); }}, '\u2039 Back to models'),
      c.tour && featureOn('model_tours') ? el('button', {class: 'chip', onclick: (ev) => { ev.stopPropagation(); closeMenus(); openModelTour(c, true); }}, 'Take the tour \u203a') : ''));
}
// The effort button opens a list: how much should it think (some models cannot do every level).
$('effortBtn').onclick = () => {
  const open = !$('effortMenu').hidden; closeMenus(); if (open) return;
  const m = $('effortMenu'); m.replaceChildren(el('div', {class: 'head'}, 'HOW MUCH SHOULD IT THINK?'));
  const cm = curModel();
  for (const e of S.state.efforts) { const blocked = cm && cm.efforts && !cm.efforts.includes(e.id) && e.id !== 'auto';
    m.append(el('button', {class: 'opt' + (e.id === S.effort ? ' sel' : ''), disabled: blocked, onclick: () => { S.effort = e.id; S.autoNote = null; try { localStorage.setItem('emvryx_effort', e.id); } catch (x) {} closeMenus(); renderComposer(); refreshUsage(); }},
      el('span', {class: 'grow'}, el('b', {}, e.name), ' ', el('small', {style: 'display:inline'}, '· ' + e.use), el('small', {}, blocked ? 'Needs Flare or a bigger model.' : e.blurb)), e.id === S.effort ? '✓' : '')); }
  m.append(el('div', {class: 'head', style: 'text-transform:none;letter-spacing:0;font-weight:400'}, 'Thinking longer is slower and uses more of your usage.'));
  m.hidden = false;
};
// A click anywhere outside the message box closes the menus.
document.addEventListener('click', (e) => { if (!e.target.closest('.box')) closeMenus(); });
// warmTimer waits a moment before loading a model, so quick switching does not load every model.
let warmTimer = null;
// warmModel: load the picked model in the background, so the next message does not wait for it
function warmModel() {   // load the picked model in the background, so the next message does not wait for it
  clearTimeout(warmTimer); warmTimer = setTimeout(() => { if (S.state && S.model && !S.busy) post('/api/models/warm', {model: S.model}).catch(() => {}); }, 500);
}
// chooseModel: pick a model, remember it for next time, fix the effort if the model cannot do it, repaint, and warm it up.
async function chooseModel(c) {
  closeMenus(); if (c.id === S.model) return;
  S.model = c.id; try { localStorage.setItem('emvryx_model', c.id); } catch (e) {}
  if (c.efforts && S.effort !== 'auto' && !c.efforts.includes(S.effort)) S.effort = 'balanced';
  wash(); applyTheme(); renderComposer(); renderThread(false); warmModel(); maybeModelTour(c); await refreshUsage();
}
// input is the message box.
const input = $('input');
// The message box is a rich text box so the phone keyboard can paste a screenshot into it; it reads and writes as plain text (images are taken out below).
// The message box is a rich text box so the phone keyboard can paste a screenshot into it; it reads and writes as plain text (input.value) like a textarea did.
// Make input.value behave like a normal text field: reading gives the plain text, writing replaces it (and keeps the cursor at the end).
Object.defineProperty(input, 'value', {
  get() { return (input.innerText || '').replace(/\u00a0/g, ' ').replace(/\n$/, ''); },
  set(v) { input.textContent = v == null ? '' : String(v); if (document.activeElement === input) { const r = document.createRange(); r.selectNodeContents(input); r.collapse(false); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); } }});
// Paste: pictures are attached (documents.js); anything else goes in as plain text, cut to 20,000 characters.
input.addEventListener('paste', (e) => {           // pictures are attached (documents.js); anything else goes in as plain text, never as formatting
  if (imageFilesFrom(e.clipboardData).length) return;
  e.preventDefault(); const t = (e.clipboardData && e.clipboardData.getData('text/plain')) || '';
  if (t) document.execCommand('insertText', false, t.slice(0, Math.max(0, 20000 - input.value.length)));
});
// A picture the phone keyboard inserts arrives here: attach it instead of putting it in the box.
input.addEventListener('beforeinput', (e) => {     // a picture the phone keyboard inserts (its "Paste" with a screenshot) arrives here on some browsers
  const files = e.dataTransfer ? imageFilesFrom(e.dataTransfer) : [];
  if (files.length) { e.preventDefault(); addFiles(files); }
});
// Watch the box: if a picture got put in as an <img>, take it out and attach it as a file.
new MutationObserver(() => {                       // ...and on others as an <img> put straight into the box: take it out and attach the picture instead
  for (const img of [...input.querySelectorAll('img')]) {
    const src = img.getAttribute('src') || ''; img.remove();
    const asFile = (b) => addFiles([new File([b], 'screenshot-' + Date.now() + '.' + ((b.type.split('/')[1] || 'png').replace('jpeg', 'jpg')), {type: b.type || 'image/png'})]);
    const m = /^data:(image\/[a-z0-9.+-]+);base64,(.*)$/i.exec(src);
    if (m) { const bin = atob(m[2]); const a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); asFile(new Blob([a], {type: m[1]})); }
    else if (src.startsWith('blob:')) {               // the page's own rules do not allow fetching it: draw it instead
      const pic = new Image(); pic.onload = () => { const c = document.createElement('canvas'); c.width = pic.naturalWidth; c.height = pic.naturalHeight; c.getContext('2d').drawImage(pic, 0, 0); c.toBlob((b) => b && asFile(b), 'image/png'); }; pic.src = src;
    }
  }
}).observe(input, {childList: true, subtree: true});
// Dropping files on the box attaches them.
input.addEventListener('drop', (e) => { if (!(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length)) { e.preventDefault(); const t = e.dataTransfer && e.dataTransfer.getData('text/plain'); if (t) document.execCommand('insertText', false, t); } });
// Keep the box clean and the length within its limit.
input.addEventListener('input', () => { if (!input.textContent && input.innerHTML) input.innerHTML = ''; if (input.value.length > 20000) input.value = input.value.slice(0, 20000); });   // :empty shows the placeholder again
// steering: a reply is being written and the person typed something, so it can steer the reply (the chat_steer switch).
const steering = () => S.busy && featureOn('chat_steer') && typeof steer === 'function' && !!input.value.trim();     // chat_steer: typing while it answers
// Enter sends (Shift+Enter makes a new line); not while an input method is composing a word or the + menu is open.
input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !(typeof plusMenuOpen === 'function' && plusMenuOpen())) { e.preventDefault(); steering() ? steer() : send(); } });
// The send button sends, steers or stops depending on what is going on.
$('send').onclick = () => (steering() ? steer() : S.busy ? stop() : send());
// The + button: a menu to upload files, photos, a folder or pick documents added before.
$('plus').onclick = () => {
  const open = !$('attachMenu').hidden; closeMenus(); if (open) return;
  const m = $('attachMenu'); const row = (icon, title, sub, fn) => el('button', {class: 'opt', onclick: () => { closeMenus(); fn(); }}, el('span', {style: 'font-size:20px;width:26px;text-align:center'}, icon), el('span', {class: 'grow'}, el('b', {}, title), el('small', {}, sub)));
  m.replaceChildren(row('\ud83d\udcc4', 'Upload files', 'PDF, Word, text', () => pickMany({accept: DOC_ACCEPT})),
    row('\ud83d\uddbc\ufe0f', 'Photos or screenshots', 'Attach a picture to your message', () => pickMany({accept: 'image/*'})),
    row('\ud83d\udcc1', 'Upload a folder', 'Every file inside', () => pickMany({folder: true})),
    row('\ud83d\udcda', 'Your documents', 'Pick ones you added before', openAttach));
  m.hidden = false;
};
// New chat buttons, the burger button that opens the sidebar on a phone, and the sun/moon theme button.
$('newChat').onclick = () => newChat(false); $('newTop').onclick = () => newChat(false);
$('burger').onclick = () => document.body.classList.add('menu-open');
$('scrim').onclick = () => document.body.classList.remove('menu-open');
$('themeBtn').onclick = () => { S.theme = (document.documentElement.dataset.mode === 'light') ? 'dark' : 'light'; try { localStorage.setItem('emvryx_theme', S.theme); } catch (e) {} applyTheme(); };

// ---------------------------------------------------------------- usage line (the numbers ease to their new value)
// tween holds the timer that eases the usage numbers to their new value.
let tween = null;
// pctText: a fraction as a percent for people (99.96 shows as 100%).
function pctText(frac) { const p = frac * 100; return (p >= 99.95 ? '100' : p >= 90 ? p.toFixed(1) : String(Math.round(p))) + '%'; }   // near full, one decimal, so a small message is visible
// renderUsage: draw the usage bar and text, easing from the old value to the new one so it does not jump.
function renderUsage(u, instant) {
  // exempt: the owner has no limits.
  const exempt = u.exempt;
  // How full to show: the smaller of what is left in the tank and in the week.
  const target = exempt ? 1 : Math.min(u.tank.pct, u.week.pct_left) / 100;
  // draw paints one step of the bar and the text.
  const draw = (frac, msgs) => {
    $('barFill').style.width = Math.max(0, Math.min(100, frac * 100)) + '%';
    $('usage').classList.toggle('low', !exempt && frac <= 0.2);
    $('usageBtn').textContent = exempt ? 'Usage: no limit (owner)' : (u.can_send <= 0 ? 'Usage: out for now. Tap for details' : 'Usage: ' + pctText(frac) + ' · about ' + fmt(msgs) + ' messages left');
  };
  // Where to start from: the new value at once, or the value shown last time.
  const from = S.shown == null || instant ? {frac: target, msgs: u.can_send} : S.shown;
  S.shown = {frac: from.frac, msgs: from.msgs}; S.lastUsage = u;
  clearInterval(tween);
  if (instant || (Math.abs(from.frac - target) < 0.001 && from.msgs === u.can_send)) { S.shown = {frac: target, msgs: u.can_send}; draw(target, u.can_send); return; }
  // Move a little closer to the target every 30 milliseconds until it arrives.
  tween = setInterval(() => {
    S.shown.frac += (target - S.shown.frac) * 0.16; S.shown.msgs += (u.can_send - S.shown.msgs) * 0.16;
    if (Math.abs(S.shown.frac - target) < 0.0005) { S.shown = {frac: target, msgs: u.can_send}; clearInterval(tween); }
    draw(S.shown.frac, S.shown.msgs);
  }, 30);
}
// popTokens: the small "minus N credits" that floats up after a reply.
function popTokens(before, after) {
  if (!before || before.exempt || !after) return; const used = before.tank.left - after.tank.left;
  if (used < 1) return; const p = $('pop'); p.className = 'pop'; p.textContent = '\u2212' + fmt(used) + ' credits'; p.style.animation = 'none'; void p.offsetWidth; p.style.animation = ''; setTimeout(() => { p.textContent = ''; p.className = ''; }, 1400);
}
// refreshUsage: ask the server for the newest usage and memory size and redraw.
async function refreshUsage() {
  const q = new URLSearchParams({effort: S.effort, model: S.model}); const r = await api('/api/state?' + q); const st = await r.json();
  S.state.usage = st.usage; S.state.window = st.window; renderUsage(st.usage);
}
// The usage text opens the full usage window.
$('usageBtn').onclick = openUsage;
// untilText: how long until a time, like "5 h 20 min".
function untilText(epochSeconds) {   // "5 h 20 min": how long until a time
  const m = Math.max(0, Math.round((epochSeconds * 1000 - Date.now()) / 60000));
  return m >= 60 ? Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '') : m + ' min';
}
// openUsage: the usage window: tank, week, refill times and messages left by model.
function openUsage() {
  const u = S.lastUsage || S.state.usage; const mk = (t, c) => el('div', {class: 'kv'}, el('span', {}, t), el('span', {}, c));
  const resets = new Date(u.week.resets_at * 1000), full = new Date(u.tank.full_at * 1000);
  const body = [el('h2', {}, 'Usage'), el('div', {style: 'color:var(--muted)'}, 'Status: ' + u.status)];
  if (u.exempt) body.push(el('div', {}, 'You are the owner, so nothing is limited or counted.'));
  else body.push(
    el('b', {}, 'Right now'), el('div', {class: 'big'}, el('div', {style: 'width:' + u.tank.pct + '%'})),
    mk('Left in your tank', fmt(u.tank.left) + ' of ' + fmt(u.tank.cap) + ' tokens'), mk('About', fmt(u.tank.messages_left) + ' messages'),
    mk('Refills', u.tank.mode === 'window' ? 'All at once, ' + u.tank.refill_hours + ' hours after your first message' : fmt(u.tank.refill_per_hour) + ' tokens an hour'),
    mk('Full again', (u.tank.mode === 'window' ? u.tank.left >= u.tank.cap : u.tank.pct >= 99.5) ? 'Already full' : full.toLocaleString([], {weekday: 'short', hour: 'numeric', minute: '2-digit'}) + ' (in ' + untilText(u.tank.full_at) + ')'),
    el('b', {}, 'This week'), el('div', {class: 'big'}, el('div', {style: 'width:' + u.week.pct_left + '%'})),
    mk('Left this week', fmt(u.week.left) + ' of ' + fmt(u.week.cap) + ' tokens'), mk('About', fmt(u.week.messages_left) + ' messages'),
    mk('Resets', resets.toLocaleString([], {weekday: 'long', hour: 'numeric', minute: '2-digit'})),
    el('b', {}, 'Messages left, by model'), ...u.models.map((m) => mk(m.model[0].toUpperCase() + m.model.slice(1), '≈ ' + fmt(m.messages_left))),
    el('div', {style: 'color:var(--muted);font-size:14px'}, 'A normal message is about 500 tokens on Flare. Bigger models and Deep thinking use more. Models running on your own device are never counted.'));
  dialog(body, 'Close');
}
// dialog: a reusable pop-up window with a title area, optional extra content and a close button; clicking outside it closes it.
function dialog(children, closeText, extra) {
  const m = el('div', {class: 'modal', role: 'dialog', 'aria-modal': 'true', onclick: (e) => { if (e.target === m) m.remove(); }},
    el('div', {class: 'dialog'}, ...children, extra || null, el('button', {class: 'btn ghost', onclick: () => m.remove()}, closeText || 'Close')));
  $('dialogs').append(m); return m;
}

// ideas to try on an empty chat (shown only in the modern look: modern.css hides them otherwise)
const ML_IDEAS = [['Explain something', 'Explain how vaccines work like I am twelve.'], ['Plan my day', 'Help me plan a productive day around three things I need to get done.'],
  ['Write for me', 'Write a short, friendly message asking my landlord to fix the heating.'], ['Look it up', 'What is in the news today?']];
// mlIdeas: the idea buttons on an empty chat; each puts its sentence in the message box.
function mlIdeas() {
  return el('div', {class: 'ml-ideas'}, ...ML_IDEAS.map(([name, text]) => el('button', {type: 'button', onclick: () => { $('input').value = text; $('input').dispatchEvent(new Event('input')); $('input').focus(); }}, el('b', {}, name), el('span', {}, text))));
}
