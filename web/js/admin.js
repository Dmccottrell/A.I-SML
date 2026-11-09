/* The Admin screen for the owner and admins. */
// ---------------------------------------------------------------- Admin screen (owner and admins)
// ADM remembers which tab is open (tab), the Admin window itself (root) and what is typed in the search box (q).
const ADM = {tab: 'previews', root: null, q: ''};
// Close the Admin window: remove every element with the class "adm", forget it, and clear the address hash (the part after # in the web address).
function closeAdmin() { document.querySelectorAll('.adm').forEach((n) => n.remove()); ADM.root = null; viewHash(''); }
// Open the Admin window on one tab (or the last tab used, or Previews the first time).
function openAdmin(tab) {
  // Close any Admin or Settings window that is already open, so there is only ever one.
  closeAdmin(); closeSettings(); ADM.tab = tab || ADM.tab || 'previews'; ADM.q = '';
  // Build the window as a dialog (screen readers announce it as one) and put it into the page's dialogs area, then draw its contents.
  ADM.root = el('div', {class: 'adm', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Admin'}); $('dialogs').append(ADM.root); admRender();
}
// Draw the whole Admin window: the title row, the row of tabs, and the content of the tab that is open.
function admRender() {
  // If the window was closed while we were waiting, stop here.
  const root = ADM.root; if (!root || !root.isConnected) return;
  // Put the tab into the web address (admin/previews, admin/people...) so a reload or a shared link opens the same tab.
  viewHash('admin/' + ADM.tab);
  // The tabs, each as [id, label]. The id picks what to draw below; the label is what the person reads.
  const tabs = [['overview', 'Overview'], ['previews', 'Previews'], ['models', 'Models'], ['apps', 'Apps'], ['pc', 'PC'], ['people', 'People'], ['signups', 'Sign-ups'], ['reports', 'Answer reports'], ['backups', 'Backups'], ['cloud', 'Cloud machine'], ['activity', 'Activity'], ...(S.state && S.state.owner && featureOn('admin_crashes') ? [['crashes', 'Crashes']] : [])];
  // The empty area under the tabs, filled in by the function for the open tab.
  const body = el('div', {class: 'adm-body', id: 'admBody'});
  // Put the top row, the tabs and the body into the window, replacing whatever was there.
  root.replaceChildren(
    el('div', {class: 'adm-top'}, el('h2', {}, 'Admin'), el('button', {class: 'icon', type: 'button', 'aria-label': 'Close admin', onclick: closeAdmin}, icon('x'))),
    el('div', {class: 'adm-tabs', role: 'tablist'}, ...tabs.map(([id, n]) => el('button', {type: 'button', role: 'tab', class: ADM.tab === id ? 'on' : '', 'aria-selected': String(ADM.tab === id), onclick: () => { ADM.tab = id; ADM.q = ''; admRender(); }}, n))),
    body);
  // Which function draws which tab. The older owner pages (sign-ups, activity, overview...) are drawn by admOld, which reuses the page code in this folder.
  const fill = {previews: admPreviews, models: admModels, apps: admApps, pc: admPc, people: admPeople, signups: () => admOld(body, 'a-signups'), activity: () => admOld(body, 'a-log'),
    overview: () => admOld(body, 'a-overview'), reports: () => admOld(body, 'a-feedback'), backups: () => admOld(body, 'a-backups'), cloud: () => admOld(body, 'a-cloud'), crashes: admCrashes}[ADM.tab] || admPreviews;
  // Until the tab has loaded, show "Loading...".
  body.append(el('div', {style: 'color:var(--muted)'}, 'Loading...'));
  // Start drawing the tab; if it fails for any reason, say so plainly instead of leaving a blank screen.
  Promise.resolve(fill(body)).catch(() => body.replaceChildren(el('p', {class: 'lead'}, 'That did not load. Check your connection and try again.')));
}
// Draw one of the older owner pages inside the Admin window.
async function admOld(body, id) { body.replaceChildren(el('div', {id: 'sxAdmin'})); await adminPage(id); }
// admInitials: the one or two capital letters in a person's round picture ("sam smith" becomes SS). A "?" if the name has no letters.
const admInitials = (n) => (String(n).replace(/[^A-Za-z0-9 _.-]/g, '').split(/[ _.-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('') || '?').toUpperCase();
// admAgo: a time in plain words: "just now", "12 min ago", "3 hours ago", or the date for older ones ("never" when there is no time).
const admAgo = (t) => { if (!t) return 'never'; const d = Date.now() / 1000 - t; return d < 90 ? 'just now' : d < 5400 ? Math.round(d / 60) + ' min ago' : d < 129600 ? Math.round(d / 3600) + ' hours ago' : Math.round(d / 86400) + ' days ago'; };
// admDate: a Unix time (seconds since 1970) as a short date such as Nov 3, 2026.
const admDate = (t) => t ? new Date(t * 1000).toLocaleDateString([], {month: 'short', day: 'numeric', year: 'numeric'}) : 'an unknown date';
// admCopy: copy text to the clipboard and say "Copied" on the button for two seconds. If the phone refuses, ask for a long press instead.
async function admCopy(text, btn) { try { await navigator.clipboard.writeText(text); btn.textContent = 'Copied'; } catch (e) { btn.textContent = 'Press and hold to copy'; } setTimeout(() => { btn.textContent = 'Copy'; }, 1800); }

// what kind of release this is: new features add 0.5 to the version (3.0 -> 3.5), bug fixes add 0.1 (3.1 -> 3.2), a big change goes to the next whole
// number; each with the version it becomes and optional notes. [kind] is the one picked at first (what the switch is).
// The three kinds of release a push can be, each as [id, name, what it does to the version number].
const REL_KINDS = [['features', 'New features', 'Adds 0.5 to the version'], ['fixes', 'Bug fixes', 'Adds 0.1 to the version'], ['major', 'Big change', 'The next whole number']];
// nextVersion: the version that will come next, so the dialog can show "v3.0 to v3.5". Features add 0.5, fixes add 0.1, a big change goes to the next whole number.
function nextVersion(v, kind) {
  // Turn the version into tenths (3.1 is 31; a three-part version counts as the next whole number), the same rule as tenths() in app/flags.py.
  const p = String(v).split('.').map(Number), t = (p[1] || 0) <= 9 && !(p[2] || 0) ? p[0] * 10 + (p[1] || 0) : (p[0] + 1) * 10;      // flags.py tenths()
  // Work out the new number in tenths for the chosen kind.
  const n = kind === 'major' ? (Math.floor(t / 10) + 1) * 10 : t + (kind === 'fixes' ? 1 : 5);
  // Back to the "3.5" form.
  return Math.floor(n / 10) + '.' + (n % 10);
}
// releaseDialog: ask what kind of release this is (features, fixes or a big change), show the version it becomes, take optional notes, then call go(kind, notes).
function releaseDialog(title, version, verb, go, first) {
  // The kind that is selected at first.
  let kind = first || 'features';
  // The notes box ("What changed", at most 500 characters).
  const notes = el('textarea', {rows: 3, maxlength: 500, placeholder: 'What changed (optional, shown in What\u2019s new)', style: 'width:100%;border-radius:12px;padding:10px;background:var(--surface2);color:var(--text);border:1px solid var(--line);font:inherit'});
  // The line that shows the version change.
  const line = el('p', {style: 'margin:4px 0 0;font-weight:600'});
  // The column of three choices.
  const opts = el('div', {style: 'display:flex;flex-direction:column;gap:8px;margin:10px 0'});
  // paint redraws the version line and the three choices, marking the selected one.
  const paint = () => {
    line.textContent = 'v' + version + '  \u2192  v' + nextVersion(version, kind);
    opts.replaceChildren(...REL_KINDS.map(([k, name, what]) => el('button', {type: 'button', class: 'opt' + (k === kind ? ' sel' : ''), onclick: () => { kind = k; paint(); }},
      el('span', {class: 'grow'}, el('b', {}, name + '  \u00b7  v' + nextVersion(version, k)), el('small', {}, what)))));
  };
  // Draw once now.
  paint();
  // Build the dialog with its title, question, choices, version line and notes box.
  const m = dialog([el('h2', {}, title), el('div', {style: 'color:var(--muted)'}, 'What kind of release is this?'), opts, line, notes], 'Cancel',
    // The confirm button: close the dialog and hand the chosen kind and the notes to the caller.
    el('button', {class: 'btn', style: 'margin-bottom:8px', onclick: () => { m.remove(); go(kind, notes.value.trim()); }}, verb));
}
// pushDialog: the same idea for a push of one kind where the kind is already fixed (all waiting features, or all waiting fixes).
// a push of one kind (all the waiting new features, or all the waiting fixes) with optional notes
function pushDialog(title, line, verb, go) {
  const notes = el('textarea', {rows: 3, maxlength: 500, placeholder: 'What changed (optional, shown in What\u2019s new)', style: 'width:100%;border-radius:12px;padding:10px;background:var(--surface2);color:var(--text);border:1px solid var(--line);font:inherit'});
  const m = dialog([el('h2', {}, title), el('p', {style: 'margin:4px 0 10px;font-weight:600'}, line), notes], 'Cancel',
    el('button', {class: 'btn', style: 'margin-bottom:8px', onclick: () => { m.remove(); go(notes.value.trim()); }}, verb));
}
// relCat: which release category a switch belongs to: fixes or features.
const relCat = (f) => f.kind === 'fix' ? 'fixes' : 'features';
// admPreviews: the Previews tab. It lists switches that only the owner and admins can see yet, and lets you publish them to everyone or schedule that.
async function admPreviews(body) {
  // Load the switches from the server; "view" is whether we show those in preview or those already published.
  let j = await (await api('/api/admin/flags')).json(); let view = ADM.view || 'preview';
  // save sends a change to the server and redraws; on a refusal it shows the server's message.
  const save = async (b) => { const r = await post('/api/admin/flags', b); const k = await r.json().catch(() => ({})); if (!r.ok) return toast(k.message || 'That did not work.'); Object.assign(j, k); draw(); toast('Saved. It applies at once.'); };
  // Split the switches: waiting (not for everyone and not off), in preview (not for everyone yet) and published (for everyone).
  const ready = j.flags.filter((f) => f.audience !== 'everyone' && f.audience !== 'off'), prev = j.flags.filter((f) => f.audience !== 'everyone'), pub = j.flags.filter((f) => f.audience === 'everyone');
  // previewCard draws one switch that is still in preview, with its schedule and publish buttons.
  const previewCard = (f) => {
    // A date-time picker for scheduling; its earliest value is one minute from now in the person's own time zone.
    const when = sxInput('datetime-local', '', {'aria-label': 'Publish date and time for ' + f.title}); when.min = new Date(Date.now() + 60000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    // The switch's title and tag, then its description.
    return el('div', {class: 'adm-sub'}, el('b', {}, f.title, f.model ? ' ' : '', f.model ? el('span', {class: 'adm-tag'}, 'Part of VryxCode') : null), el('small', {}, f.desc),
      el('small', {style: 'color:var(--accenttext)'}, f.model ? 'Only you and the admins see this. It goes to everyone with the next VryxCode push (Models > VryxCode), or publish it alone here.' : 'Only you see this until you publish it.'),
      f.scheduled ? el('small', {style: 'color:var(--accenttext)'}, 'Goes live for everyone on ' + sxWhen(f.scheduled.at) + ' as a ' + (REL_KIND[f.scheduled.kind] || 'feature').toLowerCase() + ' release (set by ' + f.scheduled.by + ').') : null,
      // The row of actions: pick a time, Schedule, cancel a schedule, Publish now.
      el('div', {class: 'adm-acts'}, when,
        // Schedule: refuse a missing or past time, then ask what kind of release it is and send the schedule to the server.
        sxBtn('Schedule', () => { const t = new Date(when.value).getTime(); if (!when.value || !(t > Date.now())) return toast('Choose a date and time in the future.');
          releaseDialog('Schedule "' + f.title + '"', j.version, 'Schedule it', (kind, notes) => save({id: f.id, schedule_at: t / 1000, kind, notes}), relCat(f)); }),
        f.scheduled ? sxBtn('Cancel schedule', () => save({id: f.id, cancel_schedule: true})) : null,
        // Publish now to everyone, after asking what kind of release it is.
        sxBtn('Publish', () => releaseDialog('Publish "' + f.title + '" to everyone', j.version, 'Publish now', (kind, notes) => save({id: f.id, publish: 'now', kind, notes}), relCat(f)), 'primary')));
  };
  // pubCard draws one switch that is already live for everyone, with a button that pulls it back to admins after a confirmation.
  const pubCard = (f) => el('div', {class: 'adm-sub'}, el('b', {}, f.title, ' ', el('span', {class: 'adm-tag on'}, 'Live')), el('small', {}, f.desc),
    el('small', {}, f.changed ? 'Live since ' + admDate(f.changed.at) + ' (' + f.changed.by + ').' : 'Live for everyone.'),
    el('div', {class: 'adm-acts'}, sxBtn('Pull back to admins', () => { if (confirm('Take "' + f.title + '" away from everyone and keep it for admins?')) save({id: f.id, audience: 'admins'}); }, 'bad')));
  // draw redraws the whole tab from the data we hold.
  const draw = () => {
    // waiting: switches that are not for everyone, not off and not part of VryxCode; appRel: the app's release history without the model releases.
    const waiting = j.flags.filter((f) => f.audience !== 'everyone' && f.audience !== 'off' && !f.model), appRel = j.releases.filter((r) => !String(r.kind || '').startsWith('model'));
    // Split the waiting switches into new features and bug fixes (plus plain fix notes from the server).
    const feats = waiting.filter((f) => f.kind !== 'fix'), fixFlags = waiting.filter((f) => f.kind === 'fix'), fixes = j.fixes || [];
    // The next version numbers; the server sends them, or we work them out.
    const nx = j.next || {features: nextVersion(j.version, 'features'), fixes: nextVersion(j.version, 'fixes')};
    // How many bug fixes are waiting in all.
    const nFix = fixFlags.length + fixes.length;
    // inPrev lists the switches in preview for one group: features, fixes or VryxCode.
    const inPrev = (kind) => prev.filter((f) => kind === 'vryxcode' ? !!f.model : !f.model && (f.kind === 'fix') === (kind === 'fixes'));
    // Replace the tab's content with the cards below.
    body.replaceChildren(
      // First card: Feature previews, with the current version and the two publish buttons.
      el('div', {class: 'adm-card'}, el('h3', {}, '\u{1F9EA} Feature previews'),
        el('p', {}, 'App updates ship to the live app visible only to you and your admins first. New features and bug fixes go out separately: new features add 0.5 to the version (v3.0 \u2192 v3.5), bug fixes add 0.1 (v3.1 \u2192 v3.2). New model versions are published under Models.'),
        el('div', {class: 'adm-row'}, el('span', {style: 'color:var(--muted)'}, 'Current version: v' + j.version)),
        el('div', {class: 'adm-acts', style: 'flex-wrap:wrap'},
          // Publish new features: only if some are waiting, after asking what to write in What's new.
          sxBtn('Publish new features (' + feats.length + ') \u00b7 v' + nx.features, () => { if (!feats.length) return toast('No new features are waiting.');
            pushDialog('Publish ' + feats.length + (feats.length === 1 ? ' new feature' : ' new features') + ' to everyone', 'v' + j.version + '  \u2192  v' + nx.features, 'Publish features', (notes) => save({publish: 'all', kind: 'features', notes})); }, feats.length ? 'primary' : ''),
          // Publish bug fixes, the same way.
          sxBtn('Publish bug fixes (' + nFix + ') \u00b7 v' + nx.fixes, () => { if (!nFix) return toast('No bug fixes are waiting.');
            pushDialog('Publish ' + nFix + (nFix === 1 ? ' bug fix' : ' bug fixes') + ' to everyone', 'v' + j.version + '  \u2192  v' + nx.fixes, 'Publish fixes', (notes) => save({publish: 'all', kind: 'fixes', notes})); }, nFix ? 'primary' : '')),
        // A fold-out list of the plain bug-fix notes that will be published.
        fixes.length ? el('details', {class: 'adm-fixes', style: 'border:1px solid var(--line);border-radius:12px;padding:10px 12px;margin:8px 0'}, el('summary', {style: 'cursor:pointer'}, el('b', {}, 'Fix notes waiting (' + fixes.length + ')'), el('small', {style: 'display:block'}, 'They go out with the next bug-fix release and show under Fixed in What\u2019s new.')),
          ...fixes.map((t) => el('small', {style: 'display:block;margin-top:6px'}, '\u2022 ' + t))) : null,
        el('small', {style: 'color:var(--muted)'}, 'VryxCode\u2019s features and fixes go out with its own pushes: Models > VryxCode.'),
        // The switch between "In preview" and "Published".
        sxSeg([['preview', 'In preview (' + prev.length + ')'], ['published', 'Published (' + pub.length + ')']], view, (v) => { view = ADM.view = v; draw(); }),
        // In the preview view, three groups with a heading and the cards of each group.
        ...(view === 'preview' ? (prev.length ? [['features', '\u2728 New features'], ['fixes', '\u{1F527} Bug fixes'], ['vryxcode', '\u{1F6E0} VryxCode (goes out with its own pushes under Models)']].flatMap(([k, name]) => inPrev(k).length
              ? [el('h3', {style: 'font-size:16px;margin:14px 0 4px'}, name + ' (' + inPrev(k).length + ')'), ...inPrev(k).map(previewCard)] : [])
              : [el('p', {}, 'Nothing is in preview. New features and fixes appear here until you publish them.')])
                              : (pub.length ? pub.map(pubCard) : [el('p', {}, 'Nothing has been published yet.')]))),
      // Second card: the history of every app version published, newest first.
      el('div', {class: 'adm-card'}, el('h3', {}, '\u{1F4CB} App release history'), el('p', {}, 'Every app version published so far, with what went live in each one. Model versions and their updates are under Models.'),
        ...(appRel.length ? appRel.map((r) => el('div', {class: 'adm-sub'}, el('div', {class: 'adm-row'}, el('span', {}, el('b', {}, relTitle(r)), ' ', el('span', {class: 'adm-tag'}, relKind(r))), el('small', {}, admDate(r.at))),
          ...r.items.map((i) => el('small', {}, '\u2022 ' + i.title + ': ' + i.desc)), ...(r.fixes || []).map((t) => el('small', {}, '\u2022 Fixed: ' + t)), r.notes ? el('small', {}, r.notes) : null, el('small', {}, 'Published by ' + r.by))) : [el('p', {}, 'No app releases yet.')])));
  };
  draw();
}


// admin_crashes: the errors found in server.log, the same error counted once, with a button that hands it to VryxCode in the Emvryx project to fix test first.
// admin_crashes: the errors in server.log, the same one counted once; Fix this hands it to VryxCode in the Emvryx project, test first
// admCrashes draws the Crashes tab.
async function admCrashes(body) {
  const j = await (await api('/api/admin/crashes')).json();
  // fix: open VryxCode and prepare a session to fix this one error.
  const fix = async (c) => {
    closeAdmin(); await openCode();
    // Find the VryxCode project that holds the Emvryx code (named a-i-sml or emvryx).
    const mine = (C.info.projects || []).find((p) => /^(a-?i-?sml|emvryx)/i.test(p));
    // If there is none, say how to import it from GitHub first.
    if (!mine) { note('bad', 'Import Emvryx first', 'Fix this works on your Emvryx code as a VryxCode project. Import your A.I-SML repository from GitHub (tap the project name, then Import from GitHub), then press Fix this again.'); return; }
    // Select that project, start a new session and put the error text in the message box, ready to send.
    C.project = mine; renderCodeBar(); newSession(); $('codeTask').value = c.task; $('codeTask').focus();
    note('fin', 'Ready to fix', 'The error is in the message box. Send it to start; when it is done, Save to GitHub makes a pull request. Nothing changes on the running app until you update it.');
  };
  // The card: how many times each error happened, where, when it last happened, and the lines around it.
  body.replaceChildren(el('div', {class: 'adm-card'}, el('h3', {}, '\u{1F6A8} Crashes and errors'),
    el('p', {}, j.log_found ? 'Errors from server.log, newest first. The same error is listed once with how many times it happened.' : 'No server.log was found. It is written when Emvryx is started by the autostart script.'),
    ...(j.crashes.length ? j.crashes.map((c) => el('div', {class: 'adm-sub'},
      el('div', {class: 'adm-row'}, el('b', {}, c.error), el('span', {class: 'adm-tag'}, c.count + (c.count === 1 ? ' time' : ' times'))),
      el('small', {}, c.where + (c.request ? ' \u00b7 ' + c.request : '') + (c.last ? ' \u00b7 last ' + c.last : '')),
      el('details', {}, el('summary', {style: 'cursor:pointer;color:var(--muted);font-size:14px'}, 'The lines around it'), el('pre', {style: 'white-space:pre-wrap;font-size:12px;overflow:auto'}, c.text)),
      el('div', {class: 'adm-acts'}, sxBtn('Fix this', () => fix(c), 'primary')))) : [el('p', {}, j.log_found ? 'No errors. \u2713' : '')])));
}

// accuracy_score: each model's score on the everyday question sheet every time the checks ran, and the change since the run before.
// accuracy_score: each model's score on the everyday question sheet, every time the checks ran, and the change since the run before
// accuracyCard: hist is the saved history per model; live is the models that can be measured now.
function accuracyCard(j, save) {
  const hist = j.accuracy || {}, live = j.models.filter((m) => !m.preview && m.available);
  // One row per model that has a history or can be measured.
  const rows = j.models.filter((m) => (hist[m.id] || []).length || live.includes(m)).map((m) => {
    // The latest run and the one before it.
    const runs = hist[m.id] || [], last = runs[runs.length - 1], prev = runs[runs.length - 2];
    // The change in percent between the two, rounded to one decimal; empty if there is only one run.
    const d = last && prev ? Math.round((last.percent - prev.percent) * 10) / 10 : null;
    // Draw the row: name, latest percent, the change (red if worse), a small bar chart of the last twelve runs, the score per category and a Measure now button.
    return el('div', {class: 'adm-sub'},
      el('div', {class: 'adm-row'}, el('b', {}, m.label), last ? el('span', {class: 'adm-tag' + (last.percent >= 80 ? ' on' : '')}, Math.round(last.percent) + '%') : el('small', {}, 'Not measured yet')),
      last ? el('small', {style: d == null ? '' : d < 0 ? 'color:var(--danger)' : 'color:var(--good, #4ade80)'}, d == null ? 'First run ' + admAgo(last.when) + '.' : (d < 0 ? '\u25bc ' : d > 0 ? '\u25b2 ' : '= ') + Math.abs(d) + ' points since the run before (' + admAgo(last.when) + ')') : null,
      runs.length > 1 ? el('div', {class: 'acc-bars', title: 'The last ' + runs.length + ' runs, oldest first'}, ...runs.slice(-12).map((r) => el('i', {style: 'height:' + Math.max(4, Math.round(r.percent * 0.4)) + 'px', title: Math.round(r.percent) + '%'}))) : null,
      last ? el('small', {}, Object.entries(last.by_category || {}).map(([k, v]) => k + ' ' + v[0] + '/' + v[1]).join(' \u00b7 ')) : null,
      live.includes(m) ? el('div', {class: 'adm-acts'}, sxBtn('Measure now', () => save({id: m.id, run_checks: true}))) : null);
  });
  // The card around the rows, with a short explanation of what the numbers mean.
  return el('div', {class: 'adm-card'}, el('h3', {}, '\u{1F4C8} Accuracy over time'),
    el('p', {}, 'The same everyday questions (facts, sums, following a format, saying \u201cI don\u2019t know\u201d, code, refusing harm) after every update, so you can see whether it got smarter or worse. It takes a few minutes and loads the model.'),
    ...(rows.length ? rows : [el('p', {}, 'No model is on this computer yet.')]));
}

// model_code_test: your own models on tasks made from your recorded VryxCode sessions, run in the sandbox; the tests decide pass or fail.
// model_code_test: your own models on tasks made from your recorded VryxCode sessions, sealed in the sandbox; the tests decide pass or fail
// codeTestCard fills one box with the coding test: how many tasks, the run button and each model's result.
async function codeTestCard(box) {
  // Ask the server for the state; if it cannot be reached, leave the box as it is.
  let j; try { j = await (await api('/api/admin/code-test')).json(); } catch (e) { return; }
  if (!box.isConnected) return;
  // The run button; it says Running while a test is going and is highlighted when there are recordings to test.
  const run = sxBtn(j.state === 'running' ? 'Running\u2026' : 'Run the coding test', async () => {
    const r = await post('/api/admin/code-test', {run: true}); const k = await r.json().catch(() => ({}));
    if (!r.ok) return toast((k.message || 'That did not work.') + (k.action ? ' ' + k.action : ''));
    codeTestCard(box);
  }, j.recorded && j.state !== 'running' ? 'primary' : '');
  // A running test cannot be started twice.
  if (j.state === 'running') run.disabled = true;
  // One row per model, best result first: passed of done, steps per task and what it got wrong.
  const rows = (j.models || []).slice().sort((a, b) => b.passed - a.passed).map((m) => el('div', {class: 'adm-sub'},
    el('div', {class: 'adm-row'}, el('b', {}, m.label), el('span', {class: 'adm-tag' + (m.done && m.passed === m.done ? ' on' : '')}, m.passed + ' of ' + m.done + ' passed')),
    m.error ? el('small', {style: 'color:var(--danger)'}, 'Could not load: ' + m.error) : el('small', {}, m.done ? 'About ' + Math.round(m.steps / m.done) + ' steps and ' + Math.round(m.secs / m.done) + ' s a task' : 'Waiting\u2026'),
    m.fails.length ? el('details', {}, el('summary', {style: 'cursor:pointer;color:var(--muted);font-size:14px'}, 'What it got wrong (' + m.fails.length + ')'),
      ...m.fails.map((f) => el('small', {style: 'display:block;margin-top:6px'}, el('b', {}, f.task), ' \u2192 ' + f.why))) : null));
  // Put the heading, the explanation, the counts and the rows into the box.
  box.replaceChildren(el('h3', {}, '\u{1F9EA} Coding test'),
    el('p', {}, 'Your recorded VryxCode sessions become tasks: the project as it was and the same request. Each of your own models does them, sealed in the sandbox, and the project\u2019s tests decide. Nothing a model writes is kept or used for training.'),
    el('div', {class: 'adm-row'}, el('span', {style: 'color:var(--muted)'}, j.recorded + (j.recorded === 1 ? ' task' : ' tasks') + ' from your recordings' + (j.state === 'running' ? ' \u00b7 ' + j.progress[0] + ' of ' + j.progress[1] + ' done' : j.finished ? ' \u00b7 last run ' + admAgo(j.finished) : '')), run),
    ...rows);
  // While a test is running, look again every five seconds, but only while the box is still on screen.
  if (j.state === 'running') setTimeout(() => { if (box.isConnected) codeTestCard(box); }, 5000);
}

// admModels: the Models tab: model versions in preview, live models and their release history, plus products such as VryxCode that are released like a model.
async function admModels(body) {
  // Load the models; timer is used to look again while safety checks run.
  let j = await (await api('/api/admin/models')).json(); let timer = null;
  // refresh reloads the data and redraws, quietly ignoring a failed try.
  const refresh = async () => { try { j = await (await api('/api/admin/models')).json(); draw(); } catch (e) { /* try again next time */ } };
  // save sends a change and redraws.
  const save = async (b) => { const r = await post('/api/admin/models', b); const k = await r.json().catch(() => ({})); if (!r.ok) return toast(k.message || 'That did not work.'); j = k; draw(); toast('Saved.'); };
  // guardBox draws the safety-check box of a model: running, not run yet, or done with passed or not passed.
  const guardBox = (m) => {
    const g = m.guard || {state: 'none'};
    if (g.state === 'running') return el('div', {class: 'adm-sub'}, el('b', {}, 'Safety checks running… ' + g.progress[0] + ' of ' + g.progress[1]), el('small', {}, 'About 40 everyday questions, one at a time. The model has to be loaded first, so the first one is slow. You can leave this screen.'));
    const run = sxBtn(g.state === 'done' ? 'Run the checks again' : 'Run safety checks', async () => { const r = await post('/api/admin/models', {id: m.id, run_checks: true}); const k = await r.json().catch(() => ({})); if (!r.ok) return toast(k.message || 'That did not work.'); toast('Checks started.'); refresh(); });
    if (g.state !== 'done') return el('div', {class: 'adm-sub'}, el('b', {}, 'Safety checks: not run yet'), el('small', {}, 'A new model must pass about 40 everyday questions (facts, sums, following a format, saying I don’t know, refusing harm) before it can be published.'), el('div', {class: 'adm-acts'}, run));
    return el('div', {class: 'adm-sub'}, el('b', {}, 'Safety checks: ', el('span', {class: 'adm-tag ' + (g.passed ? 'on' : '')}, g.passed ? 'Passed' : 'Not passed'), ' ' + g.summary.passed + ' of ' + g.summary.total + ' (' + g.summary.percent + '%)'),
      el('small', {}, 'Run ' + admAgo(g.when) + (g.by ? ' by ' + g.by : '') + '. ' + Object.entries(g.summary.by_category).map(([k, v]) => k + ' ' + v[0] + '/' + v[1]).join(' · ')),
      ...(g.reasons || []).map((r) => el('small', {style: 'color:var(--danger)'}, '• ' + r)),
      g.failed && g.failed.length ? el('details', {}, el('summary', {style: 'cursor:pointer;color:var(--muted);font-size:14px'}, 'What it got wrong (' + g.failed.length + ')'), ...g.failed.map((f) => el('small', {style: 'display:block;margin-top:6px'}, el('b', {}, f.prompt), ' → ' + (f.error ? 'could not be asked: ' + f.error : (f.reply || '(nothing)'))))) : null,
      el('div', {class: 'adm-acts'}, run));
  };
  // previewCard draws a model in preview: its description, whether its file is on this computer, its safety checks and the schedule and publish buttons.
  const previewCard = (m) => {
    const when = sxInput('datetime-local', '', {'aria-label': 'Publish date and time for ' + m.label}); when.min = new Date(Date.now() + 60000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    // ok: the safety checks ran and passed.
    const ok = m.guard && m.guard.state === 'done' && m.guard.passed;
    return el('div', {class: 'adm-sub'}, el('b', {}, m.label, ' ', el('span', {class: 'adm-tag on'}, 'Preview')), el('small', {}, m.tagline),
      el('small', {style: 'color:var(--accenttext)'}, m.replaces ? 'Only you see this. Publishing makes it the new ' + m.name + ' card and moves ' + m.replaces + ' to Other models (still usable).' : 'Only you see this until you publish it.'),
      m.available ? null : el('small', {style: 'color:var(--danger)'}, 'Its model file is not on this computer yet, so it cannot be published.'),
      guardBox(m),
      m.schedule_failed ? el('small', {style: 'color:var(--danger)'}, 'The scheduled publish did not happen: ' + m.schedule_failed.why) : null,
      m.scheduled ? el('small', {style: 'color:var(--accenttext)'}, 'Goes live for everyone on ' + sxWhen(m.scheduled.at) + ' (set by ' + m.scheduled.by + ') if the checks have passed by then.') : null,
      el('div', {class: 'adm-acts'}, when,
        sxBtn('Schedule', () => { const t = new Date(when.value).getTime(); if (!when.value || !(t > Date.now())) return toast('Choose a date and time in the future.'); save({id: m.id, schedule_at: t / 1000}); }),
        m.scheduled ? sxBtn('Cancel schedule', () => save({id: m.id, cancel_schedule: true})) : null,
        // Publish is offered after a pass; without a pass the only choice is a recorded override.
        ok ? sxBtn('Publish', () => { if (confirm('Publish ' + m.label + ' to everyone now?' + (m.replaces ? ' ' + m.replaces + ' moves to Other models.' : ''))) save({id: m.id, publish: 'now'}); }, m.available ? 'primary' : '')
           : sxBtn('Publish without the checks…', () => { if (confirm('Publish ' + m.label + ' WITHOUT passing the safety checks? This is recorded in the security log. Only do it if you have tested the model yourself.')) save({id: m.id, publish: 'now', skip_checks: true}); }, 'bad')));
  };
  // a product released like a model (VryxCode): its waiting features go out together as its next version
  // productCard draws one such product: waiting features, waiting bug fixes, what was left out because its switch is off, the push buttons and what is already live.
  const productCard = (p) => el('div', {class: 'adm-card'}, el('h3', {}, '\u{1F6E0} ' + p.label),
    el('p', {}, p.desc +  ' Each feature keeps its own switch under Previews (for trying it on you and the admins); its new features and its bug fixes go to everyone in separate pushes: new features add 0.5 to the version (' + p.title + ' ' + p.next.features + '), bug fixes add 0.1 (' + p.title + ' ' + p.next.fixes + ').'),
    el('h3', {style: 'font-size:16px'}, '\u2728 New features waiting (' + p.waiting.length + ')'),
    ...(p.waiting.length ? p.waiting.map((f) => el('div', {class: 'adm-sub'}, el('b', {}, f.title, ' ', el('span', {class: 'adm-tag'}, f.audience === 'owner' ? 'Owner' : 'Admins')), el('small', {}, f.desc)))
                         : [el('p', {}, 'No new features are waiting. New ' + p.title + ' features appear here.')]),
    el('h3', {style: 'font-size:16px'}, '\u{1F527} Bug fixes waiting (' + ((p.waiting_fixes || []).length + (p.fixes || []).length) + ')'),
    ...(p.waiting_fixes || []).map((f) => el('div', {class: 'adm-sub'}, el('b', {}, f.title), el('small', {}, f.desc))),
    ...(p.fixes || []).map((t) => el('small', {style: 'display:block;margin-top:6px'}, '\u2022 ' + t)),
    p.held.length ? el('small', {style: 'color:var(--muted)'}, 'Switched off, so left out: ' + p.held.map((f) => f.title).join(', ')) : null,
    el('div', {class: 'adm-acts', style: 'flex-wrap:wrap'}, ...[['features', 'Push new features', p.waiting.length], ['fixes', 'Push bug fixes', (p.waiting_fixes || []).length + (p.fixes || []).length]].map(([k, verb, n]) =>
      sxBtn(verb + ' \u00b7 ' + p.title + ' ' + p.next[k], () => {
        if (!n) return toast(k === 'fixes' ? 'No bug fixes are waiting.' : 'No new features are waiting.');
        pushDialog(verb + ' to everyone', p.label + '  \u2192  ' + p.title + ' ' + p.next[k], verb, (notes) => save({push_product: p.id, kind: k, notes}));
      }, n ? 'primary' : ''))),
    p.live.length ? el('details', {}, el('summary', {style: 'cursor:pointer;color:var(--muted);font-size:14px'}, 'Live for everyone (' + p.live.length + ')'), ...p.live.map((f) => el('small', {style: 'display:block;margin-top:6px'}, '\u2022 ' + f.title))) : null);
  // draw redraws the Models tab.
  const draw = () => {
    // Stop any earlier timer so there is only one.
    clearTimeout(timer);
    // Split into models in preview and live models.
    const prev = j.models.filter((m) => m.preview), live = j.models.filter((m) => !m.preview);
    // The owner can also see the coding test card when its switch is on.
    const testBox = S.state && S.state.owner && featureOn('model_code_test') ? el('div', {class: 'adm-card', id: 'admCodeTest'}, el('h3', {}, '\u{1F9EA} Coding test'), el('p', {}, 'Loading\u2026')) : null;
    if (testBox) setTimeout(() => codeTestCard(testBox), 0);
    // Fill the tab with the product cards, the accuracy card, the coding test and the model sections.
    body.replaceChildren(
      ...(j.products || []).map(productCard),
      ...(featureOn('accuracy_score') ? [accuracyCard(j, (b) => save(b))] : []),
      ...(testBox ? [testBox] : []),
      el('div', {class: 'adm-card'}, el('h3', {}, '\u{1F9E0} Model versions'),
        el('p', {}, 'A new model version stays in preview (only you and admins see it, marked Preview in the model picker) until you publish it. Before it can be published it must pass the safety checks. Publishing makes it live for everyone and moves the older version of that name to Other models, where it stays usable. Other models keeps the newest ' + j.keep_older + ' older versions of each name.'),
        el('p', {}, 'Rule of thumb: a new version when the training lessons change (Flare 2.5 to 2.6); otherwise it is an update and the version stays (record it below). The app’s own version does not change.'),
        el('h3', {style: 'font-size:16px'}, 'In preview (' + prev.length + ')'),
        ...(prev.length ? prev.map(previewCard) : [el('p', {}, 'No model is waiting. A new build appears here once it is added to the model list with the status “preview”.')])),
      el('div', {class: 'adm-card'}, el('h3', {}, 'Live models'), el('p', {}, 'Made a change that keeps the same version (a new window, new settings, a re-exported file)? Record an update so it shows in the history and in What’s new. What changed is filled in for you.'),
        ...live.map((m) => el('div', {class: 'adm-sub'}, el('div', {class: 'adm-row'}, el('b', {}, m.label, m.live ? ' ' : '', m.live ? el('span', {class: 'adm-tag on'}, 'Published ' + admDate(m.live.at)) : null),
          sxBtn('Record an update', () => { const n = prompt('What changed in ' + m.label + '? (shown to everyone in What’s new; filled in from what was updated, change it if you like)', m.changes || ''); if (n && n.trim()) save({id: m.id, record_update: true, notes: n.trim()}); }, m.changes ? 'primary' : '')), el('small', {}, m.tagline),
          m.changes ? el('small', {style: 'color:var(--accenttext)'}, 'Changed since the last update: ' + m.changes) : null,
          m.guard && m.guard.state !== 'none' ? guardBox(m) : null))),
      el('div', {class: 'adm-card'}, el('h3', {}, 'Model release history'),
        ...(j.releases.length ? j.releases.map((r) => el('div', {class: 'adm-sub'}, el('div', {class: 'adm-row'}, el('span', {}, el('b', {}, relTitle(r)), ' ', el('span', {class: 'adm-tag'}, relKind(r))), el('small', {}, admDate(r.at))),
          ...(r.product ? (r.items || []).map((i) => el('small', {}, '\u2022 ' + i.title)) : []), ...(r.fixes || []).map((t) => el('small', {}, '\u2022 Fixed: ' + t)), r.notes ? el('small', {}, r.notes) : null, el('small', {}, 'By ' + r.by))) : [el('p', {}, 'No model releases yet.')])));
    // If safety checks are running, ask the server again in three seconds.
    if (j.checks_running && body.isConnected) timer = setTimeout(() => { if (body.isConnected) refresh(); }, 3000);
  };
  draw();
}

// admApps: the Apps tab: your own programs (a household finance app...) that ask Emvryx a question through a key and get an answer.
async function admApps(body) {
  // Load the list of apps and the address they send questions to.
  let j = await (await api('/api/admin/apps')).json();
  // call sends a change to the server and redraws or shows its message.
  const call = async (b) => { const r = await post('/api/admin/apps', b); const k = await r.json().catch(() => ({})); if (!r.ok) { toast(k.message || 'That did not work.'); return null; } j.apps = k.apps || j.apps; draw(); return k; };
  // keyDialog shows a new key once, with a ready-made curl command to try it.
  const keyDialog = (title, key, slug) => {
    // The example command: it sends one question to the address with the key as a Bearer header.
    const sample = 'curl -s ' + j.url + ' -H "Authorization: Bearer ' + key + '" -H "Content-Type: application/json" -d \'{"question": "Say hello in five words."}\'';
    const cp = (text, label) => el('button', {class: 'btn ghost', onclick: (e) => { navigator.clipboard && navigator.clipboard.writeText(text).then(() => { e.target.textContent = 'Copied'; }).catch(() => { e.target.textContent = 'Press and hold to copy'; }); }}, label);
    dialog([el('h2', {}, title), el('p', {}, 'This is the only time the key is shown. Copy it now and keep it in the app’s private settings (a server-side secret), never in code that runs in a browser or on a phone.'),
      el('div', {style: 'word-break:break-all;background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:12px;font-family:monospace;font-size:14px;margin:8px 0'}, key), cp(key, 'Copy key'),
      el('p', {style: 'margin-top:14px'}, 'Try it from a computer on this network:'), el('pre', {style: 'white-space:pre-wrap;word-break:break-all;font-size:12px;background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:10px'}, sample), cp(sample, 'Copy test command')], 'Done');
  };
  // draw builds the tab: one card per app (switch, instructions, limits, plan, lookup) and a card to add a new one.
  const draw = () => {
    // The inputs for adding an app: a short name and a display name.
    const slug = sxInput('text', 'a short name, e.g. finance', {'aria-label': 'App name', autocapitalize: 'none'}), disp = sxInput('text', 'Display name, e.g. Household finance', {'aria-label': 'Display name'});
    const ins = el('textarea', {rows: '3', placeholder: 'What this app is for, e.g. You are a calm budgeting helper. Explain the numbers you are given; never do arithmetic yourself.', 'aria-label': 'Instructions', style: 'width:100%;box-sizing:border-box;background:var(--surface2);border:1px solid var(--line);border-radius:12px;color:var(--text);padding:10px;font:inherit'});
    // What is chosen in the add form: the plan and whether it may look things up.
    let plan = 'free', lookup = 'none';
    body.replaceChildren(
      // The first card explains what Apps are and where to send questions.
      el('div', {class: 'adm-card'}, el('h3', {}, '\u{1F50C} Apps'),
        el('p', {}, 'Your own apps (household finance, charting practice...) can ask Emvryx a question and get an answer back. Each app has its own key, plan, instructions and speed limit, and you can switch one off or replace its key without touching the others. Nothing an app asks is saved.'),
        el('p', {style: 'font-size:14px;word-break:break-all'}, 'Address: ' + j.url + '  (send POST with the header Authorization: Bearer <the app’s key>). The app must call it from its own server side (for example a Supabase edge function or a Vercel function), never from browser code. The PC must be on.')),
      // One card per existing app, or a note that there are none yet.
      ...(j.apps.length ? j.apps.map((a) => {
        const text = el('textarea', {rows: '3', 'aria-label': 'Instructions for ' + a.display, style: 'width:100%;box-sizing:border-box;background:var(--surface2);border:1px solid var(--line);border-radius:12px;color:var(--text);padding:10px;font:inherit'}); text.value = a.instructions;
        const rpm = sxInput('number', '', {'aria-label': 'Questions per minute', min: '1', max: '600', inputmode: 'numeric'}); rpm.value = a.rpm; rpm.style.maxWidth = '90px';
        return el('div', {class: 'adm-card'}, el('div', {class: 'adm-row'}, el('div', {}, el('h3', {}, a.display, ' ', el('span', {class: 'adm-tag ' + (a.enabled ? 'on' : '')}, a.enabled ? 'On' : 'Off')), el('small', {style: 'color:var(--muted)'}, a.name + ' · ' + a.plan + ' plan · ' + a.calls + ' questions' + (a.last_used ? ' · last ' + admAgo(a.last_used) : ' · not used yet'))),
          // The switch that turns this app on or off.
          sxSwitch(a.enabled, (v) => call({action: 'update', slug: a.slug, enabled: v}), 'App on or off')),
          // The instructions that are sent along with every question.
          el('b', {style: 'font-size:15px'}, 'Instructions (sent with every question)'), text,
          // Questions allowed per minute, and the Save button.
          el('div', {class: 'adm-acts'}, el('span', {style: 'color:var(--muted);font-size:14px'}, 'Questions per minute'), rpm, sxBtn('Save', async () => { if (await call({action: 'update', slug: a.slug, instructions: text.value, rpm: parseInt(rpm.value, 10) || 20})) toast('Saved.'); })),
          // The plan, which sets its limits and models.
          el('b', {style: 'font-size:15px'}, 'Plan (limits and models)'), sxSeg(j.plans.map((p) => [p, p[0].toUpperCase() + p.slice(1)]), a.plan, (v) => call({action: 'update', slug: a.slug, plan: v})),
          // Whether it may look things up: nothing, Wikipedia or automatic.
          el('b', {style: 'font-size:15px'}, 'May look things up'), el('small', {style: 'color:var(--muted)'}, 'None: nothing leaves this PC. Wikipedia: the local copy only. Auto: the web too (the question text is sent to the search service). Keep None for money and personal data.'),
          sxSeg([['none', 'None'], ['wikipedia', 'Wikipedia'], ['auto', 'Auto']], a.lookup, (v) => call({action: 'update', slug: a.slug, lookup: v})),
          // New key (the old one stops working) and Remove (you must type the app's name).
          el('div', {class: 'adm-acts'}, sxBtn('New key…', async () => { if (confirm('Make a new key for ' + a.display + '? The old key stops working at once, so update the app straight after.')) { const k = await call({action: 'rotate', slug: a.slug}); if (k) keyDialog('New key for ' + a.display, k.key, a.slug); } }),
            sxBtn('Remove…', async () => { const n = prompt('Type the app’s name (' + a.slug + ') to remove it for good:'); if (n === a.slug) { if (await call({action: 'delete', slug: a.slug, confirm: n})) toast('Removed.'); } else if (n !== null) toast('That is not the name. Nothing was removed.'); }, 'bad')));
      }) : [el('div', {class: 'adm-card'}, el('p', {}, 'No apps yet. Add the first one below.'))]),
      // The card to add an app.
      el('div', {class: 'adm-card'}, el('h3', {}, 'Add an app'), authField('Short name (letters, numbers, -)', slug), authField('Display name', disp), el('b', {style: 'font-size:15px'}, 'Instructions'), ins,
        el('b', {style: 'font-size:15px'}, 'Plan'), sxSeg(j.plans.map((p) => [p, p[0].toUpperCase() + p.slice(1)]), 'free', (v) => { plan = v; }),
        el('b', {style: 'font-size:15px'}, 'May look things up'), sxSeg([['none', 'None (recommended)'], ['wikipedia', 'Wikipedia'], ['auto', 'Auto']], 'none', (v) => { lookup = v; }),
        el('div', {}, sxBtn('Make the app and its key', async () => { const k = await call({action: 'create', slug: slug.value.trim().toLowerCase(), display: disp.value.trim(), plan, instructions: ins.value, lookup}); if (k) keyDialog('Key for ' + (disp.value.trim() || slug.value), k.key, slug.value); }, 'primary'))));
  };
  draw();
}

// Admin > PC > Software update (owner only): see what is new on GitHub, then pull it onto this computer and restart
// updateCard builds the Software update card.
function updateCard() {
  // box is the card; out is the changing area under the buttons.
  const box = el('div', {class: 'adm-card'}), out = el('div', {});
  // info holds the last answer from the server.
  let info = null;
  // show puts new content into the changing area, skipping empty items.
  const show = (nodes) => out.replaceChildren(...nodes.filter(Boolean));
  // waitBack: after "Update and restart" the app is away for a few seconds; wait for it to answer again, then reload the page.
  const waitBack = async () => {                                     // the app stops for a few seconds while it restarts: wait for it, then reload
    // Ask /api/status every two seconds for up to three minutes.
    for (let i = 0; i < 90; i++) { await new Promise((r) => setTimeout(r, 2000)); try { const r = await fetch('/api/status', {cache: 'no-store'}); if (r.ok && i > 2) { location.reload(); return; } } catch (e) { /* still restarting */ } }
    show([el('p', {}, 'It is taking longer than usual to come back. Reload this page in a minute.')]);
  };
  // apply asks the server to update, naming the version we saw so a newer one cannot slip in; force means update even while a reply or session is running.
  const apply = async (force) => {
    show([el('p', {}, 'Updating\u2026')]);
    const r = await post('/api/admin/update', {expected: info.latest, force: !!force}), j = await r.json().catch(() => ({}));
    // If the server refused, show why, offer "Update anyway" when it only said busy, and a way to check again.
    if (!r.ok) {
      return show([el('p', {style: 'color:var(--danger)'}, (j.message || 'The update did not work.') + ' ' + (j.action || '')),
        j.code === 'busy' ? el('div', {class: 'adm-acts'}, sxBtn('Update anyway', () => apply(true), 'bad')) : null, el('div', {class: 'adm-acts'}, sxBtn('Check again', check))]);
    }
    // If the app restarts itself, say so and wait for it; otherwise say it must be restarted by hand.
    if (j.restarting) { show([el('p', {}, 'Updated (' + j.changes + (j.changes === 1 ? ' change' : ' changes') + '). Restarting now: this page reloads by itself when Emvryx is back.' + (j.deps_changed ? ' Note: requirements changed, run pip install -r requirements.txt on the PC.' : ''))]); waitBack(); }
    else show([el('p', {}, 'Updated (' + j.changes + (j.changes === 1 ? ' change' : ' changes') + '), but it cannot restart itself here. Restart the app on the PC to use it.' + (j.deps_changed ? ' Also run pip install -r requirements.txt.' : ''))]);
  };
  // the proof that the newest change is the project's own (app/update_verify.py): shown whenever keys are pinned on this computer, and never hidden
  // the proof that the newest change is the project's own (app/update_verify.py): shown whenever keys are pinned on this computer, and never hidden when it failed
  // proof draws a green line when the newest change is proven to be the project's own, or a warning with the reason when it is not.
  const proof = (v) => !v || v.mode === 'off' ? null : el('p', {class: 'update-proof', style: 'font-size:14px;color:' + (v.ok ? '#3fb950' : 'var(--danger)')},
    v.ok ? '\u2713 Proven to be the project\u2019s own: ' + v.checks.join(', ') + '.' : '\u26A0 Not proven (' + v.mode + ' mode): ' + v.reason + '.');
  // check asks GitHub (through the server) what is new and shows the list.
  const check = async () => {
    show([el('p', {}, 'Checking GitHub\u2026')]);
    const r = await api('/api/admin/update'); info = await r.json().catch(() => ({}));
    // Nothing to update (or it cannot): say why and offer to check again.
    if (!info.can_update) return show([el('p', {}, info.reason || 'Nothing to update.'), proof(info.verification), el('div', {class: 'adm-acts'}, sxBtn('Check again', check))]);
    // Show how many changes are waiting, their titles, the proof line, a warning if a reply or session is running, and whether this computer can restart itself.
    show([el('p', {}, el('b', {}, info.behind + (info.behind === 1 ? ' new change' : ' new changes')), ' ready (you have ' + info.current + ', newest is ' + info.latest + '):'),
      el('ul', {style: 'margin:6px 0 10px 18px;padding:0;font-size:14px'}, ...info.incoming.slice(0, 12).map((c) => el('li', {}, c.subject))),
      proof(info.verification),
      info.busy ? el('p', {style: 'color:var(--muted);font-size:14px'}, 'A reply or coding session is running now, so it will ask before updating.') : null,
      info.restart ? null : el('p', {style: 'color:var(--muted);font-size:14px'}, 'This computer cannot restart the app by itself (no "Emvryx App" scheduled task), so you will need to restart it after.'),
      // The Update and restart button asks once more before it does it.
      el('div', {class: 'adm-acts'}, sxBtn('Update and restart', () => { if (confirm('Update Emvryx to the newest version and restart it now? Everyone is disconnected for a few seconds.')) apply(false); }, 'primary'), sxBtn('Check again', check))]);
  };
  // Put the heading, the explanation and the check button in the card.
  box.append(el('h3', {}, '\u2B07\uFE0F Software update'), el('p', {}, 'Pull the newest Emvryx onto this computer and restart it, without touching the PC. Only the owner sees this. It only moves forward and refuses if files here were changed by hand.'),
    el('div', {class: 'adm-acts'}, sxBtn('Check for updates', check)), out);
  return box;
}

// admPc: the PC tab: Gaming mode (rest Emvryx so you can game or train), what is loaded on the graphics card, the software update and when to unload when idle.
async function admPc(body) {
  // Load the settings from the server.
  let j = await (await api('/api/admin/pc')).json();
  // save sends a change and redraws.
  const save = async (b) => { const r = await post('/api/admin/pc', b); const k = await r.json().catch(() => ({})); if (!r.ok) return toast(k.message || 'That did not work.'); j = k; if (S.state) S.state.gaming = j.gaming; renderAll(); draw(); toast('Saved.'); };
  // The idle choices in minutes (0 means never).
  const idle = [[0, 'Never'], [5, '5 min'], [10, '10 min'], [15, '15 min'], [30, '30 min'], [60, '1 hour']];
  // draw redraws the tab.
  const draw = () => {
    // How many whole minutes the model has been idle.
    const mins = Math.floor((j.idle_seconds || 0) / 60);
    body.replaceChildren(
      // Gaming mode card: a switch that frees the graphics card and memory at once.
      el('div', {class: 'adm-card'}, el('h3', {}, '\u{1F3AE} Gaming mode'),
        el('p', {}, 'Frees the graphics card and memory at once, so you can game or train on this PC. While it is on, chats say Emvryx is resting, for everyone. Turn it off and the next message loads the model again (the first reply is slow while it loads).'),
        el('div', {class: 'adm-row'}, el('b', {}, j.gaming ? 'On: Emvryx is resting' : 'Off'), sxSwitch(j.gaming, (v) => save({gaming: v}), 'Gaming mode')),
        el('p', {style: 'font-size:14px'}, 'You can also switch it from the PC itself: create a file called gaming.flag in the .emvryx folder to turn it on, and delete it to turn it off.')),
      // What is on the graphics card right now, with an Unload now button.
      el('div', {class: 'adm-card'}, el('h3', {}, 'On the card right now'),
        j.has_runner ? el('p', {}, j.loaded ? el('span', {}, el('b', {}, j.loaded_label || j.loaded), ' is loaded' + (j.busy ? ' and in use.' : ', idle for ' + (mins ? mins + ' min' : 'under a minute') + '.')) : 'Nothing is loaded. The next message loads a model.')
          : el('p', {}, 'This server is not running models itself (no llama-server), so there is nothing to free here.'),
        j.has_runner && j.loaded ? el('div', {class: 'adm-acts'}, sxBtn('Unload now', () => save({unload: true}))) : null),
      // Only the owner sees the software update card.
      ...(S.state.owner ? [updateCard()] : []),
      // Unload when idle: after this long without use the model is removed from the card; the next message loads it again.
      el('div', {class: 'adm-card'}, el('h3', {}, 'Unload when idle'),
        el('p', {}, 'When nobody has used the model for this long, it is unloaded to free the card. The next message loads it again. Never keeps it loaded until you pick another model.'),
        sxSeg(idle, j.idle_unload_minutes, (v) => save({idle_unload_minutes: v}))));
  };
  draw();
}

// admPeople: the People tab: every account with email, last activity and the buttons an admin may use, plus adding a person.
async function admPeople(body) {
  // Load the accounts; me is who is signed in; granter is whether this person may make admins and change plans.
  const j = await (await api('/api/admin/users')).json(); const users = j.users, me = S.state.user, granter = S.state.granter;
  // out is a small area for messages.
  const out = el('div', {style: 'word-break:break-all;color:var(--muted);font-size:14px'});
  // link makes a one-time sign-in link for a person and shows it in a box with Copy and Share buttons.
  const link = async (u) => {   // shown in a box right away (it used to appear at the bottom of the whole list, out of sight on a phone)
    const r = await post('/api/admin/pairing', {user: u}); const k = await r.json().catch(() => ({}));
    if (!r.ok || !k.pair) return toast(k.message || 'The sign-in link could not be made.');
    const url = location.origin + '/pair/' + k.pair, cp = el('button', {class: 'btn', onclick: (e) => admCopy(url, e.target)}, 'Copy link');
    const share = navigator.share ? el('button', {class: 'btn ghost', onclick: () => navigator.share({title: 'Emvryx sign-in link', url}).catch(() => {})}, 'Share') : null;
    dialog([el('h2', {}, 'Sign-in link for ' + u), el('p', {}, 'Send it privately. It works once, for ' + k.pair_minutes + ' minutes, and signs that device in as ' + u + '.'),
      el('div', {style: 'word-break:break-all;color:var(--muted);font-size:14px;margin-bottom:8px'}, url), cp, share], 'Done');
  };
  // resetPw resets someone's password after a confirmation and shows the reset link (emailed if the person has an email).
  const resetPw = (u) => {
    const run = async () => { const r = await post('/api/admin/reset-password', {user: u.user}); const k = await r.json().catch(() => ({})); if (!r.ok) return toast(k.message || 'That did not work.');
      const cp = el('button', {class: 'btn ghost', onclick: (e) => admCopy(k.link, e.target)}, 'Copy');
      dialog([el('h2', {}, 'Password reset for ' + u.user), el('p', {}, k.emailed ? 'Emailed to ' + u.email + '. ' : 'No email was sent (' + (u.email ? 'email is not set up on this server' : 'this person has no email') + '). '), el('p', {}, 'Send this link privately. It works once, for ' + k.minutes + ' minutes, and lets them sign in and choose a new password. Their old password no longer works and they were signed out everywhere.'),
        el('div', {style: 'word-break:break-all;color:var(--muted);font-size:14px;margin-bottom:8px'}, k.link), cp], 'Done'); admRender(); };
    if (confirm('Reset the password for ' + u.user + '? Their old password stops working and they are signed out everywhere.')) run();
  };
  // list holds the people shown; draw fills it, filtered by the search box.
  const list = el('div', {});
  const draw = () => {
    // Keep people whose name or email contains what was typed.
    const q = ADM.q.toLowerCase(), shown = users.filter((u) => !q || (u.user + ' ' + (u.email || '')).toLowerCase().includes(q));
    list.replaceChildren(...(shown.length ? shown.map((u) => {
      // locked: this person's rights cannot be changed here (the owner, yourself, or an admin when you may not grant).
      const locked = u.owner || u.user === me || ((u.admin || u.unlimited) && !granter);
      // One row per person: round initials, name and tags, email, joined and last active, and the buttons.
      return el('div', {class: 'adm-person'}, el('div', {class: 'adm-av'}, admInitials(u.user)),
        el('div', {}, el('b', {}, u.user, ' ', u.owner ? sxPill('Owner') : null, ' ', u.admin ? sxPill('Admin') : null, ' ', u.unlimited ? sxPill('No limits') : null, ' ', u.banned ? sxPill('Turned off', 'warn') : null),
          el('div', {}, el('small', {}, u.email || 'no email yet', ' '), u.email ? el('button', {class: 'link', type: 'button', style: 'background:none;border:0;color:var(--accenttext);font-weight:600;padding:0', onclick: (e) => admCopy(u.email, e.target)}, 'Copy') : null),
          el('div', {}, el('small', {}, 'Joined ' + admDate(u.created) + ' · last active ' + admAgo(u.last_seen) + ' · ' + u.tier + ' plan' + (u.has_password ? '' : ' · no password') + (u.mfa ? ' · two-step on' : '')))),
        // The buttons for this person; each one asks first when it is risky.
        el('div', {class: 'adm-acts'},
          u.owner || u.user === me ? null : sxBtn('Reset password', () => resetPw(u)),
          sxBtn('Sign-in link', () => link(u.user)),
          u.mfa && !locked ? sxBtn('Reset two-step', async () => { if (confirm('Turn off two-step for ' + u.user + ' and sign them out everywhere?')) { await post('/api/admin/mfa-reset', {user: u.user}); toast('Two-step reset for ' + u.user + '.'); admRender(); } }) : null,
          granter && !u.owner ? sxBtn(u.admin ? 'Remove admin' : 'Make admin', async () => { if (confirm((u.admin ? 'Remove admin rights from ' : 'Make admin: ') + u.user + '?')) { const r = await post('/api/admin/access', {user: u.user, admin: !u.admin}); const k = await r.json().catch(() => ({})); if (!r.ok) return toast(k.message || 'That did not work.'); admRender(); } }) : null,
          granter && !u.owner ? sxBtn('Plan and rights…', () => accessDialog(u, admRender)) : null,
          locked ? null : sxBtn('Delete…', () => removeAccountDialog(u, admRender), 'bad'),
          u.owner || u.admin || u.unlimited ? null : sxBtn(u.banned ? 'Turn on' : 'Turn off', async () => { await post('/api/admin/ban', {user: u.user, banned: !u.banned}); admRender(); }, u.banned ? '' : 'bad')));
    }) : [el('p', {}, 'No one matches that.')]));
  };
  // The search box redraws the list as you type.
  const search = el('input', {type: 'text', class: 'adm-search', placeholder: 'Search by name or email...', 'aria-label': 'Search people', value: ADM.q, oninput: (e) => { ADM.q = e.target.value.trim(); draw(); }});
  // Inputs for adding a person: a name and an optional email.
  const name = sxInput('text', 'Name, e.g. sam', {'aria-label': 'Name'}), mail = sxInput('text', 'Email (optional)', {inputmode: 'email', 'aria-label': 'Email'}); let plan = 'free';
  // Draw the list once now.
  draw();
  // Put the two cards into the tab: the people and adding someone.
  body.replaceChildren(
    el('div', {class: 'adm-card'}, el('h3', {}, 'People (' + users.length + ')'), el('p', {}, 'Everyone with an account: their email, when they joined and were last here. Reset a password, send a sign-in link, change plan or rights, or delete an account. Password resets email the person when email is set up on this server; otherwise you get a link to send yourself.'), search, list, out),
    el('div', {class: 'adm-card'}, el('h3', {}, 'Add a person'), authField('Name', name), authField('Email', mail), sxSeg([['free', 'Free'], ['pro', 'Pro'], ['mega', 'Mega']], 'free', (v) => { plan = v; }),
      el('div', {}, sxBtn('Add and make a sign-in link', async () => { const r = await post('/api/admin/users', {user: name.value.trim(), tier: plan, email: mail.value.trim() || undefined}); const k = await r.json(); if (r.ok) { out.textContent = 'Send this link privately (works once, ' + k.pair_minutes + ' minutes): ' + location.origin + '/pair/' + k.pair + (k.key ? '\nTheir access key (shown once, not stored): ' + k.key : ''); admRender(); } else toast(k.message || 'That did not work.'); }, 'primary'))));
}

// Which Admin tab each older owner page belongs to, so an old link opens the right tab.
const ADM_TAB_OF = {'a-overview': 'overview', 'a-flags': 'previews', 'a-people': 'people', 'a-signups': 'signups', 'a-feedback': 'reports', 'a-backups': 'backups', 'a-cloud': 'cloud', 'a-log': 'activity'};
// adminPage draws one of the older owner pages (overview, sign-ups, reports, backups, cloud...) into its place.
async function adminPage(id) {
  // If the Admin window is not open yet, open it on the right tab instead.
  if (!$('sxAdmin') && ADM_TAB_OF[id]) { openAdmin(ADM_TAB_OF[id]); return; }   // the owner pages all live on the Admin screen now
  // host is the place where the page is drawn.
  const host = $('sxAdmin'); if (!host) return;
  try {
    // Overview: a "safe to share" checklist, counts of people and of the last hour, and controls such as pause, sharing links, the weekly summary and a test email.
    if (id === 'a-overview') {
      const o = await (await api('/api/admin/overview')).json(), h = o.health, ok = o.checklist.filter((c) => c.ok).length;
      host.replaceChildren(
        el('div', {class: 'sx-sec', style: 'margin-top:0'}, 'Safe to share? ' + ok + ' of ' + o.checklist.length),
        el('div', {class: 'sx-card'}, ...o.checklist.map((c) => el('div', {class: 'check'}, el('span', {class: 'mk ' + (c.ok ? 'ok' : 'no')}, c.ok ? '✓' : '!'), el('div', {}, el('b', {}, c.title), c.ok ? null : el('small', {}, c.how), !c.ok && ['password', 'mfa', 'email'].includes(c.id) ? sxBtn('Fix this', () => { SX.page = c.id === 'email' ? 'account' : 'security'; sxRender(true); }) : null)))),
        el('div', {class: 'sx-sec'}, 'People'), el('div', {class: 'stats'}, ...[[o.people, 'people'], [o.banned, 'turned off'], ...Object.entries(o.plans).map(([k, v]) => [v, k + ' plan'])].map(([n, l]) => el('div', {class: 'stat'}, el('b', {}, n), el('span', {}, l)))),
        el('div', {class: 'sx-sec'}, 'Last hour'), el('div', {class: 'stats'}, ...[[h.last_hour.sign_ins, 'sign-ins'], [h.last_hour.failed_tries, 'wrong tries'], [h.last_hour.lockouts, 'lockouts'], [h.devices_signed_in, 'devices signed in'], [h.server_errors, 'server errors'], [h.uptime_minutes + 'm', 'uptime']].map(([n, l]) => el('div', {class: 'stat'}, el('b', {}, n), el('span', {}, l)))),
        el('div', {class: 'sx-sec'}, 'Controls'), sxCard([{title: 'Pause everyone', desc: 'Stops chats for everyone except you. Restart the server to clear it, or press Resume.', ctl: el('div', {style: 'display:flex;gap:8px'}, sxBtn('Pause', async () => { await post('/api/admin/pause', {paused: true}); toast('Paused for everyone but you.'); }, 'bad'), sxBtn('Resume', async () => { await post('/api/admin/pause', {paused: false}); toast('Resumed.'); }))},
          {title: 'Let people share chats by link', desc: 'Each link shows a read-only copy of one chat to anyone who has it, expires (1 to 30 days) and can be cancelled. Turning this off stops every link at once.', ctl: sxSwitch(o.sharing, async (v) => { await post('/api/admin/sharing', {on: v}); }, 'Let people share chats by link')},
          {title: 'Weekly summary', desc: 'Once a week: people, sign-ins, wrong tries, messages by model, reports to read, errors and how old your newest backup is. Counts only, no chats are read. Sent to your owner email (if mail is set up) and as a phone alert (if alerts are set up).', ctl: el('div', {style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap'}, sxSwitch(o.weekly_summary, async (v) => { await post('/api/admin/summary-settings', {on: v}); }, 'Weekly summary'),
            sxBtn('Preview', async () => { const r = await post('/api/admin/summary', {}); const j = await r.json(); dialog([el('h2', {}, 'This week'), el('pre', {style: 'white-space:pre-wrap;margin:0;font:inherit'}, j.text)], 'Close'); }),
            sxBtn('Send now', async () => { const r = await post('/api/admin/summary', {send: true}); const j = await r.json(); toast(j.emailed ? 'Emailed to you.' : j.alerted ? 'Sent as a phone alert.' : 'Nothing was sent: set up mail or alerts first.'); }))},
          {title: 'Send a test email', desc: 'Sends a message to your owner email, so you know sign-in codes will arrive. Needs EMVRYX_SMTP_* in .emvryx\\keys.env.', ctl: sxBtn('Send test', async () => { const r = await post('/api/admin/mail-test'); const j = await r.json(); toast(r.ok ? 'Sent to ' + j.to : (j.message + ' ' + (j.action || ''))); })},
          {title: 'Live sources and keys', desc: 'Which lookups work and which keys are missing.', ctl: sxBtn('See sources', openSources)}]));
    // Sign-ups: who can sign up and the invite codes.
    } else if (id === 'a-signups') {
      const o = await (await api('/api/admin/overview')).json(), out = el('div', {class: 'srow', style: 'display:none'});
      // What the invite form has picked: the plan and how many uses.
      let tier = 'free', uses = 1;
      const desc = {closed: 'Nobody can make an account. You add people yourself.', invite: 'People need a code from you. Good for a private beta.', open: 'Anyone who finds the page can make a free account. Only do this when you are ready for strangers and the GPU cost.'};
      const modeNote = el('small', {style: 'color:var(--muted)'}, desc[o.signup_mode]);
      const made = el('div', {});
      host.replaceChildren(
        el('div', {class: 'sx-card'}, el('div', {class: 'srow stack'}, el('div', {class: 'stxt'}, el('b', {}, 'Who can sign up'), modeNote), sxSeg([['closed', 'Closed'], ['invite', 'Invite only'], ['open', 'Open']], o.signup_mode, async (v) => { await post('/api/admin/signups', {mode: v}); modeNote.textContent = desc[v]; }))),
        el('div', {class: 'sx-sec'}, 'Make an invite code'),
        el('div', {class: 'sx-card'}, el('div', {class: 'srow stack'}, el('div', {class: 'stxt'}, el('b', {}, 'Plan it gives'), el('small', {}, 'People who use it start on this plan.')), sxSeg([['free', 'Free'], ['pro', 'Pro'], ['mega', 'Mega']], 'free', (v) => { tier = v; }),
          el('div', {class: 'stxt'}, el('b', {}, 'Uses')), sxSeg([[1, 'One person'], [5, 'Five people'], [25, 'Twenty-five']], 1, (v) => { uses = Number(v); }),
          // Make a code: ask the server and show the new code once, valid 14 days.
          el('div', {}, sxBtn('Make a code', async () => { const r = await post('/api/admin/invites', {tier, uses, days: 14}); const k = await r.json(); if (!r.ok) return toast(k.message);
            made.replaceChildren(el('div', {class: 'authnote'}, 'Shown once. Valid 14 days. Send it privately.'), el('div', {class: 'setupkey'}, k.code), el('div', {style: 'display:flex;gap:8px;flex-wrap:wrap'}, sxBtn('Copy code', async (e) => { try { await navigator.clipboard.writeText(k.code); e.target.textContent = 'Copied'; } catch (x) {} }), sxBtn('Copy invite link', async (e) => { try { await navigator.clipboard.writeText(location.origin + '/?invite=' + k.code); e.target.textContent = 'Copied'; } catch (x) {} })), el('small', {style: 'color:var(--muted)'}, 'The link opens Create account with the code already filled in. People can also type the code on the Emvryx website home page.')); }, 'primary'), made))),
        el('div', {class: 'sx-sec'}, 'Active codes (' + o.invites.length + ')'),
        el('div', {class: 'sx-card'}, ...(o.invites.length ? o.invites.map((i) => el('div', {class: 'srow inline'}, el('div', {class: 'stxt'}, el('b', {}, '…-' + i.ends_with + '  ·  ' + i.tier), el('small', {}, i.uses_left + ' use(s) left · ends ' + sxWhen(i.expires))), el('div', {class: 'sctl'}, sxBtn('Cancel', async () => { await post('/api/admin/invites/revoke', {id: i.id}); adminPage(id); }, 'bad')))) : [el('div', {class: 'srow'}, 'No active codes.')])));
    // Answer reports: what people said was wrong with an answer, newest first, each with Mark handled.
    } else if (id === 'a-feedback') {
      const f = await (await api('/api/admin/feedback?limit=60')).json();
      const kindName = (k) => (f.kinds[k] || k);
      const pills = (obj, name) => Object.keys(obj).length ? Object.entries(obj).map(([k, n]) => sxPill(name(k) + ' · ' + n)) : [el('small', {style: 'color:var(--muted)'}, 'None yet.')];
      host.replaceChildren(
        el('div', {class: 'sx-card'}, el('div', {class: 'srow stack'}, el('div', {class: 'stxt'}, el('b', {}, f.counts.new + ' new report' + (f.counts.new === 1 ? '' : 's')), el('small', {}, f.counts.total + ' in total. People send these with the Report button under an answer; private chats can’t be reported.')),
          el('div', {style: 'display:flex;flex-wrap:wrap;gap:6px'}, ...pills(f.counts.by_kind, kindName)), el('div', {style: 'display:flex;flex-wrap:wrap;gap:6px'}, ...pills(f.counts.by_model, (m) => m || 'unknown model')),
          el('div', {style: 'display:flex;gap:8px;flex-wrap:wrap'}, el('a', {class: 'sbtn', href: '/api/admin/feedback/export', download: ''}, 'Download as a lessons file'),
            el('small', {style: 'color:var(--muted);align-self:center'}, 'One line per report (question, the weak answer, what was wrong). You still write the corrected answers.')))),
        el('div', {class: 'sx-sec'}, 'Newest first'),
        el('div', {class: 'sx-card'}, ...(f.items.length ? f.items.map((i) => el('div', {class: 'srow stack'}, el('div', {class: 'stxt'}, el('b', {}, kindName(i.kind) + '  ·  ' + (i.model || '?') + '  ·  ' + i.user), el('small', {}, sxWhen(i.at))),
          el('div', {style: 'font-size:14px'}, el('b', {}, 'Asked: '), clip(i.question, 300)), el('div', {style: 'font-size:14px;color:var(--muted)'}, el('b', {style: 'color:var(--text)'}, 'Answered: '), clip(i.answer, 400)),
          i.note ? el('div', {style: 'font-size:14px'}, el('b', {}, 'They said: '), i.note) : null,
          el('div', {}, sxBtn('Mark handled', async () => { await post('/api/admin/feedback/handle', {id: i.id}); adminPage(id); })))) : [el('div', {class: 'srow'}, 'Nothing new. Nice.')])));
    // Backups: the newest backup, make one now, download the earlier ones and good-to-know notes.
    } else if (id === 'a-backups') {
      const b = await (await api('/api/admin/backups')).json();
      // size turns bytes into KB or MB.
      const size = (n) => n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1000)) + ' KB';
      const out = el('div', {role: 'status', style: 'color:var(--muted);font-size:14px;word-break:break-word'});
      host.replaceChildren(
        el('div', {class: 'sx-card'}, el('div', {class: 'srow stack'},
          el('div', {class: 'stxt'}, el('b', {}, b.items.length ? 'Newest backup: ' + sxWhen(b.items[0].at) : 'No backups yet'), el('small', {}, 'A backup is one zip of everything this server keeps (chats, people, notes, projects), made safely while the app runs. The newest ' + b.keep + ' are kept.')),
          el('div', {style: 'display:flex;gap:8px;flex-wrap:wrap'}, sxBtn('Make a backup now', async (e) => { e.target.disabled = true; out.textContent = 'Making a backup...'; const r = await post('/api/admin/backups/now', {}); const j = await r.json(); e.target.disabled = false;
            if (r.ok) adminPage(id); else { out.style.color = 'var(--danger)'; out.textContent = j.message; } }, 'primary')), out)),
        el('div', {class: 'sx-sec'}, 'Your backups'),
        el('div', {class: 'sx-card'}, ...(b.items.length ? b.items.map((i) => el('div', {class: 'srow inline'}, el('div', {class: 'stxt'}, el('b', {}, i.name), el('small', {}, sxWhen(i.at) + ' · ' + size(i.size))),
          el('div', {class: 'sctl'}, el('a', {class: 'sbtn', href: '/api/admin/backups/' + i.name, download: ''}, 'Download')))) : [el('div', {class: 'srow'}, 'None yet.')])),
        el('div', {class: 'sx-sec'}, 'Good to know'),
        el('div', {class: 'sx-card'}, el('div', {class: 'srow stack'},
          el('small', {style: 'color:var(--muted)'}, 'They are stored in ' + b.dir + ', next to the data folder. A backup on the same computer does not help if the computer dies: download one now and then and keep it somewhere else (another disk, your cloud drive). It holds everyone’s chats, so keep it private.'),
          el('small', {style: 'color:var(--muted)'}, 'The key that protects saved tokens (secret.key) is not inside a backup on purpose. Keep a copy of it somewhere else too, or people will have to connect their apps again after a restore.'),
          el('small', {style: 'color:var(--muted)'}, 'To restore, stop the app, then in PowerShell: python tools/backup_data.py --restore ' + (b.items[0] ? b.items[0].name : 'emvryx-DATE.zip') + ' --to .emvryx-restored, check the folder, then swap it in for .emvryx and start the app. Restoring while the app runs is not offered because it could corrupt the live data.'))));
    // Cloud machine: the address (host, port, user) of a computer VryxCode may run code on, a public key to copy and a step by step guide.
    } else if (id === 'a-cloud') {
      const c = await (await api('/api/admin/cloud')).json();
      const hostIn = sxInput('text', 'ssh5.vast.ai or 203.0.113.7', {'aria-label': 'Host', value: c.host || '', inputmode: 'url'});
      const portIn = sxInput('text', '22', {'aria-label': 'Port', inputmode: 'numeric', value: String(c.port || 22)});
      const userIn = sxInput('text', 'root', {'aria-label': 'User', value: c.user || 'root'});
      const out = el('div', {role: 'status', style: 'color:var(--muted);font-size:14px;word-break:break-word;white-space:pre-wrap'});
      const say = (ok, text) => { out.style.color = ok ? 'var(--muted)' : 'var(--danger)'; out.textContent = text; };
      // save stores the address, optionally for other people too.
      const save = async (forOthers) => {
        const r = await post('/api/admin/cloud', {host: hostIn.value.trim(), port: portIn.value.trim(), user: userIn.value.trim(), for_others: forOthers});
        const j = await r.json();
        say(r.ok, r.ok ? 'Saved.' : j.message + ' ' + (j.action || ''));
        return r.ok;
      };
      // The public key and a Copy button.
      const keyRows = c.public_key ? [el('div', {class: 'setupkey', style: 'font-size:13px;letter-spacing:0;text-align:left'}, c.public_key),
        el('div', {}, sxBtn('Copy public key', async (e) => { try { await navigator.clipboard.writeText(c.public_key); e.target.textContent = 'Copied'; } catch (x) {} }))] : [];
      // cloud_guide: a free Oracle Cloud machine, step by step in plain words (the steps below are the same three: machine, key, check)
      // step draws one numbered step of the guide.
      const step = (n, title, ...kids) => el('div', {class: 'srow stack', style: 'border-top:1px solid var(--line)'}, el('b', {}, n + '. ' + title), ...kids);
      // tip draws a small grey explanation line.
      const tip = (t) => el('small', {style: 'color:var(--muted)'}, t);
      // The guide is a fold-out box, open until the machine is ready.
      const guide = featureOn('cloud_guide') ? el('details', {class: 'sx-card', open: !c.ready}, el('summary', {style: 'cursor:pointer;padding:12px 14px;font-weight:600'}, '\u2601 Free machine on Oracle Cloud: step by step'),
        step(1, 'Make the account', tip('On cloud.oracle.com choose Sign up and pick a home region near you (it cannot be changed later). Oracle asks for a card to check who you are; Always Free machines are not charged. Never press Upgrade to Pay As You Go: that is the only way charges can start.')),
        step(2, 'Make the key here first', tip('Below, under "2. A key for Emvryx", press Make a key, then Copy public key. Emvryx keeps the private half on this computer; nobody is shown it.')),
        step(3, 'Create the machine', tip('In Oracle: menu > Compute > Instances > Create instance. Image: Canonical Ubuntu (22.04 or newer). Shape: Ampere, VM.Standard.A1.Flex (it says Always Free-eligible), with the cores and memory inside the free amount it shows. Under Add SSH keys choose Paste public keys and paste the key you copied. Press Create and wait until it says Running.'),
          tip('If it says "Out of capacity", try another availability domain in the same screen, or again later: free Arm machines are popular.')),
        step(4, 'Fill in its address', tip('On the instance page copy the Public IP address. Below, put it in Host; the user is ubuntu and the port 22.'),
          el('div', {}, sxBtn('Fill in ubuntu and 22', () => { userIn.value = 'ubuntu'; portIn.value = '22'; hostIn.focus(); }))),
        step(5, 'Check it', tip('Press Save, then Test the connection. When it says Connected, choose Cloud machine as the environment in VryxCode: its terminal and servers then run there, not on this PC.')),
        step(6, 'Keep it free and safe', tip('Leave only port 22 (SSH) open in Oracle; never open 3389. If the machine sits unused for a long time Oracle may stop it: start it again from the same page.'))) : null;
      // Put the guide and the cards into the page.
      host.replaceChildren(
        ...(guide ? [guide] : []),
        el('div', {class: 'sx-card'}, el('div', {class: 'srow stack'},
          el('div', {class: 'stxt'}, el('b', {}, c.ready ? 'Ready' : 'Not ready yet'), el('small', {}, c.ready ? 'VryxCode can run code on ' + c.host + '.' : (c.why_not || 'Fill in the steps below.'))),
          !c.ssh_found ? el('small', {style: 'color:var(--danger)'}, 'This computer has no ssh program. On Windows, turn on OpenSSH Client in Settings > Optional features.') : null)),
        el('div', {class: 'sx-sec'}, '1. The machine'),
        el('div', {class: 'sx-card'}, el('div', {class: 'srow stack'},
          el('small', {style: 'color:var(--muted)'}, 'Rent one (for example a Vast.ai instance), then copy its address, port and user from its Connect button. It needs python3 and git for most projects.'),
          authField('Host', hostIn), authField('Port', portIn), authField('User', userIn),
          el('div', {style: 'display:flex;align-items:center;gap:12px'}, sxSwitch(c.for_others, async (v) => { await save(v); adminPage(id); }, 'Let other people use it'), el('span', {}, 'Let other people use it')),
          el('small', {style: 'color:var(--muted)'}, 'Off means only you. What people run there is their code on your rented machine, so turn it on only for people you trust.'),
          el('div', {}, sxBtn('Save', async () => { if (await save(c.for_others)) adminPage(id); }, 'primary')))),
        el('div', {class: 'sx-sec'}, '2. A key for Emvryx'),
        el('div', {class: 'sx-card'}, el('div', {class: 'srow stack'},
          el('small', {style: 'color:var(--muted)'}, 'Emvryx makes a key and keeps the private half on this computer. Add the public half below to the machine (on Vast.ai: Account > SSH Keys), then press Test.'),
          ...keyRows,
          el('div', {}, sxBtn(c.key_made ? 'Make a new key' : 'Make a key', async () => { if (c.key_made && !confirm('A new key replaces the old one. Add the new public key to the machine afterwards.')) return;
            const r = await post('/api/admin/cloud/keygen', {replace: c.key_made}); const j = await r.json(); if (r.ok) adminPage(id); else say(false, j.message + ' ' + (j.action || '')); }, c.key_made ? '' : 'primary')))),
        el('div', {class: 'sx-sec'}, '3. Check it'),
        el('div', {class: 'sx-card'}, el('div', {class: 'srow stack'},
          el('div', {}, sxBtn('Test the connection', async (e) => { e.target.disabled = true; say(true, 'Connecting...'); const r = await post('/api/admin/cloud/test'); const j = await r.json(); e.target.disabled = false;
            say(r.ok, r.ok ? 'Connected.\n' + j.text : j.message + ' ' + (j.action || '')); })), out)),
        el('small', {style: 'color:var(--muted)'}, 'Then in VryxCode choose Cloud machine as the environment. Each command copies your project over, runs it there, and copies new and changed files back. The .git folder never leaves this computer.'));
    } else if (id === 'a-log') {
      const a = await (await api('/api/admin/audit?limit=100')).json();
      host.replaceChildren(el('div', {class: 'sx-card'}, ...a.events.map((e) => el('div', {class: 'logline'}, el('time', {}, sxWhen(e.at)), el('b', {}, (EVENT_NAMES[e.kind] || e.kind) + (e.user ? ' · ' + e.user : '')), el('span', {}, [e.ip, e.detail].filter(Boolean).join(' · '))))));
    }
  } catch (e) { if (e.message !== 'login') host.textContent = 'Could not load this page.'; }
}
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && document.querySelector('.sx') && !document.querySelector('.modal')) closeSettings(); });
