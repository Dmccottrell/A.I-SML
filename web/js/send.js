/* Sending a message and streaming the answer. */
// ---------------------------------------------------------------- sending
const clockText = (s) => (s < 1 ? '' : s < 60 ? s + 's' : Math.floor(s / 60) + 'm ' + String(s % 60).padStart(2, '0') + 's');
function thinkingNode(since) {    // since: when the message was sent (performance.now()), so the clock carries on instead of starting again
  const words = S.state.thinking_words, word = el('span', {class: 'word'}, words[0]), secs = el('span', {class: 'secs', 'aria-hidden': 'true'}); let i = 0;
  const node = el('div', {class: 'thinking', 'aria-label': 'Thinking'}, logo(34, true), word, el('span', {class: 'dots'}, ...'...'.split('').map((d) => el('span', {}, d))), secs);
  const t0 = since || performance.now();
  S.thinkTimer = setInterval(() => { i++; word.textContent = words[i % words.length]; word.style.animation = 'none'; void word.offsetWidth; word.style.animation = ''; }, S.state.think_switch_s * 1000);
  S.secTimer = setInterval(() => { secs.textContent = clockText(Math.floor((performance.now() - t0) / 1000)); }, 250);      // the seconds go up by one, never back
  node._stop = () => { clearInterval(S.thinkTimer); clearInterval(S.secTimer); S.thinkTimer = S.secTimer = null; };
  return node;
}
async function send(regen, mode) {
  if (S.busy) return;
  const sentNow = sentIds(), pendingDocs = S.docs.filter((d) => !sentNow.has(d.id));
  let text = regen === true ? '' : input.value.trim();     // a picture or file alone is sent as it is (no made-up question); the model reacts to it
  if (regen !== true && !text && !pendingDocs.length) return;
  if (!S.chatId) { const r = await post('/api/chats', {private: S.private, skill: S.skill, docs: S.docs.map((d) => d.id)}); if (!r.ok) return; S.chatId = (await r.json()).id; remember(); }
  S.busy = true; S.stick = true; S.contNow = S.cont === true; S.cont = false; renderComposer(); closeMenus();
  if (regen === true) { const last = S.messages[S.messages.length - 1]; if (last && last.role === 'assistant') S.messages.pop(); }
  else { S.pending = {id: 'u' + Date.now(), role: 'user', content: text, docs: pendingDocs.map((d) => ({id: d.id, name: d.name, kind: d.kind}))}; S.messages.push(S.pending); input.value = ''; renderAttached(); }
  renderThread(); const before = S.lastUsage;
  S.sentAt = performance.now();
  const think = thinkingNode(S.sentAt); $('thread').append(think); scrollDown(true);
  let aiBubble = null, aiWrap = null, got = '', errCard = null, looked = null, lost = false, finished = false;
  S.abort = new AbortController();
  try {
    const r = await fetch('/api/chats/' + S.chatId + '/send', {method: 'POST', credentials: 'same-origin', signal: S.abort.signal, headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, model: S.model, effort: S.effort, regenerate: regen === true, regen_mode: mode || null, continue: S.contNow === true})});
    if (r.status === 401) { showLogin(); throw new Error('login'); }
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw Object.assign(new Error(j.message || 'Something went wrong.'), {info: j, status: r.status, retry: r.headers.get('Retry-After')}); }
    const reader = r.body.getReader(), dec = new TextDecoder(); let buf = '';
    const handle = (ev, data) => {
      if (ev === 'thinking') {
        S.autoNote = data.auto ? data : null; renderComposer();
      } else if (ev === 'notes') {
        looked = data;
        if (data.retry && aiWrap) {                      // the model said it didn't know, so the web was searched: it answers again
          got = ''; aiBubble.replaceChildren(el('span', {class: 'cursor'}, '▍'));
          const old = aiWrap.querySelector('.note'); if (old) old.remove();
          const line = lookupLine(data); if (line) aiWrap.insertBefore(line, aiBubble);
        }
      } else if (ev === 'memory') {
        const bits = [...(data.saved || []).map((t) => t.replace(/^The user\W?s? ?/i, '').replace(/\.$/, '')), ...(data.forgot ? ['forgot ' + data.forgot + (data.forgot === 1 ? ' thing' : ' things')] : [])];
        if (bits.length) $('thread').append(el('div', {class: 'note', style: 'align-self:flex-start', title: 'Open Memory in the menu to see or change what is kept'}, '\ud83d\udcd6 Memory updated' + (bits.length ? ': ' + bits.join('; ') : '')));
      } else if (ev === 'compacting') {             // the chat is near the model's memory limit: the older messages are being summarized first
        S.compacting = true; renderCtx(null, true);
        if (S.state.features && S.state.features.context_meter) $('thread').insertBefore(el('div', {class: 'note', id: 'compactNote'}, 'Summarizing earlier messages to make room\u2026'), think);
      } else if (ev === 'loading') {   // the model is still starting: the normal thinking words carry on (no extra message)
      } else if (ev === 'piece') {
        if (!aiWrap) { think._stop(); think.remove(); const m = curModel(); aiBubble = el('div', {class: 'bubble'}); const note = S.autoNote ? el('span', {title: S.autoNote.reason}, ' \u00b7 Auto chose ' + S.autoNote.effort[0].toUpperCase() + S.autoNote.effort.slice(1)) : null;
        aiWrap = el('div', {class: 'msg ai'}, el('div', {class: 'meta'}, logo(14, false, m ? m.name : 'brand'), mname(m), note), aiBubble); $('thread').append(aiWrap);
          const line = lookupLine(looked); if (line) aiWrap.insertBefore(line, aiBubble); }
        got += data.t;
        if (!fixesOn()) { aiBubble.replaceChildren(richText(got), el('span', {class: 'cursor'}, '▍')); scrollDown(); }
        else if (!S.paintDue) { S.paintDue = true; requestAnimationFrame(() => { S.paintDue = false; if (aiBubble) { aiBubble.replaceChildren(richText(got), el('span', {class: 'cursor'}, '▍')); scrollDown(); } }); }   // redrawn once a frame, not once a word: a long answer stays smooth
      } else if (ev === 'done') {
        finished = true; S.title = data.title || S.title; S.state.usage = data.usage; renderUsage(data.usage); popTokens(before, data.usage);
        const cn = $('compactNote'); if (cn) cn.remove();
        S.compacting = false; if (data.context) renderCtx(data.context);
        if (data.compacted) $('thread').insertBefore(el('div', {class: 'note'}, 'Earlier messages were summarized to save room'), aiWrap);
        if (data.timing && aiWrap) S.timing = data.timing;                  // the owner's speed line (shown under the reply once the chat is redrawn)
      } else if (ev === 'error') { throw Object.assign(new Error(data.message), {info: data, status: data.http}); }
    };
    for (;;) {
      const {value, done} = await reader.read(); if (done) break; buf += dec.decode(value, {stream: true});
      let i; while ((i = buf.indexOf('\n\n')) >= 0) { const block = buf.slice(0, i); buf = buf.slice(i + 2); let ev = 'message', data = '';
        for (const line of block.split('\n')) { if (line.startsWith('event:')) ev = line.slice(6).trim(); else if (line.startsWith('data:')) data += line.slice(5).trim(); }
        if (data) handle(ev, JSON.parse(data)); }
    }
    if (!finished) lost = true;   // the connection ended without the "done" message: the app was probably switched away from
  } catch (e) {
    if (e.name === 'AbortError') { if (S.resume) lost = true; }
    else if (e.message !== 'login') { if (e instanceof TypeError || /network|fetch|load failed|terminated|connection/i.test(e.message || '')) lost = true; else errCard = errorCard(e); }
  } finally {
    think._stop && think._stop(); think.remove(); S.busy = false; S.compacting = false; S.abort = null; S.resume = false;
  }
  if (lost) return followReply();   // the reply keeps being written on the server: show it when it is ready
  S.pending = null; S.sentAt = null;
    try { const r = await api('/api/chats/' + S.chatId); if (r.ok) { const c = await r.json(); S.messages = c.messages; S.title = c.title; } } catch (e) {}
  renderThread(); if (errCard) { $('thread').append(errCard); scrollDown(true); if (!got && regen !== true) input.value = text; }
  if (S.timing && !errCard) { $('thread').append(timingLine(S.timing)); scrollDown(); } S.timing = null;
  renderComposer(); try { const q = new URLSearchParams({effort: S.effort, model: S.model}); const r = await api('/api/state?' + q); const st = await r.json(); S.state.chats = st.chats; S.state.usage = st.usage; renderChats(); renderUsage(st.usage); } catch (e) {}
}
// Where the reply's time went, for the owner and admins only: "9.8s in all · looking it up 1.2s · loading the model 0s · first word at 6.1s"
function timingLine(t) {
  const sec = (x) => (x < 10 ? x.toFixed(1) : Math.round(x)) + 's';
  const bits = [sec(t.total) + ' in all'];
  if (t.lookup >= 0.3) bits.push('looking it up ' + sec(t.lookup));
  if (t.load >= 0.3) bits.push('loading the model ' + sec(t.load));
  bits.push('first word at ' + sec(t.first_word));
  if (t.thought) bits.push('thought first (Deep)');
  if (t.tries > 1) bits.push('answered twice (searched after "I don\u2019t know")');
  return el('div', {class: 'note', style: 'align-self:flex-start;opacity:.75', title: 'Only you and your admins see this'}, '\u23f1 ' + bits.join(' \u00b7 '));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function followReply() {   // the reply is still being written on the server (the app was closed or switched away from): watch it until it is done
  if (S.following || S.chatId == null) return;
  const id = S.chatId; S.following = true; S.busy = true; S.stick = true; renderComposer();
  const think = thinkingNode(S.sentAt); let lastLen = -1;
  // while the model is still loading the server has not saved the question yet: keep showing it rather than letting it disappear
  const withPending = (msgs, generating) => { const p = S.pending;
    return generating && p && !msgs.some((m) => m.role === 'user' && m.content === p.content && msgs.indexOf(m) >= msgs.length - 2) ? [...msgs, p] : msgs; };
  try {
    for (let i = 0; i < 600; i++) {   // up to about 15 minutes
      let c; try { const r = await api('/api/chats/' + id); if (!r.ok) break; c = await r.json(); } catch (e) { if (e.message === 'login') break; await sleep(2000); continue; }
      if (id !== S.chatId) break;
      const len = JSON.stringify(c.messages).length;
      if (len !== lastLen) { lastLen = len; S.messages = withPending(c.messages, c.generating); S.title = c.title; renderThread(false); if (c.generating) $('thread').append(think); scrollDown(); }
      if (!c.generating || S.stopFollow) break;
      await sleep(1200);
    }
  } finally { think._stop && think._stop(); think.remove(); S.busy = false; S.following = false; S.pending = null; S.sentAt = null; S.stopFollow = false; }
  renderThread(); renderComposer();
  try { const q = new URLSearchParams({effort: S.effort, model: S.model}); const r = await api('/api/state?' + q); const st = await r.json(); S.state.chats = st.chats; S.state.usage = st.usage; renderChats(); renderUsage(st.usage); } catch (e) {}
}
let hiddenAt = 0;
document.addEventListener('visibilitychange', async () => {
  if (document.hidden) { hiddenAt = Date.now(); return; }
  if (!S.state || S.chatId == null || S.following) return;
  const away = Date.now() - hiddenAt; hiddenAt = 0;
  if (S.busy && S.abort && away > 3000) { S.resume = true; S.abort.abort(); return; }   // the phone may have cut the live connection: carry on by watching the saved reply
  if (S.busy) return;
  try { const r = await api('/api/chats/' + S.chatId); if (!r.ok) return; const c = await r.json();
    if (c.generating) return followReply();
    if (JSON.stringify(c.messages) !== JSON.stringify(S.messages)) { S.messages = c.messages; S.title = c.title; renderThread(true); } } catch (e) {}
});
// "Read 2 notes from Wikipedia" / "Searched the web: 1 source": what the model was given before it answered
function lookupLine(info) {
  if (!info || !info.asked) return null;
  const cant = [...(info.unreadable || []).map((x) => 'Couldn\u2019t read ' + x), ...(info.app_errors || []).map((x) => 'Couldn\u2019t read your ' + x.app + ': ' + x.message)];
  if (info.pictures || info.ocr) return el('div', {class: 'note', style: 'align-self:flex-start'}, info.pictures ? 'Looked at ' + info.pictures + (info.pictures === 1 ? ' picture' : ' pictures') + (info.ocr ? ' and read the text in ' + info.ocr + ' more' : '') : 'Read the text in the picture (it can\u2019t see photos yet)');
  const n = (info.saved || 0) + (info.wiki || 0) + (info.web || 0) + (info.live || 0) + ((info.apps || []).length) + cant.length;
  const noKey = info.web_source === 'wikipedia' ? ' Only Wikipedia was searched: no web search key is active (Settings > Live facts > See which sources are on).' : '';
  if (!n) return info.web_tried ? el('div', {class: 'note', style: 'align-self:flex-start'}, 'Searched, but found nothing useful.' + noKey) : null;
  const parts = [];
  if ((info.apps || []).length) parts.push('Looked in your ' + info.apps.join(' and ') + '.');
  if (cant.length) parts.push(cant.join(' '));
  if (info.live) parts.push('Used live data: ' + (info.names || []).join(', '));
  if (info.saved) parts.push('Read ' + info.saved + (info.saved === 1 ? ' saved note' : ' saved notes') + (info.wiki ? ' and ' + info.wiki + ' from Wikipedia' : ''));
  else if (info.wiki) parts.push('Read ' + info.wiki + (info.wiki === 1 ? ' note' : ' notes') + ' from Wikipedia');
  if (info.web) parts.push(((info.wiki || info.saved) ? 'and searched' : 'Searched') + ' the web: ' + info.web + (info.web === 1 ? ' source' : ' sources'));
  return el('div', {class: 'note', style: 'align-self:flex-start', title: info.sources.map((x) => x.title + (x.url ? ' (' + x.url + ')' : '')).join('\n')}, parts.join(' ') + noKey);
}
function errorCard(e) {
  const i = e.info || {}, card = el('div', {class: 'err', role: 'alert'}, el('b', {}, e.message || 'Something went wrong.'));
  if (i.action) card.append(el('div', {}, i.action));
  if (i.code === 'tank_empty' || i.code === 'week_limit') {
    const secs = Number(e.retry || i.retry_after || 0), when = i.code === 'week_limit' && i.resets_at ? 'It resets ' + new Date(i.resets_at * 1000).toLocaleString([], {weekday: 'long', hour: 'numeric', minute: '2-digit'}) + '.'
      : (secs ? 'Try again in about ' + (secs >= 3600 ? Math.ceil(secs / 3600) + ' hours' : Math.max(1, Math.ceil(secs / 60)) + ' minutes') + '.' : '');
    card.append(el('div', {style: 'color:var(--muted)'}, when + ' Models on your own device are not counted.'));
  }
  return card;
}
// Stop: ask the server to stop, and if the page is still waiting a few seconds later (a model that is slow to let go), stop waiting here too
function stop() {
  if (S.chatId == null) return;
  post('/api/chats/' + S.chatId + '/stop').catch(() => {});
  const id = S.chatId;
  setTimeout(() => {
    if (!S.busy || S.chatId !== id) return;
    S.stopFollow = true;                                   // a reply being followed after switching away: stop following it
    if (S.abort) { S.resume = false; S.abort.abort(); }    // the live reply: end it on this side (what was written stays)
  }, 6000);
}
function regenMenu(btn) {
  const wrap = btn.closest('.msg'), old = wrap.querySelector('.regen');
  if (old) { old.remove(); return; }
  const m = el('div', {class: 'regen', role: 'menu'}, el('div', {class: 'head'}, 'HOW SHOULD THE NEW ANSWER DIFFER?'),
    ...S.state.regen_options.map((o) => el('button', {class: 'opt', role: 'menuitem', onclick: () => { m.remove(); send(true, o.id); }},
      el('span', {class: 'grow'}, el('b', {}, o.label), el('small', {}, o.blurb)))));
  wrap.append(m); scrollDown(true);
}
