/* Sign in, sign up and the sign-in screen's moving dots. */
// ---------------------------------------------------------------- sign in and sign up
// AUTH holds what this server allows (opts: Google sign-in, passkeys, email codes, sign-ups) and which sign-in screen is showing.
const AUTH = {opts: {}, view: 'signin'};
// An invite link from the website (/?invite=CODE): remember the code, take it out of the address bar, and open Create account with it filled in.
// dashCode: tidy an invite code to lower-case letters and digits (at most 12) with a dash after every four, like abcd-efgh-ijkl.
const dashCode = (v) => { const f = String(v).toLowerCase().replace(/[^0-9a-z]/g, '').slice(0, 12); return f.replace(/(.{4})(?=.)/g, '$1-'); };   // xxxx-xxxx-xxxx, dashes added as you type
// INVITE: the code from a link such as /?invite=CODE, if any; it is also taken out of the address bar so it is not left in history.
let INVITE = ''; try { INVITE = dashCode((new URLSearchParams(location.search).get('invite') || '').trim().slice(0, 60)); if (INVITE) history.replaceState(null, '', '/'); } catch (e) {}
// authCall: send one sign-in request to the server as JSON and give back its answer.
async function authCall(url, body) {
  // Send the request (the cookie goes with it); a network failure becomes a plain message.
  let r; try { r = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}); } catch (e) { throw new Error('Could not reach the server. Check your connection and try again.'); }
  // Read the answer; an empty or unreadable one counts as {}.
  const j = await r.json().catch(() => ({}));
  // If the server refused, throw its message (and what to do next) so the form can show it.
  if (!r.ok) throw new Error((j.message || 'Something went wrong.') + (j.action ? ' ' + j.action : ''));
  return j;
}
// pwScore: how strong a password is, 0 to 4: longer, mixed letters, a digit, a symbol each add a point.
function pwScore(pw) { if (!pw) return 0; let s = 0; if (pw.length >= 10) s++; if (pw.length >= 14) s++; if (/[a-z]/.test(pw) && /[A-Z0-9\W_]/.test(pw)) s++; if (new Set(pw).size >= 8) s++; return pw.length < 10 ? Math.min(s, 1) : Math.max(s, 1); }
// pwBox: a password box with an eye button to show or hide it and, optionally, a strength meter; gives back the input and the box to place.
function pwBox(attrs, withMeter) {
  const input = el('input', Object.assign({type: 'password', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false'}, attrs));
  // The eye button switches the field between hidden and visible.
  const eye = el('button', {type: 'button', class: 'eye', 'aria-label': 'Show password', onclick: () => { const show = input.type === 'password'; input.type = show ? 'text' : 'password'; eye.textContent = show ? 'Hide' : 'Show'; eye.setAttribute('aria-label', show ? 'Hide password' : 'Show password'); }}, 'Show');
  const kids = [el('div', {class: 'pwwrap'}, input, eye)];
  // With the meter: four bars and a word that change as you type.
  if (withMeter) {
    const bars = el('div', {class: 'meter', 'data-s': '0', 'aria-hidden': 'true'}, el('i'), el('i'), el('i'), el('i')), word = el('div', {class: 'meterlabel'}, '10 or more characters. A few words in a row works well.');
    input.addEventListener('input', () => { const s = pwScore(input.value); bars.dataset.s = input.value ? s : 0; word.textContent = !input.value ? '10 or more characters. A few words in a row works well.' : input.value.length < 10 ? 'Keep going: ' + (10 - input.value.length) + ' more characters.' : ['', 'Weak', 'Okay', 'Good', 'Strong'][s]; });
    kids.push(bars, word);
  }
  return {input, node: el('div', {style: 'display:flex;flex-direction:column;gap:6px'}, ...kids)};
}
// b64uToBuf: turn base64url text (what a passkey uses on the wire) into bytes.
const b64uToBuf = (s) => { s = s.replace(/-/g, '+').replace(/_/g, '/'); const bin = atob(s + '='.repeat((4 - s.length % 4) % 4)); return Uint8Array.from(bin, (c) => c.charCodeAt(0)).buffer; };
// bufToB64u: the opposite, bytes to base64url text.
const bufToB64u = (b) => { let s = ''; new Uint8Array(b).forEach((x) => { s += String.fromCharCode(x); }); return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); };
// passkeyOk: does this browser support passkeys?
const passkeyOk = () => !!(window.PublicKeyCredential && navigator.credentials);
// passkeyError: turn a cancelled or timed-out passkey prompt into a friendly message.
const passkeyError = (e) => (e && (e.name === 'NotAllowedError' || e.name === 'AbortError')) ? new Error('The passkey was cancelled or timed out. Try again.') : e;
// passkeyLogin: sign in with a passkey: ask the server for a challenge, let the device sign it, send the proof back.
async function passkeyLogin() {
  try {
    // Step 1: the server gives a one-time challenge.
    const o = await authCall('/api/login/passkey/begin', {});
    // Step 2: the phone or computer asks for fingerprint, face or PIN and signs the challenge.
    const cred = await navigator.credentials.get({publicKey: {challenge: b64uToBuf(o.challenge), rpId: o.rpId, timeout: o.timeout, userVerification: o.userVerification, allowCredentials: []}});
    const r = cred.response;
    // Step 3: send the signed proof to the server.
    await authCall('/api/login/passkey/finish', {credential: {id: cred.id, clientDataJSON: bufToB64u(r.clientDataJSON), authenticatorData: bufToB64u(r.authenticatorData), signature: bufToB64u(r.signature), userHandle: r.userHandle ? bufToB64u(r.userHandle) : ''}});
    // Signed in: carry on.
    authDone({});
  } catch (e) { throw passkeyError(e); }
}
// googleBtn: the "Continue with Google" button, shown only when this server has it set up; it passes the invite code along.
const googleBtn = (getInvite) => AUTH.opts.google ? el('button', {class: 'btn ghost', type: 'button', onclick: () => { const inv = getInvite ? getInvite() : ''; location.href = '/auth/google/start' + (inv ? '?invite=' + encodeURIComponent(inv) : ''); }}, 'Continue with Google') : null;
// authField: a label with an input and an optional small hint.
const authField = (label, input, hint) => el('label', {class: 'field'}, label, input, hint ? el('small', {class: 'hint'}, hint) : null);
// authDone: after a sign-in step: go to the two-step screen if the server asks for it, otherwise load the app.
function authDone(j) { if (j.mfa) return authView('mfa', {ticket: j.ticket}); AUTH.view = 'signin'; return load(); }
// HERO: the three selling points shown beside the sign-in form (icon, title, text).
const HERO = [['lock', 'Private by design', 'Your chats stay on the server you sign in to. Private chats are never saved.'], ['spark', 'Four models, one account', 'Pick the one that fits the question, from quick Flare to deep Apogee.'], ['code', 'More than chat', 'It looks things up, reads your files and pictures, and builds projects with VryxCode.']];
// showLogin: show the sign-in screen: hide the app, ask the server what sign-in methods exist, and show any message from the address.
async function showLogin(note) {
  // Forget the loaded app state, apply the theme, hide the app and show the sign-in area.
  S.state = null; applyTheme(); $('app').hidden = true; $('auth').hidden = false;
  // Ask the server which methods are allowed; if it cannot be reached, assume none.
  try { AUTH.opts = await (await fetch('/api/auth-options')).json(); } catch (e) { AUTH.opts = {}; }
  // GERR: the messages for the reasons Google sign-in can fail.
  const qs = new URLSearchParams(location.search), GERR = {off: 'Google sign-in isn\u2019t set up on this server.', state: 'That Google sign-in expired or didn\u2019t start here. Try again.', denied: 'Google sign-in was cancelled.', token: 'Google didn\u2019t confirm that sign-in. Try again.', unverified: 'An account with that email exists but its email was never verified. Sign in with its password.', closed: 'Sign-ups are closed, and no account uses that Google email.', invite: 'Creating an account needs an invite code. Type it first, then use Google.', banned: 'This account has been turned off.'};
  // Back from Google with an error: show its message and clean the address.
  if (qs.get('gerr')) { note = GERR[qs.get('gerr')] || 'Google sign-in did not work.'; history.replaceState(null, '', '/'); }
  // Back from Google needing a two-step code: go to that screen.
  if (qs.get('mfa')) { const ticket = qs.get('mfa'); history.replaceState(null, '', '/'); return authView('mfa', {ticket}); }
  // A key link was refused: say why.
  if (location.search.includes('notice=keylink')) { note = 'Key links are turned off (a key in an address is easy to leak). Sign in below, or ask the owner for a one-time sign-in link.'; history.replaceState(null, '', '/'); }
  // An invite link opens Create account when sign-ups allow it.
  if (INVITE) { if (['open', 'invite'].includes(AUTH.opts.signup)) AUTH.view = 'signup'; else note = 'Sign-ups are turned off right now, so that invite code can\u2019t be used yet. Ask the owner.'; }
  // Show Create account or Sign in.
  authView(AUTH.view === 'signup' && ['open', 'invite'].includes(AUTH.opts.signup) ? 'signup' : 'signin', {note});
}
// authView: draw one sign-in screen: signin, signup, mfa (two-step code), email (code by email) or key (access key).
function authView(view, ctx) {
  AUTH.view = view; ctx = ctx || {};
  // signups: can people create accounts here?
  const o = AUTH.opts, signups = ['open', 'invite'].includes(o.signup);
  // err is the red message line.
  const err = el('div', {class: 'autherr', role: 'alert'}, ctx.note || '');
  // go makes the main submit button.
  const go = (label) => el('button', {class: 'btn', type: 'submit', style: 'min-height:50px'}, label);
  // form wraps fields and a button; it blocks double submits, runs the action and shows any error in the red line.
  const form = (btn, kids, fn) => el('form', {novalidate: 'novalidate', onsubmit: async (e) => { e.preventDefault(); if (btn.disabled) return; err.textContent = ''; btn.disabled = true; const t = btn.textContent; btn.textContent = 'One moment...'; try { await fn(); } catch (x) { err.textContent = x.message || 'Something went wrong.'; } btn.disabled = false; btn.textContent = t; }}, ...kids, err, btn);
  // back makes a "Back to sign in" link.
  const back = (label, v) => el('button', {class: 'linkbtn', type: 'button', onclick: () => authView(v || 'signin')}, label || 'Back to sign in');
  // tabs makes the Sign in / Create account tabs.
  const tabs = () => el('div', {class: 'tabs2', role: 'tablist'}, el('button', {type: 'button', class: view === 'signin' ? 'on' : '', role: 'tab', onclick: () => authView('signin')}, 'Sign in'), el('button', {type: 'button', class: view === 'signup' ? 'on' : '', role: 'tab', onclick: () => authView('signup')}, 'Create account'));
  // The line about agreeing to the terms and privacy pages.
  const legal = el('div', {class: 'legal'}, 'By continuing you agree to the ', el('a', {href: '/terms', target: '_blank', rel: 'noopener'}, 'Terms'), ' and have read the ', el('a', {href: '/privacy', target: '_blank', rel: 'noopener'}, 'Privacy'), ' page.');
  let body;
  // The password sign-in screen.
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
    // Put the cursor in the first box a moment later.
    setTimeout(() => id.focus(), 50);
  // The Create account screen.
  } else if (view === 'signup') {
    const name = el('input', {type: 'text', autocomplete: 'username', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false', placeholder: 'e.g. sam_k', maxlength: '32', 'aria-label': 'Name'}), email = el('input', {type: 'text', inputmode: 'email', autocomplete: 'email', autocapitalize: 'none', placeholder: 'you@example.com', 'aria-label': 'Email'}),
      pw = pwBox({autocomplete: 'new-password', placeholder: 'Choose a password', 'aria-label': 'Password'}, true), invite = el('input', {type: 'text', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false', placeholder: 'xxxx-xxxx-xxxx', 'aria-label': 'Invite code', value: INVITE, oninput: (e) => { e.target.value = dashCode(e.target.value); }});
    const btn = go('Create account');
    body = [tabs(), el('h2', {}, 'Create your account'), el('p', {class: 'sub'}, o.signup === 'invite' ? 'You need an invite code from the owner.' : 'Free to start. Pick a name and a password.'),
      form(btn, [o.signup === 'invite' ? authField('Invite code', invite) : null, authField('Name', name, 'Letters, numbers, - and _ (3 to 32); a space becomes _. This is how you sign in.'), authField('Email', email, 'Used to sign in with a code and to recover your account.'), authField('Password', pw.node)], async () => {
        const j = await authCall('/api/signup', {name: name.value, email: email.value, password: pw.input.value, invite: invite.value}); INVITE = ''; authDone(j);
      }), googleBtn(() => invite.value.trim()), legal];
    setTimeout(() => (o.signup === 'invite' && !invite.value ? invite : name).focus(), 50);
  // The two-step screen: the 6-digit code from the authenticator app, or a recovery code.
  } else if (view === 'mfa') {
    let rec = false;
    const code = el('input', {type: 'text', class: 'codein', inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: '6', placeholder: '000000', 'aria-label': 'Code from your authenticator app'}), btn = go('Verify and sign in');
    const swap = el('button', {class: 'linkbtn', type: 'button', onclick: () => { rec = !rec; code.value = ''; code.classList.toggle('rec', rec); code.maxLength = rec ? 12 : 6; code.inputMode = rec ? 'text' : 'numeric'; code.placeholder = rec ? 'xxxx-xxxx' : '000000'; swap.textContent = rec ? 'Use my authenticator app instead' : 'I lost my phone: use a recovery code'; code.focus(); }}, 'I lost my phone: use a recovery code');
    body = [el('h2', {}, 'Two-step check'), el('p', {class: 'sub'}, 'Open your authenticator app and type the 6-digit code for Emvryx.'),
      form(btn, [authField('Code', code)], async () => { if (!code.value.trim()) throw new Error('Type the code first.'); authDone(await authCall('/api/login/mfa', {ticket: ctx.ticket, code: code.value})); }), swap, back('Start again')];
    // The code is sent by itself once six digits are typed.
    code.addEventListener('input', () => { if (!rec && /^\d{6}$/.test(code.value)) btn.click(); });
    setTimeout(() => code.focus(), 50);
  // Sign in with a code sent by email: step 1 asks for the address, step 2 for the code.
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
  // The access key screen: paste a key the owner gave you.
  } else {   // key
    const key = pwBox({autocomplete: 'off', placeholder: 'Your access key', 'aria-label': 'Access key'}), btn = go('Continue');
    body = [el('h2', {}, 'Use an access key'), el('p', {class: 'sub'}, 'Paste the key the owner gave you. If you have a password, sign in with that instead.'),
      form(btn, [authField('Access key', key.node)], async () => authDone(await authCall('/api/login', {key: key.input.value.trim()}))), back()];
    setTimeout(() => key.input.focus(), 50);
  }
  // mark: the logo and name.
  const mark = () => el('div', {class: 'mark'}, logo(view === 'signin' ? 36 : 32, false, 'brand'), 'Emvryx');
  // dots: the moving dashes behind the form.
  const dots = el('canvas', {class: 'dots', 'aria-hidden': 'true'});
  // Put the dots, the hero text and the form into the sign-in area.
  $('auth').replaceChildren(
    dots,
    el('div', {class: 'hero'}, mark(), el('h1', {}, 'One family of models. ', el('em', {}, 'Yours to run.')), el('p', {}, 'Emvryx is an AI assistant that runs on its own models: fast for everyday questions, deep for the hard ones.'),
      el('ul', {}, ...HERO.map(([ico, t, d]) => el('li', {}, el('i', {}, icon(ico)), el('div', {}, el('b', {}, t), el('span', {}, d)))))),
    el('div', {class: 'panel'}, el('div', {class: 'card'}, mark(), ...body)));
  // Start the dots animation.
  startDots(dots);
}

/* Sign-in backdrop: a field of small dashes that all turn to face the pointer, bunch away from it and glow near it.
   With no pointer (a phone) a soft invisible cursor wanders so it is never dead. Stops when the screen goes away. */
// startDots: draw and animate the background of dashes on a canvas; host is the screen it belongs to and it stops when that screen is hidden.
function startDots(canvas, host = $('auth')) {
  // If this canvas was animated before, stop that one first.
  if (canvas._dotsStop) canvas._dotsStop();
  // The canvas's 2D drawing tool; nothing to do if there is none.
  const ctx = canvas.getContext && canvas.getContext('2d');
  if (!ctx) return;
  // still: the person asked their device for less motion, so draw one still picture.
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // Size, animation handle, pointer and eased position, and the colour as "r,g,b".
  let w = 0, h = 0, dpr = 1, raf = 0, last = 0, mx = null, my = null, tx = 0, ty = 0, cx = 0, cy = 0, rgb = '245,165,36';
  // The distance between dashes.
  const GAP = 30;
  // size: match the canvas to the window (sharper on high-density screens, capped at 1.5x to stay fast).
  const size = () => { dpr = Math.min(devicePixelRatio || 1, 1.5); w = innerWidth; h = innerHeight; canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); };
  // colour: read the accent colour from the page's style and turn #rrggbb into r,g,b.
  const colour = () => {
    const c = (getComputedStyle(canvas).getPropertyValue('--accent') || '').trim();
    const m = /^#([0-9a-f]{6})$/i.exec(c);
    rgb = m ? [1, 3, 5].map(i => parseInt(m[1].slice(i - 1, i + 1), 16)).join(',') : '245,165,36';
  };
  // move: remember where the pointer or finger is.
  const move = e => { const t = e.touches ? e.touches[0] : e; if (t) { mx = t.clientX; my = t.clientY; } };
  // leave: forget the pointer when it goes away.
  const leave = () => { mx = null; };
  // frame: one animation step.
  const frame = now => {
    raf = requestAnimationFrame(frame);
    // Stop when the screen is hidden.
    if (host.hidden) return stop();
    if (canvas.classList.contains('vx-dots') && !host.classList.contains('home')) return;       // the Code screen's dashes only move on its home
    // dt is the time since the last frame, at most 50 ms.
    const dt = Math.min(50, now - (last || now)); last = now;
    // With no pointer (a phone) a soft invisible cursor wanders on its own.
    if (mx === null) { const t = now / 1000; tx = w * (.5 + .38 * Math.sin(t * .35)); ty = h * (.5 + .34 * Math.sin(t * .27 + 1.3)); }
    else { tx = mx; ty = my; }
    // Ease toward the target; the pointer is followed fast, the wandering cursor slowly.
    const k = 1 - Math.exp(-dt / (mx === null ? 400 : 90));
    cx += (tx - cx) * k; cy += (ty - cy) * k;
    if (Math.abs(cx - drawnX) < .3 && Math.abs(cy - drawnY) < .3) return;     // nothing moved: no need to draw again
    drawnX = cx; drawnY = cy; draw();
  };
  // The last position that was drawn.
  let drawnX = -1, drawnY = -1;
  // draw paints all dashes: the ones far from the pointer in one stroke, the few near it one by one, bigger, brighter and pushed away.
  const draw = () => {      // the dashes far from the pointer all look the same, so they are one stroke; only the few near it are drawn one by one
    ctx.clearRect(0, 0, w, h);
    // R is how far the pointer's effect reaches.
    const R = Math.max(160, Math.min(w, h) * .4);
    ctx.lineCap = 'round'; ctx.beginPath();
    for (let y = GAP / 2; y < h; y += GAP) for (let x = GAP / 2 + ((y / GAP | 0) % 2) * GAP / 2; x < w; x += GAP) {
      const dx = cx - x, dy = cy - y, d = Math.hypot(dx, dy) || 1;
      if (d >= R) { ctx.moveTo(x - dx / d * 2.5, y - dy / d * 2.5); ctx.lineTo(x + dx / d * 2.5, y + dy / d * 2.5); }
    }
    ctx.strokeStyle = `rgba(${rgb},.18)`; ctx.lineWidth = 1.4; ctx.stroke();
    for (let y = GAP / 2; y < h; y += GAP) {
      if (y < cy - R || y > cy + R) continue;
      for (let x = GAP / 2 + ((y / GAP | 0) % 2) * GAP / 2; x < w; x += GAP) {
        const dx = cx - x, dy = cy - y, d = Math.hypot(dx, dy) || 1;
        if (d >= R) continue;
        const near = 1 - d / R, push = near * near * 14, px = x - dx / d * push, py = y - dy / d * push, half = (5 + near * 10) / 2, ux = dx / d * half, uy = dy / d * half;
        ctx.strokeStyle = `rgba(${rgb},${(.18 + near * .8).toFixed(3)})`;
        ctx.lineWidth = 1.4 + near * 1.4;
        ctx.beginPath(); ctx.moveTo(px - ux, py - uy); ctx.lineTo(px + ux, py + uy); ctx.stroke();
      }
    }
  };
  // stop: end the animation and remove every listener.
  const stop = () => { cancelAnimationFrame(raf); removeEventListener('resize', onResize); host.removeEventListener('pointermove', move); host.removeEventListener('touchmove', move); host.removeEventListener('pointerleave', leave); canvas._dotsStop = null; };
  // onResize: size again and redraw.
  const onResize = () => { size(); drawnX = -1; if (still) draw(); };
  // First size and colour, with the pointer in the middle.
  size(); colour(); cx = tx = w / 2; cy = ty = h / 2;
  addEventListener('resize', onResize);
  host.addEventListener('pointermove', move); host.addEventListener('touchmove', move, {passive: true}); host.addEventListener('pointerleave', leave);
  canvas._dotsStop = stop;
  if (still) draw(); else raf = requestAnimationFrame(frame);
}
