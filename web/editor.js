/* editor.js - the small code editor behind VryxCode's Editor layout: colours for the code, line numbers, Tab, auto-indent and Ctrl/Cmd+S.
   No libraries: a textarea with the colouring drawn underneath it (so the phone keyboard, selection, undo and paste are the browser's own).
   Works on files up to about 200 KB (the server's limit for the editor). Exposed as window.EmvryxEditor; also usable from Node for the tests. */
(function (root) {
  'use strict';
  var LANG_BY_EXT = {py: 'py', js: 'js', mjs: 'js', cjs: 'js', jsx: 'js', ts: 'js', tsx: 'js', json: 'json', html: 'html', htm: 'html', xml: 'html', svg: 'html', css: 'css', md: 'md', sh: 'sh', bash: 'sh', yml: 'yaml', yaml: 'yaml', toml: 'yaml', ini: 'yaml', sql: 'sql', c: 'c', h: 'c', cpp: 'c', cc: 'c', hpp: 'c', java: 'c', go: 'c', rs: 'c', cs: 'c', php: 'c'};
  function langOf(path) {
    var m = /\.([A-Za-z0-9]+)$/.exec(String(path || ''));
    return (m && LANG_BY_EXT[m[1].toLowerCase()]) || 'text';
  }
  var KW = {
    py: 'and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield self',
    js: 'const let var function return if else for while do switch case break continue new class extends super import export from default async await try catch finally throw typeof instanceof in of this null undefined true false void delete static get set interface type enum implements public private',
    c: 'if else for while do switch case break continue return struct class enum union typedef static const void int long short char float double bool true false null nil new delete this public private protected package import include using namespace func fn let mut pub use mod impl trait self string var def extends implements final abstract interface try catch finally throw throws defer go chan range',
    sh: 'if then else elif fi for while do done case esac function in return exit export local echo cd',
    sql: 'select from where and or not insert into values update set delete create table drop alter index primary key foreign references join left right inner outer on group by order having limit offset as distinct null is in like between union all case when then else end',
    css: 'important', json: 'true false null', yaml: 'true false null yes no on off'
  };
  function words(list) { return '\\b(?:' + list.trim().split(/\s+/).join('|') + ')\\b'; }
  var STR_DQ = '"(?:\\\\.|[^"\\\\\\n])*"?', STR_SQ = "'(?:\\\\.|[^'\\\\\\n])*'?", NUM = '\\b(?:0[xX][0-9a-fA-F_]+|\\d[\\d_]*(?:\\.\\d+)?(?:[eE][+-]?\\d+)?)\\b';
  // [class, regex source] per language, tried in this order at each position (one capture group per rule)
  var RULES = {
    py: [['c', '#.*'], ['s', '[rbfRBF]{0,2}(?:"""[\\s\\S]*?(?:"""|$)|\'\'\'[\\s\\S]*?(?:\'\'\'|$))'], ['s', '[rbfRBF]{0,2}' + STR_DQ], ['s', '[rbfRBF]{0,2}' + STR_SQ], ['n', NUM], ['k', words(KW.py)]],
    js: [['c', '\\/\\/.*|\\/\\*[\\s\\S]*?(?:\\*\\/|$)'], ['s', '`(?:\\\\[\\s\\S]|[^`\\\\])*`?'], ['s', STR_DQ], ['s', STR_SQ], ['n', NUM], ['k', words(KW.js)]],
    c: [['c', '\\/\\/.*|\\/\\*[\\s\\S]*?(?:\\*\\/|$)'], ['s', STR_DQ], ['s', STR_SQ], ['n', NUM], ['k', words(KW.c)]],
    sh: [['c', '#.*'], ['s', STR_DQ], ['s', STR_SQ], ['n', NUM], ['k', words(KW.sh)]],
    sql: [['c', '--.*|\\/\\*[\\s\\S]*?(?:\\*\\/|$)'], ['s', STR_SQ], ['n', NUM], ['k', '(?:' + words(KW.sql) + '|' + words(KW.sql.toUpperCase()) + ')']],
    json: [['p', '"(?:\\\\.|[^"\\\\\\n])*"(?=\\s*:)'], ['s', STR_DQ], ['n', '-?\\d[\\d.eE+-]*'], ['k', words(KW.json)]],
    yaml: [['c', '#.*'], ['p', '^[ \\t-]*[\\w.-]+(?=\\s*:)'], ['s', STR_DQ], ['s', STR_SQ], ['n', NUM], ['k', words(KW.yaml)]],
    css: [['c', '\\/\\*[\\s\\S]*?(?:\\*\\/|$)'], ['s', STR_DQ], ['s', STR_SQ], ['k', '@[\\w-]+'], ['p', '[\\w-]+(?=\\s*:)'], ['n', '#[0-9a-fA-F]{3,8}\\b|-?\\d[\\d.]*(?:px|em|rem|%|vh|vw|s|ms|deg)?\\b']],
    html: [['c', '<!--[\\s\\S]*?(?:-->|$)'], ['t', '<\\/?[A-Za-z][\\w:-]*|\\/?>'], ['s', STR_DQ], ['s', STR_SQ], ['p', '\\b[\\w:-]+(?==)']],
    md: [['k', '^#{1,6} .*$'], ['s', '```[\\s\\S]*?(?:```|$)'], ['s', '`[^`\\n]+`'], ['t', '\\*\\*[^*\\n]+\\*\\*'], ['p', '^\\s*(?:[-*+]|\\d+\\.) ']]
  };
  var COMPILED = {};
  function compiled(lang) {
    if (!RULES[lang]) return null;
    if (!COMPILED[lang]) COMPILED[lang] = {re: new RegExp(RULES[lang].map(function (r) { return '(' + r[1] + ')'; }).join('|'), 'gm'), cls: RULES[lang].map(function (r) { return r[0]; })};
    return COMPILED[lang];
  }
  function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  /* The text as HTML with <span class="tk-?"> around comments (c), strings (s), numbers (n), keywords (k), names (p) and tags (t). Always ends with a newline
     character so a last empty line has height. Never throws: an odd file just comes out less coloured. */
  function highlight(src, lang) {
    var c = compiled(lang), out = '', pos = 0, m;
    if (!c || src.length > 400000) return esc(src) + '\n';
    c.re.lastIndex = 0;
    while ((m = c.re.exec(src)) !== null) {
      if (m[0] === '') { c.re.lastIndex++; continue; }
      var g = 1; while (g < m.length && m[g] === undefined) g++;
      out += esc(src.slice(pos, m.index)) + '<span class="tk-' + c.cls[g - 1] + '">' + esc(m[0]) + '</span>';
      pos = m.index + m[0].length;
    }
    return out + esc(src.slice(pos)) + '\n';
  }
  /* What a new line should start with after Enter: the indent of the line before, plus one more level after an opening bracket or a colon (Python). */
  function indentAfter(textBeforeCursor, unit) {
    unit = unit || '    ';
    var line = textBeforeCursor.slice(textBeforeCursor.lastIndexOf('\n') + 1), lead = /^[ \t]*/.exec(line)[0];
    return /[{[(:]\s*$/.test(line) ? lead + unit : lead;
  }
  function el(tag, cls, parent) { var e = document.createElement(tag); if (cls) e.className = cls; if (parent) parent.appendChild(e); return e; }
  /* An editor in `host` (an empty element). opts: onChange(text), onSave(), readOnly. Returns {setText, getText, focus, setLang, setReadOnly, scrollTo}. */
  function makeEditor(host, opts) {
    opts = opts || {};
    var ed = el('div', 'ed', host), gut = el('div', 'gut', ed), wrap = el('div', 'wrapx', ed), pre = el('pre', 'hl', wrap), ta = el('textarea', 'in', wrap);
    ta.setAttribute('spellcheck', 'false'); ta.setAttribute('autocapitalize', 'off'); ta.setAttribute('autocomplete', 'off'); ta.setAttribute('autocorrect', 'off'); ta.setAttribute('wrap', 'off');
    ta.setAttribute('aria-label', 'File editor'); ta.readOnly = !!opts.readOnly;
    pre.setAttribute('aria-hidden', 'true');
    var lang = 'text', frame = 0, lines = 0;
    function paint() {
      frame = 0;
      var text = ta.value;
      pre.innerHTML = highlight(text, lang);
      var n = text.split('\n').length;
      if (n !== lines) { lines = n; var s = ''; for (var i = 1; i <= n; i++) s += i + '\n'; gut.textContent = s; gut.style.width = (String(n).length * 9 + 22) + 'px'; }
      sync();
    }
    function sync() { pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft; gut.scrollTop = ta.scrollTop; }
    function schedule() { if (!frame) frame = (root.requestAnimationFrame || function (f) { return setTimeout(f, 16); })(paint); }
    ta.addEventListener('scroll', sync);
    ta.addEventListener('input', function () { schedule(); if (opts.onChange) opts.onChange(ta.value); });
    ta.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) { e.preventDefault(); if (opts.onSave) opts.onSave(); return; }
      if (ta.readOnly) return;
      var s = ta.selectionStart, t = ta.selectionEnd, v = ta.value;
      if (e.key === 'Tab') {
        e.preventDefault();
        if (s === t && !e.shiftKey) { insert('    '); return; }
        var from = v.lastIndexOf('\n', s - 1) + 1, block = v.slice(from, t), out = e.shiftKey ? block.replace(/^( {1,4}|\t)/gm, '') : block.replace(/^/gm, '    ');
        ta.setSelectionRange(from, t); insert(out); ta.setSelectionRange(from, from + out.length);
      } else if (e.key === 'Enter' && s === t && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
        e.preventDefault(); insert('\n' + indentAfter(v.slice(0, s)));
      }
    });
    // insert through the browser's own editing command when it can, so Undo (Ctrl+Z) keeps working
    function insert(text) {
      var ok = false;
      try { ok = document.execCommand && document.execCommand('insertText', false, text); } catch (x) { ok = false; }
      if (!ok) { var s = ta.selectionStart, t = ta.selectionEnd; ta.setRangeText(text, s, t, 'end'); ta.dispatchEvent(new Event('input')); }
    }
    return {
      setText: function (text) { ta.value = text; lines = -1; paint(); ta.scrollTop = 0; ta.scrollLeft = 0; sync(); },
      getText: function () { return ta.value; },
      setLang: function (l) { lang = l; lines = -1; paint(); },
      setReadOnly: function (on) { ta.readOnly = !!on; },
      focus: function () { ta.focus(); },
      state: function () { return {start: ta.selectionStart, end: ta.selectionEnd, top: ta.scrollTop}; },
      restore: function (st) { if (!st) return; ta.setSelectionRange(st.start, st.end); ta.scrollTop = st.top; sync(); }
    };
  }
  var api = {langOf: langOf, highlight: highlight, indentAfter: indentAfter, makeEditor: makeEditor};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.EmvryxEditor = api;
})(typeof window !== 'undefined' ? window : globalThis);
