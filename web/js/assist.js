/* The bigger assistant features, each behind its own feature flag: Deep Research (chat_research, server side research.py), talking with
   Emvryx hands-free (chat_live_voice) and scheduled tasks (chat_schedule, server side scheduled.py). */
const AS = {research: false, talk: null};

// ---------------------------------------------------------------- chat_research: the Research button and the searches as they happen
function asResearchButton() {
  if ($('asResearch')) return;
  const b = el('button', {class: 'pill plain', id: 'asResearch', 'aria-pressed': 'false', title: 'Deep Research: search the web several ways, read the pages and write a report with sources'}, '🔎 Research');
  b.onclick = () => { AS.research = !AS.research; asResearchDraw(); input.focus(); };
  $('plus').after(b);
}
function asResearchDraw() {
  const b = $('asResearch'); if (!b) return;
  b.classList.toggle('on', AS.research); b.setAttribute('aria-pressed', String(AS.research));
  input.placeholder = AS.research ? 'What should Emvryx research?' : 'Message Emvryx…';
}
function asTakeResearch() {   // send.js: is this message a research request? (once: the button turns itself off)
  const on = AS.research && pfOn('chat_research') && !S.private;
  if (AS.research) { AS.research = false; asResearchDraw(); }
  return on;
}
function asResearchStep(data, think) {   // send.js: one research event ({step, done, of}) under the thinking line
  if (!think || !think.isConnected) return;
  let box = $('asSteps');
  if (!box) { box = el('div', {class: 'as-steps', id: 'asSteps', role: 'status'}); think.after(box); }
  const pct = data.of ? Math.round(100 * data.done / data.of) : 0;
  box.replaceChildren(el('b', {}, 'Researching'), el('div', {class: 'as-bar'}, el('span', {style: 'width:' + pct + '%'})),
    ...[...(box._lines || []), data.step].slice(-6).map((t, i, all) => el('div', {class: i === all.length - 1 ? 'now' : 'done'}, (i === all.length - 1 && data.done < data.of ? '… ' : '✓ ') + t)));
  box._lines = [...(box._lines || []), data.step];
}
function asResearchEnd() { const b = $('asSteps'); if (b) b.remove(); }
const pfOn = (id) => { try { return featureOn(id); } catch (e) { return false; } };

