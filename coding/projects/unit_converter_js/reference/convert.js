const IN = 0.0254;
const FACTORS = {
  length: { mm: 0.001, cm: 0.01, m: 1, km: 1000, in: IN, ft: 12 * IN, yd: 36 * IN, mi: 63360 * IN },
  mass: { g: 1, kg: 1000, oz: 453.59237 / 16, lb: 453.59237 },
};
const TEMPS = ["C", "F", "K"];

function kindOf(unit) {
  for (const kind of Object.keys(FACTORS)) if (unit in FACTORS[kind]) return kind;
  if (TEMPS.includes(unit)) return "temperature";
  return null;
}

function units(kind) {
  if (kind === "temperature") return TEMPS.slice();
  if (!(kind in FACTORS)) throw new Error("unknown kind " + kind);
  return Object.keys(FACTORS[kind]);
}

function toKelvin(v, u) { return u === "K" ? v : u === "C" ? v + 273.15 : (v - 32) * 5 / 9 + 273.15; }
function fromKelvin(k, u) { return u === "K" ? k : u === "C" ? k - 273.15 : (k - 273.15) * 9 / 5 + 32; }

function convert(value, from, to) {
  const a = kindOf(from), b = kindOf(to);
  if (!a || !b || a !== b) throw new Error(`cannot convert ${from} to ${to}`);
  if (a === "temperature") {
    const k = toKelvin(value, from);
    if (k < -1e-9) throw new Error("below absolute zero");
    return fromKelvin(k, to);
  }
  return value * FACTORS[a][from] / FACTORS[a][to];
}

function format(n) {
  const s = (Math.round(n * 10000) / 10000).toFixed(4).replace(/\.?0+$/, "");
  return s === "-0" ? "0" : s;
}

if (typeof module !== "undefined") module.exports = { convert, units, format };
