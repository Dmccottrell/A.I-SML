/* The live preview of what VryxCode built. */
// ---------------------------------------------------------------- live preview of what was built (the page's own errors come back here)
const PV = {url: null, errors: [], loaded: false, size: 'phone', entry: ''};
function setPvSize(sz) { PV.size = sz; $('pvStage').dataset.size = sz; document.querySelectorAll('#codePv .pvbar [data-size]').forEach((b) => b.classList.toggle('on', b.dataset.size === sz)); }
function paintPv() {
  const foot = $('pvFoot'); foot.replaceChildren();
  if (PV.errors.length) {
    foot.append(el('div', {class: 'bad'}, PV.errors.length + (PV.errors.length === 1 ? ' problem' : ' problems') + ' found in ' + PV.entry),
      el('ul', {}, ...PV.errors.slice(0, 6).map((m) => el('li', {}, m))),
      el('div', {class: 'row'}, el('button', {class: 'btn small', onclick: fixPreviewErrors}, 'Ask VryxCode to fix these')));
  } else foot.append(el('div', {class: PV.loaded ? 'good' : ''}, PV.loaded ? '✓ Loaded with no errors found' : 'Loading…'));
}
async function openPreview() {
  if (!C.project) return;
  const r = await post('/api/code/preview', {project: C.project, page: vxPreviewOn() ? C.pvPage || '' : ''}); const j = await r.json().catch(() => ({}));
  if (!r.ok) { note('bad', 'Preview', (j.message || 'Could not open the preview.') + ' ' + (j.action || '')); return; }
  if (!j.entry) { note('fin', 'Nothing to preview yet', 'Ask VryxCode to build a web page (an .html file) and it can be previewed here.'); return; }
  $('codePreviewBtn').classList.remove('pulse');
  PV.url = j.url; PV.entry = j.entry; PV.errors = []; PV.loaded = false; setPvSize(PV.size); paintPv();
  $('codePv').hidden = false; $('pvFrame').src = j.url;
}
const vxPreviewOn = () => !!(S.state && S.state.features && S.state.features.vryxcode_preview);
function reloadPreview() {     // vryxcode_preview: when another page changed, that one is shown instead
  if (!PV.url) return; if (vxPreviewOn() && C.pvPage && C.pvPage !== PV.entry) { openPreview(); return; }
  PV.errors = []; PV.loaded = false; paintPv(); $('pvFrame').src = PV.url;
}
function fixPreviewErrors() {
  const list = PV.errors.slice(0, 6).map((m) => '- ' + m).join('\n');
  $('codePv').hidden = true;
  $('codeTask').value = 'The preview of ' + PV.entry + ' shows these problems:\n' + list + (S.state && S.state.features && S.state.features.vryxcode_fixes
    ? '\nFind the cause of each one in the files and fix it. Then open the page with check_page and keep fixing until it loads with no errors.' : '\nPlease fix them.');
  $('codeGo').click();
}
const PV_NOISE = /cloudflareinsights\.com|\/cdn-cgi\//;      // scripts the hosting adds to every page (not in the person's files): never something VryxCode can fix
const PV_NOISE_FIXES = /ResizeObserver loop|^Script error\.?$|favicon\.ico|Download the React DevTools|\[HMR\]|\[vite\]/i;   // vryxcode_fixes: browser and tool chatter that is not a problem in the page
window.addEventListener('message', (e) => {
  const f = $('pvFrame'); if (!f || e.source !== f.contentWindow) return;
  const d = e.data || {}; if (!d.vryxPreview) return;
  if (d.loaded) { PV.loaded = true; paintPv(); return; }
  if (typeof d.msg === 'string' && !PV_NOISE.test(d.msg) && !(S.state && S.state.features && S.state.features.vryxcode_fixes && PV_NOISE_FIXES.test(d.msg)) && PV.errors.length < 10 && !PV.errors.includes(d.msg)) { PV.errors.push(d.msg); paintPv(); }
});
$('codePreviewBtn').onclick = openPreview; $('pvBack').onclick = () => { $('codePv').hidden = true; }; $('pvReload').onclick = reloadPreview;
document.querySelectorAll('#codePv .pvbar [data-size]').forEach((b) => { b.onclick = () => setPvSize(b.dataset.size); });
$('codeStop').onclick = () => { if (!C.sid || C.stopping) return; C.stopping = true; $('codeStop').disabled = true; paintLive(); post('/api/code/sessions/' + C.sid + '/stop').then(() => poll()); };
$('codeTask').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $('codeGo').click(); } });
const b64 = (buf) => { let s = '', a = new Uint8Array(buf); for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode.apply(null, a.subarray(i, i + 0x8000)); return btoa(s); };
async function sendImport(body) {
  const r = await post('/api/code/import', Object.assign({project: C.project}, body)); const j = await r.json();
  note(r.ok ? 'fin' : 'bad', r.ok ? 'Imported' : 'Not imported', r.ok ? j.imported + ' files added to ' + C.project + '.' : j.message + ' ' + (j.action || ''));
  refreshFiles();
}
function openImport() {
  const m = dialog([el('h2', {}, 'Import into ' + C.project), el('div', {style: 'color:var(--muted)'}, 'Add an existing project: a zip file, or a whole folder (up to 1,000 files and 20 MB; .git and node_modules are skipped). Files with the same name are replaced.'),
    el('button', {class: 'btn', onclick: () => { m.remove(); $('codeZipIn').click(); }}, 'Choose a zip file'),
    el('button', {class: 'btn ghost', onclick: () => { m.remove(); $('codeDirIn').click(); }}, 'Choose a folder')], 'Cancel');
}
$('codeZipIn').onchange = async (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) await sendImport({zip_b64: b64(await f.arrayBuffer())}); };
$('codeDirIn').onchange = async (e) => {
  const list = Array.from(e.target.files).filter((f) => !/(^|\/)(\.git|node_modules|__pycache__)\//.test(f.webkitRelativePath)); e.target.value = '';
  if (!list.length) return;
  const files = []; for (const f of list) { const p = f.webkitRelativePath.split('/').slice(1).join('/'); if (p) files.push({path: p, b64: b64(await f.arrayBuffer())}); }
  await sendImport({files});
};