// ---------------------------------------------------------------- chat_live_voice: a spoken conversation, hands-free
const AsRec = window.SpeechRecognition || window.webkitSpeechRecognition;
function asTalkButton() {
  if ($('asTalk') || !AsRec || !('speechSynthesis' in window)) return;
  $('plus').after(el('button', {class: 'pill plain', id: 'asTalk', title: 'Talk with Emvryx: speak, hear the answer, speak again', onclick: asTalk}, '🗣 Talk'));
}
function asTalk() {
  if (AS.talk) return;
  const state = el('div', {class: 'as-talk-state'}, 'Listening…'), heard = el('div', {class: 'as-talk-heard'}), orb = el('div', {class: 'as-orb'});
  const end = el('button', {class: 'btn', onclick: () => stopTalk()}, 'End');
  const ui = el('div', {class: 'as-talk', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Talking with Emvryx'}, orb, state, heard,
    el('small', {style: 'color:var(--muted);max-width:420px;text-align:center'}, 'Your browser turns your voice into words (in Chrome, Google does this). Pause when you are done; Emvryx answers out loud, then listens again.'), end);
  document.body.append(ui);
  const T = AS.talk = {ui, rec: null, alive: true};
  const listen = () => {
    if (!T.alive) return;
    orb.className = 'as-orb listen'; state.textContent = 'Listening…'; heard.textContent = '';
    const rec = T.rec = new AsRec(); rec.lang = navigator.language || 'en-US'; rec.interimResults = true; rec.continuous = false;
    let said = '';
    rec.onresult = (e) => { said = [...e.results].map((r) => r[0].transcript).join(''); heard.textContent = said; };
    rec.onerror = (e) => { if (e.error === 'not-allowed') { state.textContent = 'The microphone is blocked for Emvryx in this browser’s settings.'; T.alive = false; } };
    rec.onend = async () => {
      T.rec = null;
      if (!T.alive) return;
      if (!said.trim()) { setTimeout(listen, 300); return; }
      orb.className = 'as-orb think'; state.textContent = 'Thinking…';
      input.value = said.trim(); await send();
      if (!T.alive) return;
      const last = S.messages[S.messages.length - 1];
      if (!last || last.role !== 'assistant' || !last.content) { setTimeout(listen, 300); return; }
      orb.className = 'as-orb speak'; state.textContent = 'Speaking… (tap the circle to interrupt)'; heard.textContent = '';
      speak(last.content, listen);
    };
    try { rec.start(); } catch (e) { setTimeout(listen, 500); }
  };
  const speak = (text, then) => {
    const plain = String(text).replace(/```[\s\S]*?```/g, ' (there is code in the chat) ').replace(/\[(\d+)\]/g, '').replace(/[#*_`>|]/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    const u = new SpeechSynthesisUtterance(plain); u.lang = navigator.language || 'en-US';
    u.onend = () => then(); u.onerror = () => then();
    speechSynthesis.cancel(); speechSynthesis.speak(u);
  };
  orb.onclick = () => { if (speechSynthesis.speaking) { speechSynthesis.cancel(); } };
  const stopTalk = () => { T.alive = false; if (T.rec) try { T.rec.abort(); } catch (e) { /* already stopped */ } speechSynthesis.cancel(); if (S.busy && S.abort) S.abort.abort(); ui.remove(); AS.talk = null; };
  T.stop = stopTalk;
  ui.addEventListener('keydown', (e) => { if (e.key === 'Escape') stopTalk(); });
  end.focus();
  listen();
}

// ---------------------------------------------------------------- chat_schedule: scheduled tasks
const AS_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
function asScheduleButton() {
  if ($('asSched')) return;
  $('chatSearchBox').after(el('button', {class: 'chip', id: 'asSched', style: 'margin:6px 12px 0', onclick: openSchedules, title: 'Messages Emvryx answers by itself at a set time'}, '⏰ Scheduled tasks'));
}
async function openSchedules() {
  document.body.classList.remove('menu-open');
  let tasks = [];
  try { tasks = (await (await api('/api/schedules')).json()).tasks || []; } catch (e) { return; }
  const list = el('div', {class: 'as-list'});
  const out = el('small', {style: 'color:var(--muted);display:block;min-height:1.2em'});
  const draw = () => list.replaceChildren(...(tasks.length ? tasks.map((t) => el('div', {class: 'as-task' + (t.on ? '' : ' off')},
    el('div', {class: 'grow'}, el('b', {}, t.name), el('small', {}, t.said + (t.on ? '' : ' · off') + (t.last_run ? ' · last ran ' + new Date(t.last_run * 1000).toLocaleString() : '')),
      t.last_error ? el('small', {style: 'color:var(--danger, #e66)'}, t.last_error) : ''),
    t.chat != null ? el('button', {class: 'chip', onclick: () => { m.remove(); openChat(t.chat); }}, 'Open') : '',
    el('button', {class: 'chip', onclick: async () => { const r = await post('/api/schedules/' + t.id + '/run'); if (r.ok) { tasks = (await r.json()).tasks; out.textContent = 'Running now: it appears in its chat in a moment.'; draw(); } }}, 'Run now'),
    el('button', {class: 'chip', onclick: async () => { const r = await post('/api/schedules/' + t.id + '/on', {on: !t.on}); if (r.ok) { tasks = (await r.json()).tasks; draw(); } }}, t.on ? 'Pause' : 'Resume'),
    el('button', {class: 'chip', 'aria-label': 'Delete ' + t.name, onclick: async () => { if (!confirm('Delete “' + t.name + '”?')) return; const r = await post('/api/schedules/' + t.id + '/delete'); if (r.ok) { tasks = (await r.json()).tasks; draw(); } }}, '×')))
    : [el('p', {style: 'color:var(--muted)'}, 'No scheduled tasks yet. For example: every morning at 7:30, “Give me a short summary of today’s news”.')]));
  draw();
  const prompt = el('textarea', {class: 'f', rows: 3, placeholder: 'What should Emvryx do? For example: Give me a short summary of today’s news.', 'aria-label': 'What to do'});
  const name = el('input', {type: 'text', placeholder: 'Name (optional)', 'aria-label': 'Name', style: 'margin-top:8px'});
  const when = el('select', {'aria-label': 'How often', style: 'flex:1 1 160px;width:auto'}, ...[['daily', 'Every day'], ['weekdays', 'Weekdays'], ['weekly', 'On chosen days'], ['once', 'Once']].map(([v, t]) => el('option', {value: v}, t)));
  const at = el('input', {type: 'time', value: '07:30', 'aria-label': 'Time', class: 'as-in'});
  const date = el('input', {type: 'date', 'aria-label': 'Date', hidden: true, class: 'as-in'});
  const days = el('div', {class: 'as-days', hidden: true}, ...AS_DAYS.map((d, i) => el('label', {}, el('input', {type: 'checkbox', value: String(i), checked: i < 5}), d)));
  when.onchange = () => { days.hidden = when.value !== 'weekly'; date.hidden = when.value !== 'once'; };
  const add = el('button', {class: 'btn', onclick: async () => {
    const body = {prompt: prompt.value, name: name.value, when: when.value, time: at.value, date: date.value, tz: -new Date().getTimezoneOffset(),
      days: [...days.querySelectorAll('input:checked')].map((x) => parseInt(x.value, 10)), model: S.model, effort: S.effort === 'auto' ? 'balanced' : S.effort};
    const r = await post('/api/schedules', body); const j = await r.json().catch(() => ({}));
    if (!r.ok) { out.textContent = j.message || 'That did not work.'; return; }
    tasks = j.tasks; prompt.value = ''; name.value = ''; out.textContent = 'Added: ' + j.task.said + '. You get a notification when it is ready (turn on Notifications in Settings).'; draw();
  }}, 'Add');
  const m = dialog([el('h2', {}, 'Scheduled tasks'), el('p', {style: 'color:var(--muted);margin-top:0'}, 'Emvryx answers these by itself at the time you pick, each into a chat of its own. The PC has to be on then. They count on your plan like any message.'),
    list, el('h3', {}, 'New task'), prompt, name, el('div', {class: 'as-row'}, when, at, date), days, add, out]);
}

// ---------------------------------------------------------------- after sign-in and when the switches change
function asSetup() {
  if (!S.state) return;
  if (pfOn('chat_research')) asResearchButton(); else if ($('asResearch')) { $('asResearch').remove(); AS.research = false; }
  if (pfOn('chat_live_voice')) asTalkButton(); else if ($('asTalk')) $('asTalk').remove();
  if (pfOn('chat_schedule')) asScheduleButton(); else if ($('asSched')) $('asSched').remove();
}
setInterval(() => { if (S.state && S.state !== asSetup.seen) { asSetup.seen = S.state; asSetup(); } }, 500);
