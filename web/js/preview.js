/* The live preview of what VryxCode built. */
// ---------------------------------------------------------------- live preview of what was built (the page's own errors come back here)
// PV remembers the preview: its address, the page's errors, whether it finished loading, the chosen device size and the page being shown.
const PV = {url: null, errors: [], loaded: false, size: 'phone', entry: ''};
// setPvSize: switch the preview frame between phone, tablet and desktop width and mark the active button.
function setPvSize(sz) { PV.size = sz; $('pvStage').dataset.size = sz; document.querySelectorAll('#codePv .pvbar [data-size]').forEach((b) => b.classList.toggle('on', b.dataset.size === sz)); }
// paintPv: the line under the preview: the number of problems found (with a button asking VryxCode to fix them), or "Loaded with no errors".
function paintPv() {
  const foot = $('pvFoot'); foot.replaceChildren();
  if (PV.errors.length) {
    foot.append(el('div', {class: 'bad'}, PV.errors.length + (PV.errors.length === 1 ? ' problem' : ' problems') + ' found in ' + PV.entry),
      el('ul', {}, ...PV.errors.slice(0, 6).map((m) => el('li', {}, m))),
      el('div', {class: 'row'}, el('button', {class: 'btn small', onclick: fixPreviewErrors}, 'Ask VryxCode to fix these')));
  } else foot.append(el('div', {class: PV.loaded ? 'good' : ''}, PV.loaded ? '✓ Loaded with no errors found' : 'Loading…'));
}
// openPreview: ask the server to serve the project's web page (or the running app), then show it in the frame.
async function openPreview() {
  if (!C.project) return;
  const r = await post('/api/code/preview', {project: C.project, page: vxPreviewOn() ? C.pvPage || '' : ''}); const j = await r.json().catch(() => ({}));
  if (!r.ok) { note('bad', 'Preview', (j.message || 'Could not open the preview.') + ' ' + (j.action || '')); return; }
  if (!j.entry) { note('fin', 'Nothing to preview yet', 'Ask VryxCode to build a web page (an .html file) and it can be previewed here.'); return; }
  $('codePreviewBtn').classList.remove('pulse');
  PV.url = j.url; PV.entry = j.entry; PV.errors = []; PV.loaded = false; PV.app = !!j.app; setPvSize(PV.size); paintPv();
  $('pvLogs').hidden = $('pvStopApp').hidden = !PV.app;       // vryxcode_servers: a running app shows its logs and a Stop button
  $('codePv').hidden = false; $('pvFrame').src = j.url;
}
// The Stop app button: stop the running app and close the preview.
$('pvStopApp').onclick = async () => {
  await post('/api/code/app/stop', {project: C.project}); $('codePv').hidden = true; PV.app = false;
  note('fin', 'App stopped', 'Ask VryxCode to start it again when you want to use it.');
};
// The Logs button: show what the running app printed, with a button to ask VryxCode to fix problems.
$('pvLogs').onclick = async () => {
  const r = await post('/api/code/app/logs', {project: C.project}); const j = await r.json().catch(() => ({}));
  const m = dialog([el('h2', {}, 'What the app printed'), el('pre', {style: 'white-space:pre-wrap;max-height:60vh;overflow:auto;font-size:12.5px'}, j.logs || '(nothing)'),
    el('div', {class: 'row'}, el('button', {class: 'btn small', onclick: () => { m.remove(); $('codePv').hidden = true; $('codeTask').value = 'The app shows these errors in its log:\n' + String(j.logs || '').slice(-1500) + '\nFix the cause, start it again with start_app and check it answers.'; $('codeGo').click(); }}, 'Ask VryxCode to fix these'))]);
};
const vxPreviewOn = () => !!(S.state && S.state.features && S.state.features.vryxcode_preview);
// reloadPreview: load the page again, or switch to another page if a different one was changed last.
function reloadPreview() {     // vryxcode_preview: when another page changed, that one is shown instead
  if (!PV.url) return; if (vxPreviewOn() && C.pvPage && C.pvPage !== PV.entry) { openPreview(); return; }
  PV.errors = []; PV.loaded = false; paintPv(); $('pvFrame').src = PV.url;
}
// fixPreviewErrors: write the problems into the message box and send it to VryxCode.
function fixPreviewErrors() {
  const list = PV.errors.slice(0, 6).map((m) => '- ' + m).join('\n');
  $('codePv').hidden = true;
  $('codeTask').value = 'The preview of ' + PV.entry + ' shows these problems:\n' + list + (S.state && S.state.features && S.state.features.vryxcode_fixes
    ? '\nFind the cause of each one in the files and fix it. Then open the page with check_page and keep fixing until it loads with no errors.' : '\nPlease fix them.');
  $('codeGo').click();
}
// Noise filters: messages from scripts the hosting adds, and harmless browser or tool messages, are not shown as problems.
const PV_NOISE = /cloudflareinsights\.com|\/cdn-cgi\//;      // scripts the hosting adds to every page (not in the person's files): never something VryxCode can fix
const PV_NOISE_FIXES = /ResizeObserver loop|^Script error\.?$|favicon\.ico|Download the React DevTools|\[HMR\]|\[vite\]/i;   // vryxcode_fixes: browser and tool chatter that is not a problem in the page
// The preview page sends us messages (it loaded, or an error happened); only messages from our own frame are believed.
window.addEventListener('message', (e) => {
  const f = $('pvFrame'); if (!f || e.source !== f.contentWindow) return;
  const d = e.data || {}; if (!d.vryxPreview) return;
  if (d.loaded) { PV.loaded = true; paintPv(); return; }
  if (typeof d.msg === 'string' && !PV_NOISE.test(d.msg) && !(S.state && S.state.features && S.state.features.vryxcode_fixes && PV_NOISE_FIXES.test(d.msg)) && PV.errors.length < 10 && !PV.errors.includes(d.msg)) { PV.errors.push(d.msg); paintPv(); }
});
// Wire the preview buttons: open, back, reload and the device sizes.
$('codePreviewBtn').onclick = openPreview; $('pvBack').onclick = () => { $('codePv').hidden = true; }; $('pvReload').onclick = reloadPreview;
document.querySelectorAll('#codePv .pvbar [data-size]').forEach((b) => { b.onclick = () => setPvSize(b.dataset.size); });
// The Stop button for VryxCode's work: ask the server to stop the session.
$('codeStop').onclick = () => { if (!C.sid || C.stopping) return; C.stopping = true; $('codeStop').disabled = true; paintLive(); post('/api/code/sessions/' + C.sid + '/stop').then(() => poll()); };
// Enter sends the message (Shift+Enter makes a new line).
// Enter sends (Shift+Enter starts a new line), like the chat. Not while an input method is composing a word, not when Enter is picking a suggestion, and not when there is nothing to send to.
$('codeTask').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing || e.defaultPrevented) return;
  if (!$('codeSuggest').hidden) return;
  if ($('codeGo').hidden || $('codeGo').disabled || !$('codeTask').value.trim()) return;
  e.preventDefault(); $('codeGo').click();
});
// b64: turn raw bytes into base64 text, in chunks so big files do not break the browser.
const b64 = (buf) => { let s = '', a = new Uint8Array(buf); for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode.apply(null, a.subarray(i, i + 0x8000)); return btoa(s); };
// sendImport: upload files into the project and report how many were added.
async function sendImport(body) {
  const r = await post('/api/code/import', Object.assign({project: C.project}, body)); const j = await r.json();
  note(r.ok ? 'fin' : 'bad', r.ok ? 'Imported' : 'Not imported', r.ok ? j.imported + ' files added to ' + C.project + '.' : j.message + ' ' + (j.action || ''));
  refreshFiles();
}
// openImport: the window to choose a zip file or a whole folder to import.
function openImport() {
  const m = dialog([el('h2', {}, 'Import into ' + C.project), el('div', {style: 'color:var(--muted)'}, 'Add an existing project: a zip file, or a whole folder (up to 1,000 files and 20 MB; .git and node_modules are skipped). Files with the same name are replaced.'),
    el('button', {class: 'btn', onclick: () => { m.remove(); $('codeZipIn').click(); }}, 'Choose a zip file'),
    el('button', {class: 'btn ghost', onclick: () => { m.remove(); $('codeDirIn').click(); }}, 'Choose a folder')], 'Cancel');
}
// A chosen zip file is read and sent.
$('codeZipIn').onchange = async (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) await sendImport({zip_b64: b64(await f.arrayBuffer())}); };
// A chosen folder: skip the git history and caches, keep each file's path inside the folder, and send them all.
$('codeDirIn').onchange = async (e) => {
  const list = Array.from(e.target.files).filter((f) => !/(^|\/)(\.git|node_modules|__pycache__)\//.test(f.webkitRelativePath)); e.target.value = '';
  if (!list.length) return;
  const files = []; for (const f of list) { const p = f.webkitRelativePath.split('/').slice(1).join('/'); if (p) files.push({path: p, b64: b64(await f.arrayBuffer())}); }
  await sendImport({files});
};
