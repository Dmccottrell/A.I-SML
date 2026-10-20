/* Answers with real formatting (flag chat_fixes): code blocks with a Copy button, tables, lists, headings, quotes, links, bold, italic and inline code.
   Everything is built as page elements from the text (never as HTML), so nothing a model writes can run on the page. A half-written answer (still
   streaming) renders too: an open code block shows as a code block, a table shows once its dash line has arrived. */
const MD_TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const MD_BULLET = /^(\s*)[-*+•]\s+(.*)$/;
const MD_NUMBER = /^(\s*)(\d{1,3})[.)]\s+(.*)$/;
const MD_INLINE = /(`+)([^`]+?)\1|\*\*([^*\n]+?)\*\*|__([^_\n]+?)__|~~([^~\n]+?)~~|(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\w)|(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"])/g;

function mdInline(text) {          // one line of text -> elements
  const f = document.createDocumentFragment(), re = new RegExp(MD_INLINE.source, 'g'); let at = 0, m;   // its own copy: bold inside a line is read by a nested call
  while ((m = re.exec(text))) {
    if (m.index > at) f.append(text.slice(at, m.index));
    if (m[2] != null) f.append(el('code', {class: 'md-ic'}, m[2]));
    else if (m[3] != null || m[4] != null) f.append(el('b', {}, mdInline(m[3] != null ? m[3] : m[4])));
    else if (m[5] != null) f.append(el('s', {}, mdInline(m[5])));
    else if (m[6] != null || m[7] != null) f.append(el('i', {}, mdInline(m[6] != null ? m[6] : m[7])));
    else if (m[8] != null) f.append(el('a', {href: m[9], target: '_blank', rel: 'noopener noreferrer nofollow'}, m[8]));
    else if (m[10] != null) f.append(el('a', {href: m[10], target: '_blank', rel: 'noopener noreferrer nofollow'}, m[10]));
    at = re.lastIndex;
  }
  if (at < text.length) f.append(text.slice(at));
  return f;
}
function mdCells(line) { return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim()); }
function mdCode(code, lang) {
  const btn = el('button', {class: 'md-copy', type: 'button', onclick: () => { navigator.clipboard && navigator.clipboard.writeText(code); btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = 'Copy'; }, 1500); }}, 'Copy');
  return el('div', {class: 'md-code'}, el('div', {class: 'md-cbar'}, el('span', {}, lang || 'code'), btn), el('pre', {}, el('code', {}, code)));
}
function mdList(lines) {           // [{indent, ordered, start, text}] -> nested lists
  const root = {kids: []}, stack = [{indent: -1, node: root}];
  for (const it of lines) {
    while (stack.length > 1 && it.indent <= stack[stack.length - 1].indent) stack.pop();
    const parent = stack[stack.length - 1].node;
    let list = parent.kids[parent.kids.length - 1];
    if (!list || list.ordered !== it.ordered || list.indent !== it.indent) { list = {ordered: it.ordered, start: it.start, indent: it.indent, items: []}; parent.kids.push(list); }
    const item = {text: it.text, kids: []}; list.items.push(item);
    stack.push({indent: it.indent, node: item});
  }
  const build = (list) => el(list.ordered ? 'ol' : 'ul', list.ordered && list.start !== 1 ? {start: String(list.start)} : {}, ...list.items.map((i) => el('li', {}, mdInline(i.text), ...i.kids.map(build))));
  return root.kids.map(build);
}
function mdRender(text) {
  const box = el('div', {class: 'md'}), lines = String(text || '').replace(/\r/g, '').replace(/^\s+/, '').split('\n');
  let i = 0, para = [];
  const flush = () => { if (para.length) { box.append(el('p', {}, ...para.flatMap((l, k) => k ? [el('br'), mdInline(l)] : [mdInline(l)]))); para = []; } };
  while (i < lines.length) {
    const line = lines[i];
    const fence = /^\s*(```+|~~~+)\s*([\w+#.-]*)/.exec(line);
    if (fence) {
      flush(); const close = fence[1]; const body = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith(close)) body.push(lines[i++]);
      i++; box.append(mdCode(body.join('\n'), fence[2])); continue;
    }
    if (!line.trim()) { flush(); i++; continue; }
    const h = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
    if (h) { flush(); box.append(el('div', {class: 'md-h md-h' + Math.min(h[1].length, 4)}, mdInline(h[2]))); i++; continue; }
    if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); box.append(el('hr')); i++; continue; }
    if (line.includes('|') && i + 1 < lines.length && MD_TABLE_RULE.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      flush(); const head = mdCells(line); i += 2; const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(mdCells(lines[i++]));
      box.append(el('div', {class: 'md-table'}, el('table', {}, el('thead', {}, el('tr', {}, ...head.map((c) => el('th', {}, mdInline(c))))),
        el('tbody', {}, ...rows.map((r) => el('tr', {}, ...head.map((_, k) => el('td', {}, mdInline(r[k] || '')))))))));
      continue;
    }
    if (/^\s*>/.test(line)) {
      flush(); const q = []; while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ''));
      box.append(el('blockquote', {}, mdRender(q.join('\n')))); continue;
    }
    if (MD_BULLET.test(line) || MD_NUMBER.test(line)) {
      flush(); const items = [];
      while (i < lines.length) {
        const b = MD_BULLET.exec(lines[i]), n = b ? null : MD_NUMBER.exec(lines[i]);
        if (b) items.push({indent: b[1].length, ordered: false, start: 1, text: b[2]});
        else if (n) items.push({indent: n[1].length, ordered: true, start: +n[2], text: n[3]});
        else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) items[items.length - 1].text += '\n' + lines[i].trim();   // a wrapped item
        else break;
        i++;
      }
      box.append(...mdList(items)); continue;
    }
    para.push(line); i++;
  }
  flush();
  return box;
}
