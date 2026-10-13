/* Sign in, sign up and the sign-in screen's moving dots. */
// ---------------------------------------------------------------- sign in and sign up
const AUTH = {opts: {}, view: 'signin'};
// An invite link from the website (/?invite=CODE): remember the code, take it out of the address bar, and open Create account with it filled in.
const dashCode = (v) => { const f = String(v).toLowerCase().replace(/[^0-9a-z]/g, '').slice(0, 12); return f.replace(/(.{4})(?=.)/g, '$1-'); };   // xxxx-xxxx-xxxx, dashes added as you type
let INVITE = ''; try { INVITE = dashCode((new URLSearchParams(location.search).get('invite') || '').trim().slice(0, 60)); if (INVITE) history.replaceState(null, '', '/'); } catch (e) {}
async function authCall(url, body) {
  let r; try { r = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}); } catch (e) { throw new Error('Could not reach the server. Check your connection and try again.'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((j.message || 'Something went wrong.') + (j.action ? ' ' + j.action : ''));
  return j;
}
function pwScore(pw) { if (!pw) return 0; let s = 0; if (pw.length >= 10) s++; if (pw.length >= 14) s++; if (/[a-z]/.test(pw) && /[A-Z0-9\W_]/.test(pw)) s++; if (new Set(pw).size >= 8) s++; return pw.length < 10 ? Math.min(s, 1) : Math.max(s, 1); }
function pwBox(attrs, withMeter) {
  const input = el('input', Object.assign({type: 'password', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false'}, attrs));
  const eye = el('button', {type: 'button', class: 'eye', 'aria-label': 'Show password', onclick: () => { const show = input.type === 'password'; input.type = show ? 'text' : 'password'; eye.textContent = show ? 'Hide' : 'Show'; eye.setAttribute('aria-label', show ? 'Hide password' : 'Show password'); }}, 'Show');
  const kids = [el('div', {class: 'pwwrap'}, input, eye)];
  if (withMeter) {
    const bars = el('div', {class: 'meter', 'data-s': '0', 'aria-hidden': 'true'}, el('i'), el('i'), el('i'), el('i')), word = el('div', {class: 'meterlabel'}, '10 or more characters. A few words in a row works well.');
    input.addEventListener('input', () => { const s = pwScore(input.value); bars.dataset.s = input.value ? s : 0; word.textContent = !input.value ? '10 or more characters. A few words in a row works well.' : input.value.length < 10 ? 'Keep going: ' + (10 - input.value.length) + ' more characters.' : ['', 'Weak', 'Okay', 'Good', 'Strong'][s]; });
    kids.push(bars, word);
  }
  return {input, node: el('div', {style: 'display:flex;flex-direction:column;gap:6px'}, ...kids)};
}
const b64uToBuf = (s) => { s = s.replace(/-/g, '+').replace(/_/g, '/'); const bin = atob(s + '='.repeat((4 - s.length % 4) % 4)); return Uint8Array.from(bin, (c) => c.charCodeAt(0)).buffer; };
const bufToB64u = (b) => { let s = ''; new Uint8Array(b).forEach((x) => { s += String.fromCharCode(x); }); return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); };
const passkeyOk = () => !!(window.PublicKeyCredential && navigator.credentials);
const passkeyError = (e) => (e && (e.name === 'NotAllowedError' || e.name === 'AbortError')) ? new Error('The passkey was cancelled or timed out. Try again.') : e;
async function passkeyLogin() {
  try {
    const o = await authCall('/api/login/passkey/begin', {});
    const cred = await navigator.credentials.get({publicKey: {challenge: b64uToBuf(o.challenge), rpId: o.rpId, timeout: o.timeout, userVerification: o.userVerification, allowCredentials: []}});
    const r = cred.response;
    await authCall('/api/login/passkey/finish', {credential: {id: cred.id, clientDataJSON: bufToB64u(r.clientDataJSON), authenticatorData: bufToB64u(r.authenticatorData), signature: bufToB64u(r.signature), userHandle: r.userHandle ? bufToB64u(r.userHandle) : ''}});
    authDone({});
  } catch (e) { throw passkeyError(e); }
}
const googleBtn = (getInvite) => AUTH.opts.google ? el('button', {class: 'btn ghost', type: 'button', onclick: () => { const inv = getInvite ? getInvite() : ''; location.href = '/auth/google/start' + (inv ? '?invite=' + encodeURIComponent(inv) : ''); }}, 'Continue with Google') : null;
const authField = (label, input, hint) => el('label', {class: 'field'}, label, input, hint ? el('small', {class: 'hint'}, hint) : null);
function authDone(j) { if (j.mfa) return authView('mfa', {ticket: j.ticket}); AUTH.view = 'signin'; return load(); }
const HERO = [['lock', 'Private by design', 'Your chats stay on the server you sign in to. Private chats are never saved.'], ['spark', 'Four models, one account', 'Pick the one that fits the question, from quick Flare to deep Apogee.'], ['code', 'More than chat', 'It looks things up, reads your files and pictures, and builds projects with VryxCode.']];
async function showLogin(note) {
  S.state = null; applyTheme(); $('app').hidden = true; $('auth').hidden = false;
  try { AUTH.opts = await (await fetch('/api/auth-options')).json(); } catch (e) { AUTH.opts = {}; }
  const qs = new URLSearchParams(location.search), GERR = {off: 'Google sign-in isn\u2019t set up on this server.', state: 'That Google sign-in expired or didn\u2019t start here. Try again.', denied: 'Google sign-in was cancelled.', token: 'Google didn\u2019t confirm that sign-in. Try again.', unverified: 'An account with that email exists but its email was never verified. Sign in with its password.', closed: 'Sign-ups are closed, and no account uses that Google email.', invite: 'Creating an account needs an invite code. Type it first, then use Google.', banned: 'This account has been turned off.'};
  if (qs.get('gerr')) { note = GERR[qs.get('gerr')] || 'Google sign-in did not work.'; history.replaceState(null, '', '/'); }
  if (qs.get('mfa')) { const ticket = qs.get('mfa'); history.replaceState(null, '', '/'); return authView('mfa', {ticket}); }
  if (location.search.includes('notice=keylink')) { note = 'Key links are turned off (a key in an address is easy to leak). Sign in below, or ask the owner for a one-time sign-in link.'; history.replaceState(null, '', '/'); }
  if (INVITE) { if (['open', 'invite'].includes(AUTH.opts.signup)) AUTH.view = 'signup'; else note = 'Sign-ups are turned off right now, so that invite code can\u2019t be used yet. Ask the owner.'; }
  authView(AUTH.view === 'signup' && ['open', 'invite'].includes(AUTH.opts.signup) ? 'signup' : 'signin', {note});
}
function authView(view, ctx) {
  AUTH.view = view; ctx = ctx || {};
  const o = AUTH.opts, signups = ['open', 'invite'].includes(o.signup);
  const err = el('div', {class: 'autherr', role: 'alert'}, ctx.note || '');
  const go = (label) => el('button', {class: 'btn', type: 'submit', style: 'min-height:50px'}, label);
  const form = (btn, kids, fn) => el('form', {novalidate: 'novalidate', onsubmit: async (e) => { e.preventDefault(); if (btn.disabled) return; err.textContent = ''; btn.disabled = true; const t = btn.textContent; btn.textContent = 'One moment...'; try { await fn(); } catch (x) { err.textContent = x.message || 'Something went wrong.'; } btn.disabled = false; btn.textContent = t; }}, ...kids, err, btn);
  const back = (label, v) => el('button', {class: 'linkbtn', type: 'button', onclick: () => authView(v || 'signin')}, label || 'Back to sign in');
  const tabs = () => el('div', {class: 'tabs2', role: 'tablist'}, el('button', {type: 'button', class: view === 'signin' ? 'on' : '', role: 'tab', onclick: () => authView('signin')}, 'Sign in'), el('button', {type: 'button', class: view === 'signup' ? 'on' : '', role: 'tab', onclick: () => authView('signup')}, 'Create account'));
  const legal = el('div', {class: 'legal'}, 'By continuing you agree to the ', el('a', {href: '/terms', target: '_blank', rel: 'noopener'}, 'Terms'), ' and have read the ', el('a', {href: '/privacy', target: '_blank', rel: 'noopener'}, 'Privacy'), ' page.');
  let body;
  if (view === 'signin') {
    const id = el('input', {type: 'text', autocomplete: 'username', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false', placeholder: 'Name or email', 'aria-label': 'Name or email'}), pw = pwBox({autocomplete: 'current-password', placeholder: 'Your password', 'aria-label': 'Password'});
    const btn = go('Sign in');
    body = [signups ? tabs() : null, el('h2', {}, 'Welcome back'), el('p', {class: 'sub'}, 'Sign in to keep going where you left off.'),
      form(btn, [authField('Name or email', id), authField('Password', pw.node)], async () => {
        if (!id.value.trim() || !pw.input.value) throw new Error('Enter your name (or email) and your password.');
        authDone(await authCall('/api/login/password', {id: id.value, password: pw.input.value}));
      }),
      el('div', {class: 'or'}, 'or'),
      el('div', {class: 'alt'}, o.passkeys && passkeyOk() ? el('button', {class: 'btn ghost', type: 'button', onclick: async () => { err.textContent = ''; try { await passkeyLogin(); } catch (x) { err.textContent = x.message; } }}, 'Sign in with a passkey') : null, googleBtn(), ...(o.email ? [el('button', {class: 'btn ghost', type: 'button', onclick: () => authView('email')}, 'Email me a sign-in code')] : []),
        el('button', {class: 'btn ghost', type: 'button', onclick: () => authView('key')}, 'Use an access key or link')),
      el('div', {class: 'hint'}, o.email ? 'Forgot your password? Email yourself a code, then choose a new password in Settings > Security.' : 'Forgot your password? Ask the owner for a one-time sign-in link, then choose a new one in Settings > Security.'),
      !signups ? el('div', {class: 'authnote'}, 'New here? Accounts are by invitation right now. Ask the owner for a sign-in link.') : null, legal];
    setTimeout(() => id.focus(), 50);
  } else if (view === 'signup') {
    const name = el('input', {type: 'text', autocomplete: 'username', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false', placeholder: 'e.g. sam_k', maxlength: '32', 'aria-label': 'Name'}), email = el('input', {type: 'text', inputmode: 'email', autocomplete: 'email', autocapitalize: 'none', placeholder: 'you@example.com', 'aria-label': 'Email'}),
      pw = pwBox({autocomplete: 'new-password', placeholder: 'Choose a password', 'aria-label': 'Password'}, true), invite = el('input', {type: 'text', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false', placeholder: 'xxxx-xxxx-xxxx', 'aria-label': 'Invite code', value: INVITE, oninput: (e) => { e.target.value = dashCode(e.target.value); }});
    const btn = go('Create account');
    body = [tabs(), el('h2', {}, 'Create your account'), el('p', {class: 'sub'}, o.signup === 'invite' ? 'You need an invite code from the owner.' : 'Free to start. Pick a name and a password.'),
      form(btn, [o.signup === 'invite' ? authField('Invite code', invite) : null, authField('Name', name, 'Letters, numbers, - and _ (3 to 32); a space becomes _. This is how you sign in.'), authField('Email', email, 'Used to sign in with a code and to recover your account.'), authField('Password', pw.node)], async () => {
        const j = await authCall('/api/signup', {name: name.value, email: email.value, password: pw.input.value, invite: invite.value}); INVITE = ''; authDone(j);
      }), googleBtn(() => invite.value.trim()), legal];
    setTimeout(() => (o.signup === 'invite' && !invite.value ? invite : name).focus(), 50);
  } else if (view === 'mfa') {
    let rec = false;
    const code = el('input', {type: 'text', class: 'codein', inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: '6', placeholder: '000000', 'aria-label': 'Code from your authenticator app'}), btn = go('Verify and sign in');
    const swap = el('button', {class: 'linkbtn', type: 'button', onclick: () => { rec = !rec; code.value = ''; code.classList.toggle('rec', rec); code.maxLength = rec ? 12 : 6; code.inputMode = rec ? 'text' : 'numeric'; code.placeholder = rec ? 'xxxx-xxxx' : '000000'; swap.textContent = rec ? 'Use my authenticator app instead' : 'I lost my phone: use a recovery code'; code.focus(); }}, 'I lost my phone: use a recovery code');
    body = [el('h2', {}, 'Two-step check'), el('p', {class: 'sub'}, 'Open your authenticator app and type the 6-digit code for Emvryx.'),
      form(btn, [authField('Code', code)], async () => { if (!code.value.trim()) throw new Error('Type the code first.'); authDone(await authCall('/api/login/mfa', {ticket: ctx.ticket, code: code.value})); }), swap, back('Start again')];
    code.addEventListener('input', () => { if (!rec && /^\d{6}$/.test(code.value)) btn.click(); });
    setTimeout(() => code.focus(), 50);
  } else if (view === 'email') {
    let step = 1;
    const email = el('input', {type: 'text', inputmode: 'email', autocomplete: 'email', autocapitalize: 'none', placeholder: 'you@example.com', 'aria-label': 'Email'}), code = el('input', {type: 'text', class: 'codein', inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: '6', placeholder: '000000', 'aria-label': 'Code from the email'}), btn = go('Email me a code');
    const cf = authField('Code from the email', code, 'It works once, for 10 minutes.'); cf.hidden = true;
    const info = el('div', {class: 'authnote'}); info.hidden = true;
    body = [el('h2', {}, 'Sign in with email'), el('p', {class: 'sub'}, 'We email a 6-digit code to the address on your account.'),
      form(btn, [authField('Email', email), info, cf], async () => {
        if (step === 1) { const j = await authCall('/api/login/email/start', {email: email.value}); step = 2; cf.hidden = false; info.hidden = false; info.textContent = j.message; btn.textContent = 'Sign in'; code.focus(); return; }
        authDone(await authCall('/api/login/email/verify', {email: email.value, code: code.value}));
      }), back()];
    setTimeout(() => email.focus(), 50);
  } else {   // key
    const key = pwBox({autocomplete: 'off', placeholder: 'Your access key', 'aria-label': 'Access key'}), btn = go('Continue');
    body = [el('h2', {}, 'Use an access key'), el('p', {class: 'sub'}, 'Paste the key the owner gave you. If you have a password, sign in with that instead.'),
      form(btn, [authField('Access key', key.node)], async () => authDone(await authCall('/api/login', {key: key.input.value.trim()}))), back()];
    setTimeout(() => key.input.focus(), 50);
  }
  const mark = () => el('div', {class: 'mark'}, logo(view === 'signin' ? 36 : 32, false, 'brand'), 'Emvryx');
  const dots = el('canvas', {class: 'dots', 'aria-hidden': 'true'});
  $('auth').replaceChildren(
    dots,
    el('div', {class: 'hero'}, mark(), el('h1', {}, 'One family of models. ', el('em', {}, 'Yours to run.')), el('p', {}, 'Emvryx is an AI assistant that runs on its own models: fast for everyday questions, deep for the hard ones.'),
      el('ul', {}, ...HERO.map(([ico, t, d]) => el('li', {}, el('i', {}, icon(ico)), el('div', {}, el('b', {}, t), el('span', {}, d)))))),
    el('div', {class: 'panel'}, el('div', {class: 'card'}, mark(), ...body)));
  startDots(dots);
}

/* Sign-in backdrop: a field of small dashes that all turn to face the pointer, bunch away from it and glow near it.
   With no pointer (a phone) a soft invisible cursor wanders so it is never dead. Stops when the screen goes away. */
let dotsStop = null;
function startDots(canvas) {
  if (dotsStop) dotsStop();
  const ctx = canvas.getContext && canvas.getContext('2d');
  if (!ctx) return;
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const host = $('auth');
  let w = 0, h = 0, dpr = 1, raf = 0, last = 0, mx = null, my = null, tx = 0, ty = 0, cx = 0, cy = 0, rgb = '245,165,36';
  const GAP = 30;
  const size = () => { dpr = Math.min(devicePixelRatio || 1, 2); w = innerWidth; h = innerHeight; canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); };
  const colour = () => {
    const c = (getComputedStyle(document.documentElement).getPropertyValue('--accent') || '').trim();
    const m = /^#([0-9a-f]{6})$/i.exec(c);
    rgb = m ? [1, 3, 5].map(i => parseInt(m[1].slice(i - 1, i + 1), 16)).join(',') : '245,165,36';
  };
  const move = e => { const t = e.touches ? e.touches[0] : e; if (t) { mx = t.clientX; my = t.clientY; } };
  const leave = () => { mx = null; };
  const frame = now => {
    raf = requestAnimationFrame(frame);
    if (host.hidden) return stop();
    const dt = Math.min(50, now - (last || now)); last = now;
    if (mx === null) { const t = now / 1000; tx = w * (.5 + .38 * Math.sin(t * .35)); ty = h * (.5 + .34 * Math.sin(t * .27 + 1.3)); }
    else { tx = mx; ty = my; }
    const k = 1 - Math.exp(-dt / (mx === null ? 400 : 90));
    cx += (tx - cx) * k; cy += (ty - cy) * k;
    draw();
  };
  const draw = () => {
    ctx.clearRect(0, 0, w, h);
    const R = Math.max(160, Math.min(w, h) * .4);
    ctx.lineCap = 'round';
    for (let y = GAP / 2; y < h; y += GAP) for (let x = GAP / 2 + ((y / GAP | 0) % 2) * GAP / 2; x < w; x += GAP) {
      const dx = cx - x, dy = cy - y, d = Math.hypot(dx, dy) || 1, near = Math.max(0, 1 - d / R), a = Math.atan2(dy, dx);
      const push = near * near * 14, px = x - dx / d * push, py = y - dy / d * push;
      const len = 5 + near * 10, ux = Math.cos(a) * len / 2, uy = Math.sin(a) * len / 2;
      ctx.strokeStyle = `rgba(${rgb},${(.18 + near * .8).toFixed(3)})`;
      ctx.lineWidth = 1.4 + near * 1.4;
      ctx.beginPath(); ctx.moveTo(px - ux, py - uy); ctx.lineTo(px + ux, py + uy); ctx.stroke();
    }
  };
  const stop = () => { cancelAnimationFrame(raf); removeEventListener('resize', onResize); host.removeEventListener('pointermove', move); host.removeEventListener('touchmove', move); host.removeEventListener('pointerleave', leave); dotsStop = null; };
  const onResize = () => { size(); if (still) draw(); };
  size(); colour(); cx = tx = w / 2; cy = ty = h / 2;
  addEventListener('resize', onResize);
  host.addEventListener('pointermove', move); host.addEventListener('touchmove', move, {passive: true}); host.addEventListener('pointerleave', leave);
  dotsStop = stop;
  if (still) draw(); else raf = requestAnimationFrame(frame);
}
