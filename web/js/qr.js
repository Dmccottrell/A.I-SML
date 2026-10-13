/* QR codes for the two-step sign-in setup. */
// ---------------------------------------------------------------- QR codes (for the two-step setup): byte mode, error level L, versions 1 to 9
const QR_BLOCKS = [null, [26, 7, 1, 19], [44, 10, 1, 34], [70, 15, 1, 55], [100, 20, 1, 80], [134, 26, 1, 108], [172, 18, 2, 68], [196, 20, 2, 78], [242, 24, 2, 97], [292, 30, 2, 116]];   // version: [all codewords, check codewords per block, blocks, data codewords per block]
const QR_ALIGN = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46]];
const QR_EXP = new Array(512), QR_LOG = new Array(256);
(() => { let x = 1; for (let i = 0; i < 255; i++) { QR_EXP[i] = x; QR_LOG[x] = i; x <<= 1; if (x & 256) x ^= 0x11D; } for (let i = 255; i < 512; i++) QR_EXP[i] = QR_EXP[i - 255]; })();
const qrMul = (a, b) => (a && b ? QR_EXP[QR_LOG[a] + QR_LOG[b]] : 0);
function qrChecks(data, n) {   // Reed-Solomon: the n check codewords for the data codewords
  let g = [1]; for (let i = 0; i < n; i++) { const next = new Array(g.length + 1).fill(0); for (let j = 0; j < g.length; j++) { next[j] ^= g[j]; next[j + 1] ^= qrMul(g[j], QR_EXP[i]); } g = next; }
  const r = new Array(n).fill(0);
  for (const d of data) { const f = d ^ r[0]; r.shift(); r.push(0); for (let i = 0; i < n; i++) r[i] ^= qrMul(g[i + 1], f); }
  return r;
}
function qrBch(value, poly, bits) { let v = value << bits; const top = (n) => 31 - Math.clz32(n); while (top(v) >= top(poly)) v ^= poly << (top(v) - top(poly)); return (value << bits) | v; }
function qrMatrix(text) {
  const bytes = Array.from(new TextEncoder().encode(text));
  let ver = 1; while (ver < 9 && bytes.length > QR_BLOCKS[ver][2] * QR_BLOCKS[ver][3] - 2) ver++;
  const [total, ecn, nb, dpb] = QR_BLOCKS[ver], dataCw = nb * dpb;
  if (bytes.length > dataCw - 2) return null;
  const bits = []; const put = (v, n) => { for (let i = n - 1; i >= 0; i--) bits.push((v >> i) & 1); };
  put(4, 4); put(bytes.length, 8); bytes.forEach((b) => put(b, 8));
  for (let i = 0; i < 4 && bits.length < dataCw * 8; i++) bits.push(0);
  while (bits.length % 8) bits.push(0);
  for (let pad = 0xEC; bits.length < dataCw * 8; pad ^= 0xEC ^ 0x11) put(pad, 8);
  const cw = []; for (let i = 0; i < bits.length; i += 8) cw.push(parseInt(bits.slice(i, i + 8).join(''), 2));
  const blocks = []; for (let b = 0; b < nb; b++) blocks.push(cw.slice(b * dpb, (b + 1) * dpb));
  const checks = blocks.map((b) => qrChecks(b, ecn)), out = [];
  for (let i = 0; i < dpb; i++) for (const b of blocks) out.push(b[i]);
  for (let i = 0; i < ecn; i++) for (const c of checks) out.push(c[i]);
  const stream = []; out.forEach((c) => put2(stream, c)); function put2(a, v) { for (let i = 7; i >= 0; i--) a.push((v >> i) & 1); }
  const size = 17 + 4 * ver, M = Array.from({length: size}, () => new Array(size).fill(0)), F = Array.from({length: size}, () => new Array(size).fill(false));
  const set = (r, c, v) => { if (r >= 0 && c >= 0 && r < size && c < size) { M[r][c] = v ? 1 : 0; F[r][c] = true; } };
  const finder = (r, c) => { for (let i = -1; i <= 7; i++) for (let j = -1; j <= 7; j++) set(r + i, c + j, i >= 0 && i <= 6 && j >= 0 && j <= 6 && (i === 0 || i === 6 || j === 0 || j === 6 || (i >= 2 && i <= 4 && j >= 2 && j <= 4))); };
  finder(0, 0); finder(0, size - 7); finder(size - 7, 0);
  for (let i = 8; i < size - 8; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
  const al = QR_ALIGN[ver];
  for (const r of al) for (const c of al) { if ((r === 6 && c === 6) || (r === 6 && c === al[al.length - 1]) || (c === 6 && r === al[al.length - 1])) continue; for (let i = -2; i <= 2; i++) for (let j = -2; j <= 2; j++) set(r + i, c + j, Math.max(Math.abs(i), Math.abs(j)) !== 1); }
  set(size - 8, 8, true);
  for (let i = 0; i < 9; i++) { if (!F[8][i]) set(8, i, 0); if (!F[i][8]) set(i, 8, 0); }
  for (let i = 0; i < 8; i++) { if (!F[8][size - 1 - i]) set(8, size - 1 - i, 0); if (!F[size - 1 - i][8]) set(size - 1 - i, 8, 0); }
  if (ver >= 7) { const v = qrBch(ver, 0x1F25, 12); for (let i = 0; i < 18; i++) { const bit = (v >> i) & 1, a = Math.floor(i / 3), b = (i % 3) + size - 11; set(a, b, bit); set(b, a, bit); } }
  const free = F.map((row) => row.slice()), data = [];   // where data goes: two columns at a time, from the bottom right, going up then down
  for (let c = size - 1, up = true; c > 0; c -= 2, up = !up) { if (c === 6) c--; for (let k = 0; k < size; k++) { const r = up ? size - 1 - k : k; for (const cc of [c, c - 1]) if (!free[r][cc]) data.push([r, cc]); } }
  const masks = [(r, c) => (r + c) % 2 === 0, (r) => r % 2 === 0, (r, c) => c % 3 === 0, (r, c) => (r + c) % 3 === 0, (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0, (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0, (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0, (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0];
  const build = (m) => {
    const G = M.map((row) => row.slice());
    data.forEach(([r, c], i) => { G[r][c] = (stream[i] || 0) ^ (masks[m](r, c) ? 1 : 0); });
    const f = qrBch((1 << 3) | m, 0x537, 10) ^ 0x5412;   // error level L is 01
    const fb = (i) => (f >> i) & 1;
    for (let i = 0; i < 6; i++) G[i][8] = fb(i); G[7][8] = fb(6); G[8][8] = fb(7); G[8][7] = fb(8); for (let i = 9; i < 15; i++) G[8][14 - i] = fb(i);
    for (let i = 0; i < 8; i++) G[8][size - 1 - i] = fb(i); for (let i = 8; i < 15; i++) G[size - 15 + i][8] = fb(i);
    G[size - 8][8] = 1; return G;
  };
  const penalty = (G) => {
    let p = 0;
    for (let pass = 0; pass < 2; pass++) for (let a = 0; a < size; a++) { let run = 1; for (let b = 1; b < size; b++) { const cur = pass ? G[b][a] : G[a][b], prev = pass ? G[b - 1][a] : G[a][b - 1]; if (cur === prev) { run++; if (run === 5) p += 3; else if (run > 5) p++; } else run = 1; } }
    for (let r = 0; r < size - 1; r++) for (let c = 0; c < size - 1; c++) if (G[r][c] === G[r][c + 1] && G[r][c] === G[r + 1][c] && G[r][c] === G[r + 1][c + 1]) p += 3;
    const pat = [1, 0, 1, 1, 1, 0, 1];
    for (let pass = 0; pass < 2; pass++) for (let a = 0; a < size; a++) for (let b = 0; b <= size - 7; b++) { const at = (i) => (pass ? G[b + i][a] : G[a][b + i]); if (pat.every((v, i) => at(i) === v)) { const side = (from, to) => { for (let i = from; i < to; i++) if (b + i < 0 || b + i >= size || at(i)) return false; return true; }; if (side(-4, 0) || side(7, 11)) p += 40; } }
    let dark = 0; G.forEach((row) => row.forEach((v) => { dark += v; })); p += Math.floor(Math.abs((dark * 100) / (size * size) - 50) / 5) * 10;
    return p;
  };
  let best = null, bestP = Infinity; for (let m = 0; m < 8; m++) { const G = build(m), p = penalty(G); if (p < bestP) { bestP = p; best = G; } }
  return best;
}
function qrSvg(text, px) {   // an <svg> element, black on white with a 4-module quiet zone (scanners need the white)
  const G = qrMatrix(text); if (!G) return null;
  const n = G.length, q = 4, ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${n + 2 * q} ${n + 2 * q}`); svg.setAttribute('width', px); svg.setAttribute('height', px); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'QR code to add Emvryx to your authenticator app'); svg.setAttribute('shape-rendering', 'crispEdges');
  const bg = document.createElementNS(ns, 'rect'); bg.setAttribute('width', n + 2 * q); bg.setAttribute('height', n + 2 * q); bg.setAttribute('fill', '#fff'); svg.append(bg);
  let d = ''; for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (G[r][c]) d += `M${c + q} ${r + q}h1v1h-1z`;
  const path = document.createElementNS(ns, 'path'); path.setAttribute('d', d); path.setAttribute('fill', '#000'); svg.append(path); return svg;
}
