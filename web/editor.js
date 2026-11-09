/* editor.js - the small code editor behind VryxCode's Editor layout: colours for the code, line numbers, Tab, auto-indent and Ctrl/Cmd+S, and Ctrl/Cmd+K for "edit this selection" (the page handles it through opts.onEdit).
   No libraries: a textarea with the colouring drawn underneath it (so the phone keyboard, selection, undo and paste are the browser's own).
   Works on files up to about 200 KB (the server's limit for the editor). Exposed as window.EmvryxEditor; also usable from Node for the tests. */
// Everything is wrapped in one function so its helper names do not leak into the page; "root" is the window (or Node's global object when the tests run it).
(function (root) {
  'use strict';
  // LANG_BY_EXT: which colouring language each file ending uses.
  var LANG_BY_EXT = {py: 'py', js: 'js', mjs: 'js', cjs: 'js', jsx: 'js', ts: 'js', tsx: 'js', json: 'json', html: 'html', htm: 'html', xml: 'html', svg: 'html', css: 'css', md: 'md', sh: 'sh', bash: 'sh', yml: 'yaml', yaml: 'yaml', toml: 'yaml', ini: 'yaml', sql: 'sql', c: 'c', h: 'c', cpp: 'c', cc: 'c', hpp: 'c', java: 'c', go: 'c', rs: 'c', cs: 'c', php: 'c'};
  // langOf: the language for a file path; unknown endings are plain "text".
  function langOf(path) {
    var m = /\.([A-Za-z0-9]+)$/.exec(String(path || ''));
    return (m && LANG_BY_EXT[m[1].toLowerCase()]) || 'text';
  }
  // KW: the keywords of each language that get the keyword colour.
  var KW = {
    py: 'and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield self',
    js: 'const let var function return if else for while do switch case break continue new class extends super import export from default async await try catch finally throw typeof instanceof in of this null undefined true false void delete static get set interface type enum implements public private',
    c: 'if else for while do switch case break continue return struct class enum union typedef static const void int long short char float double bool true false null nil new delete this public private protected package import include using namespace func fn let mut pub use mod impl trait self string var def extends implements final abstract interface try catch finally throw throws defer go chan range',
    sh: 'if then else elif fi for while do done case esac function in return exit export local echo cd',
    sql: 'select from where and or not insert into values update set delete create table drop alter index primary key foreign references join left right inner outer on group by order having limit offset as distinct null is in like between union all case when then else end',
    css: 'important', json: 'true false null', yaml: 'true false null yes no on off'
  };
  // words: turn a list of keywords into a pattern that matches whole words only.
  function words(list) { return '\\b(?:' + list.trim().split(/\s+/).join('|') + ')\\b'; }
  // Patterns for double-quoted strings, single-quoted strings (an unfinished one at the end of a line still counts) and numbers.
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
  // COMPILED keeps each language's combined pattern after it is first built, so it is not rebuilt for every key press.
  var COMPILED = {};
  // compiled: join a language's rules into one big pattern; the group that matched tells which colour class to use.
  function compiled(lang) {
    if (!RULES[lang]) return null;
    if (!COMPILED[lang]) COMPILED[lang] = {re: new RegExp(RULES[lang].map(function (r) { return '(' + r[1] + ')'; }).join('|'), 'gm'), cls: RULES[lang].map(function (r) { return r[0]; })};
    return COMPILED[lang];
  }
  // esc: make text safe to put in the page by escaping & < >.
  function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  /* The text as HTML with <span class="tk-?"> around comments (c), strings (s), numbers (n), keywords (k), names (p) and tags (t). Always ends with a newline
     character so a last empty line has height. Never throws: an odd file just comes out less coloured. */
  // highlight: the code as coloured HTML plus a final newline, so a last empty line still has height.
  function highlight(src, lang) { return highlightBody(src, lang) + '\n'; }
  // highlightBody: walk through the text, wrapping each comment, string, number, keyword, name or tag in a coloured span; very long files are left uncoloured.
  function highlightBody(src, lang) {
    var c = compiled(lang), out = '', pos = 0, m;
    if (!c || src.length > 400000) return esc(src);
    c.re.lastIndex = 0;
    while ((m = c.re.exec(src)) !== null) {
      if (m[0] === '') { c.re.lastIndex++; continue; }
      var g = 1; while (g < m.length && m[g] === undefined) g++;
      out += esc(src.slice(pos, m.index)) + '<span class="tk-' + c.cls[g - 1] + '">' + esc(m[0]) + '</span>';
      pos = m.index + m[0].length;
    }
    return out + esc(src.slice(pos));
  }
  /* What a new line should start with after Enter: the indent of the line before, plus one more level after an opening bracket or a colon (Python). */
  // indentAfter: what a new line should start with after Enter: the same indent as the line before, one level deeper after an opening bracket or colon.
  function indentAfter(textBeforeCursor, unit) {
    unit = unit || '    ';
    var line = textBeforeCursor.slice(textBeforeCursor.lastIndexOf('\n') + 1), lead = /^[ \t]*/.exec(line)[0];
    return /[{[(:]\s*$/.test(line) ? lead + unit : lead;
  }
  /* A line diff of two texts: [{t: '=' | '-' | '+', s: line}], by the longest common run of lines (fine for the few dozen lines of a selection). */
  // diffLines: compare two texts line by line and say which lines are the same, removed (-) or added (+), using the longest common run of lines; huge inputs just show everything removed then added.
  function diffLines(a, b) {
    var x = a.split('\n'), y = b.split('\n'), n = x.length, m = y.length, i, j, t = [];
    if (n * m > 250000) return x.map(function (l) { return {t: '-', s: l}; }).concat(y.map(function (l) { return {t: '+', s: l}; }));
    // Fill a table where each cell counts how many lines match from that point to the end...
    for (i = 0; i <= n; i++) t.push(new Array(m + 1).fill(0));
    for (i = n - 1; i >= 0; i--) for (j = m - 1; j >= 0; j--) t[i][j] = x[i] === y[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
    // ...then walk through the table to produce the result.
    var out = []; i = 0; j = 0;
    while (i < n && j < m) {
      if (x[i] === y[j]) { out.push({t: '=', s: x[i]}); i++; j++; }
      else if (t[i + 1][j] >= t[i][j + 1]) { out.push({t: '-', s: x[i]}); i++; }
      else { out.push({t: '+', s: y[j]}); j++; }
    }
    while (i < n) out.push({t: '-', s: x[i++]});
    while (j < m) out.push({t: '+', s: y[j++]});
    return out;
  }
  // el: create an element with a class and attach it to a parent.
  function el(tag, cls, parent) { var e = document.createElement(tag); if (cls) e.className = cls; if (parent) parent.appendChild(e); return e; }
  /* An editor in `host` (an empty element). opts: onChange(text), onSave(), readOnly. Returns {setText, getText, focus, setLang, setReadOnly, scrollTo}. */
  // makeEditor: build the editor inside an empty element. It is a plain text box (so phone keyboards, selection, undo and paste work normally) with a coloured copy drawn underneath it, and a line-number column on the left.
  function makeEditor(host, opts) {
    opts = opts || {};
    var ed = el('div', 'ed', host), gut = el('div', 'gut', ed), wrap = el('div', 'wrapx', ed), pre = el('pre', 'hl', wrap), ta = el('textarea', 'in', wrap);
    ta.setAttribute('spellcheck', 'false'); ta.setAttribute('autocapitalize', 'off'); ta.setAttribute('autocomplete', 'off'); ta.setAttribute('autocorrect', 'off'); ta.setAttribute('wrap', 'off');
    ta.setAttribute('aria-label', 'File editor'); ta.readOnly = !!opts.readOnly;
    pre.setAttribute('aria-hidden', 'true');
    // State: the language, a pending repaint, the line count, and the grey "ghost" suggestion text.
    var lang = 'text', frame = 0, lines = 0, ghost = '', ghostKey = '';
    // paint: redraw the coloured copy (with the ghost text after the cursor if there is one) and the line numbers.
    function paint() {
      frame = 0;
      var text = ta.value, n = text.split('\n').length, extra = 0, at = ta.selectionStart;
      if (ghost && ta.selectionStart === ta.selectionEnd) {              // grey suggestion drawn after the cursor (the textarea itself never holds it)
        pre.innerHTML = highlightBody(text.slice(0, at), lang) + '<span class="ghost">' + esc(ghost) + '</span>' + highlightBody(text.slice(at), lang) + '\n';
        extra = ghost.split('\n').length - 1; ghostKey = text.slice(0, at).split('\n').length;
      } else { ghost = ''; pre.innerHTML = highlight(text, lang); ghostKey = ''; }
      var key = n + ':' + extra + ':' + ghostKey;
      if (key !== lines) {                                               // line numbers (blank ones under the cursor's line while a multi-line suggestion pushes the rest down)
        lines = key; var g = ''; for (var i = 1; i <= n; i++) { g += i + '\n'; if (extra && i === ghostKey) g += new Array(extra + 1).join('\n'); }
        gut.textContent = g; gut.style.width = (String(n).length * 9 + 22) + 'px';
      }
      sync();
    }
    // sync: keep the coloured copy and the line numbers scrolled together with the text box.
    function sync() { pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft; gut.scrollTop = ta.scrollTop; }
    // schedule: ask for one repaint on the next screen refresh, however many keys were pressed.
    function schedule() { if (!frame) frame = (root.requestAnimationFrame || function (f) { return setTimeout(f, 16); })(paint); }
    ta.addEventListener('scroll', sync);
    // Typing removes any ghost suggestion, repaints and tells the page about the change.
    ta.addEventListener('input', function () { ghost = ''; schedule(); if (opts.onChange) opts.onChange(ta.value); if (opts.onType) opts.onType(ta.value, ta.selectionStart); });
    // clearGhost: remove the grey suggestion.
    function clearGhost() { if (ghost) { ghost = ''; lines = -1; schedule(); } }
    ta.addEventListener('click', clearGhost); ta.addEventListener('blur', clearGhost);
    // Keys: Ctrl/Cmd+S saves, Ctrl/Cmd+K asks for an AI edit, Tab accepts a suggestion or indents (Shift+Tab un-indents the selected lines), and Enter keeps the indent of the line above.
    ta.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) { e.preventDefault(); if (opts.onSave) opts.onSave(); return; }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); if (opts.onEdit) opts.onEdit(); return; }
      if (ta.readOnly) return;
      var s = ta.selectionStart, t = ta.selectionEnd, v = ta.value;
      if (ghost && s === t && e.key === 'Tab' && !e.shiftKey) { e.preventDefault(); var g = ghost; ghost = ''; insert(g); return; }          // Tab accepts the grey suggestion
      if (ghost && (e.key === 'Escape' || /^Arrow|^Home$|^End$|^Page/.test(e.key))) clearGhost();
      if (e.key === 'Tab') {
        e.preventDefault();
        if (s === t && !e.shiftKey) { insert('    '); return; }
        var from = v.lastIndexOf('\n', s - 1) + 1, block = v.slice(from, t), out = e.shiftKey ? block.replace(/^( {1,4}|\t)/gm, '') : block.replace(/^/gm, '    ');
        ta.setSelectionRange(from, t); insert(out); ta.setSelectionRange(from, from + out.length);
      } else if (e.key === 'Enter' && s === t && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
        e.preventDefault(); insert('\n' + indentAfter(v.slice(0, s)));
      }
    });
    // insert: put text in through the browser's own editing command when possible, so Undo (Ctrl+Z) keeps working; otherwise set it directly.
    // insert through the browser's own editing command when it can, so Undo (Ctrl+Z) keeps working
    function insert(text) {
      var ok = false;
      try { ok = document.execCommand && document.execCommand('insertText', false, text); } catch (x) { ok = false; }
      if (!ok) { var s = ta.selectionStart, t = ta.selectionEnd; ta.setRangeText(text, s, t, 'end'); ta.dispatchEvent(new Event('input')); }
    }
    // The editor's public functions: set and get the text, ghost suggestions, cursor, language, read-only, focus, selection, replaceRange, and state/restore (cursor and scroll position of a tab).
    return {
      setText: function (text) { ta.value = text; lines = -1; paint(); ta.scrollTop = 0; ta.scrollLeft = 0; sync(); },
      getText: function () { return ta.value; },
      setGhost: function (text) { if (ta.selectionStart !== ta.selectionEnd) return false; ghost = String(text || ''); lines = -1; paint(); return !!ghost; },
      clearGhost: clearGhost,
      hasGhost: function () { return !!ghost; },
      cursor: function () { return ta.selectionStart; },
      setLang: function (l) { lang = l; lines = -1; paint(); },
      setReadOnly: function (on) { ta.readOnly = !!on; },
      focus: function () { ta.focus(); },
      selection: function () { return {start: ta.selectionStart, end: ta.selectionEnd, text: ta.value.slice(ta.selectionStart, ta.selectionEnd)}; },
      // replace a range with new text as an ordinary edit (so Undo works), and select the new text
      replaceRange: function (from, to, text) { ta.focus(); ta.setSelectionRange(from, to); insert(text); ta.setSelectionRange(from, from + text.length); },
      state: function () { return {start: ta.selectionStart, end: ta.selectionEnd, top: ta.scrollTop}; },
      restore: function (st) { if (!st) return; ta.setSelectionRange(st.start, st.end); ta.scrollTop = st.top; sync(); }
    };
  }
  // What the file offers to others: the editor in the browser, and the helper functions for the tests in Node.
  var api = {langOf: langOf, highlight: highlight, indentAfter: indentAfter, diffLines: diffLines, makeEditor: makeEditor};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.EmvryxEditor = api;
})(typeof window !== 'undefined' ? window : globalThis);
