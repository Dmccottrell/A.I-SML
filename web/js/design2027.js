/* design_2027 (owner only until reviewed): the small bits of the 2027 look that CSS alone cannot do. Everything here does nothing unless body.d27 is set
   (core.js sets it while the flag is on), and the stylesheet is /design2027.css. */
(function () {
  const on = () => document.body.classList.contains('d27');
  const dark = () => document.documentElement.dataset.mode === 'dark';

  // 1. "the model is working": the ambient glow turns warm and the send ring pulses. Chat: S.busy (set while a reply streams); VryxCode: its Stop button is showing.
  const busy = () => (typeof S !== 'undefined' && !!S.busy) || !!($('codeStop') && !$('codeStop').hidden && !$('code').hidden);
  setInterval(() => {
    document.body.classList.toggle('d27-busy', on() && busy());
    // the send ring shows how full the chat's memory is: the number the (hidden) memory ring holds, copied onto it
    const c = $('ctxBtn'), s = $('send');
    if (on() && c && s) s.style.setProperty('--p', c.hidden ? '100' : (c.style.getPropertyValue('--p') || '100'));
  }, 400);

  // 2. the token fade: after each redraw of a streaming reply, the characters that are new since the last redraw are wrapped in <span class="tok">, which fades in over 50 ms.
  //    Text that was already there is left alone, so only the newest words ramp in.
  window.d27Fade = function (bubble) {
    if (!on() || !bubble) return;
    const before = bubble._d27n || 0; let seen = 0;
    // every text node of the reply, except the blinking cursor
    const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT, {acceptNode: (n) => (n.parentNode.closest && n.parentNode.closest('.cursor') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT)});
    const nodes = []; for (let n; (n = walker.nextNode());) nodes.push(n);
    for (const n of nodes) {
      const len = n.nodeValue.length;
      if (seen + len > before) {                              // this node holds some new characters
        const cut = Math.max(0, before - seen);               // split off the new ones (all of it when the node is entirely new)
        const tail = cut ? n.splitText(cut) : n;
        const span = document.createElement('span'); span.className = 'tok';
        tail.parentNode.insertBefore(span, tail); span.append(tail);
      }
      seen += len;
    }
    bubble._d27n = seen;
  };

  // 3. the inference telemetry under a finished reply: tokens a second, the model, the time to the first word. It is measured here, while the reply streams
  //    (tokens are estimated from the length: about four letters each), so it needs nothing from the server.
  let t0 = null, tFirst = 0, lastTel = null;
  let lastBeat = 0, lastTick = 0;
  window.d27Tick = function () {
    if (!on() || typeof S === 'undefined') return;
    const now = performance.now();
    if (!tFirst || now - lastTick > 20000) { t0 = S.sentAt || now; tFirst = now; }   // the first piece of this reply (a long silence means an older reply never finished)
    lastTick = now;
    const send = $('send');                                                       // the send ring beats once per batch of words (at most every 90 ms)
    if (send && now - lastBeat > 90) { lastBeat = now; send.classList.remove('beat'); void send.offsetWidth; send.classList.add('beat'); }
  };
  window.d27Done = function (got) {
    if (!on() || !tFirst || !got) { tFirst = 0; return; }
    const secs = Math.max(0.05, (performance.now() - tFirst) / 1000);
    lastTel = {rate: Math.round(Math.max(1, got.length / 4) / secs), first: Math.round(Math.max(0, tFirst - (t0 || tFirst))), model: typeof mname === 'function' ? mname(curModel()) : ''};
    tFirst = 0;
  };
  let shown = null;                                                              // the newest reply's speed line, kept so a redraw of the chat does not lose it
  const draw = () => {
    if (!on() || !shown || typeof S === 'undefined' || S.chatId !== shown.chat || $('thread').querySelector('.d27-tel')) return;
    const last = S.messages && S.messages[S.messages.length - 1];
    if (!last || last.role !== 'assistant') return;                               // only under the newest reply
    const t = shown;
    $('thread').append(el('div', {class: 'd27-tel', title: 'Measured on this device while the reply streamed. Tokens are estimated from the length of the text.'},
      el('span', {}, '~' + t.rate + ' tok/s'), t.model ? el('b', {}, t.model) : '', el('span', {}, 'first word ' + t.first + ' ms')));
  };
  window.d27Show = function () {                                                // called after the thread is redrawn at the end of a reply
    if (!on() || !lastTel) return;
    shown = Object.assign({chat: S.chatId}, lastTel); lastTel = null; draw();
  };
  if (typeof renderThread === 'function') {                                      // every later redraw puts the line back under the newest reply
    const rt = renderThread;
    window.renderThread = renderThread = function () { const r = rt.apply(this, arguments); draw(); return r; };
  }

  // 4. the sidebar in two bento blocks: chat tools in one, developer tools in the other
  const DEV = ['VryxCode', 'Skills', 'Scheduled tasks'];
  function groups() {
    const l = $('links'); if (!l || !on()) return;
    const loose = [...l.querySelectorAll(':scope > .link')];                    // links that are not in a block yet (new ones are added later by other scripts too)
    if (!loose.length) return;
    const block = (k) => l.querySelector('.d27-block.' + k) || l.appendChild(el('div', {class: 'd27-block ' + k}));
    const chat = block('chat'), code = block('code');
    for (const b of loose) ((DEV.includes((b.querySelector('span') || b).textContent.trim()) ? code : chat)).append(b);
    l.append(chat, code);                                                       // chat tools first
  }

  // 5. the usage line becomes a pill at the top of the chat (the element is moved, so everything that updates it by id keeps working)
  function pill() {
    const u = $('usage'), top = $('themeBtn') && $('themeBtn').parentNode;
    if (!u || !top || !on() || u.classList.contains('d27-pill')) return;
    u.classList.add('d27-pill'); top.prepend(u);
  }

  // 6. cards that grow into the next page: where the browser has the View Transitions API, the tapped session morphs into the page header
  const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  function skeleton() {                                                          // shimmering lines that look like a code block, until the first real events arrive
    const box = $('codeIn'); if (!box || box.children.length) return;
    const sk = el('div', {class: 'd27-skel'}, ...[86, 62, 74, 48, 80].map((w) => el('i', {style: 'width:' + w + '%'})));
    box.append(sk);
    const done = () => { sk.remove(); mo.disconnect(); };
    const mo = new MutationObserver(() => { if ([...box.children].some((c) => c !== sk)) done(); });
    mo.observe(box, {childList: true}); setTimeout(done, 6000);
  }
  if (typeof openSession === 'function') {
    const orig = openSession;
    window.openSession = function (m) {
      const run = () => { const r = orig.call(this, m); if (on()) skeleton(); return r; };
      if (!on() || !document.startViewTransition || reduce()) return run();
      const row = document.querySelector('.vx-prow[data-id="' + (window.CSS && CSS.escape ? CSS.escape(m.id) : m.id) + '"]');
      if (row) row.style.viewTransitionName = 'vx-card';
      const vt = document.startViewTransition(() => {
        if (row) row.style.viewTransitionName = '';
        const r = run(); const h = $('codeTitle'); if (h) h.style.viewTransitionName = 'vx-card'; return r;
      });
      vt.finished.finally(() => { const h = $('codeTitle'); if (h) h.style.viewTransitionName = ''; });
    };
  }

  // keep the composer's "busy" in step right away (the 400 ms timer above also covers VryxCode)
  if (typeof renderComposer === 'function') {
    const rc = renderComposer;
    window.renderComposer = renderComposer = function () { const r = rc.apply(this, arguments); document.body.classList.toggle('d27-busy', on() && busy()); return r; };
  }

  // called by core.js when the look is applied: the OLED status bar, the usage pill, the sidebar blocks
  window.d27Apply = function () {
    if (!on()) return;
    const meta = document.querySelector('meta[name=theme-color]'); if (meta && dark()) meta.content = '#000000';
    pill(); groups();
  };
  const links = document.getElementById('links');
  if (links) new MutationObserver(groups).observe(links, {childList: true});
})();
