// The conversion maths for the unit converter (reference solution for the "unit_converter_js" exercise).
// No page code here, so it can be tested in Node.js. page.js uses it in the browser.

// One inch in metres. Imperial lengths (in, ft, yd, mi) are written as multiples of it so they stay exact.
const IN = 0.0254;
// For each kind, every unit's size measured in a base unit: lengths in metres, masses in grams.
// Example: 1 km = 1000 m, 1 lb = 453.59237 g, 1 oz = a sixteenth of a pound.
const FACTORS = {
  length: { mm: 0.001, cm: 0.01, m: 1, km: 1000, in: IN, ft: 12 * IN, yd: 36 * IN, mi: 63360 * IN },
  mass: { g: 1, kg: 1000, oz: 453.59237 / 16, lb: 453.59237 },
};
// Temperature units: Celsius, Fahrenheit, Kelvin. They cannot use a simple factor (they have offsets), so they are handled separately.
const TEMPS = ["C", "F", "K"];

// Which kind does this unit belong to? Returns "length", "mass", "temperature", or null if the unit is unknown.
function kindOf(unit) {
  // "unit in FACTORS[kind]" asks whether the object has a key with that name.
  for (const kind of Object.keys(FACTORS)) if (unit in FACTORS[kind]) return kind;
  if (TEMPS.includes(unit)) return "temperature";
  return null;
}

// List the unit names for a kind, in a fixed order. An unknown kind throws an error. Temperature returns a copy of the list.
function units(kind) {
  if (kind === "temperature") return TEMPS.slice();
  if (!(kind in FACTORS)) throw new Error("unknown kind " + kind);
  return Object.keys(FACTORS[kind]);
}

// Temperature is converted via Kelvin: first any unit to Kelvin, then Kelvin to any unit.
// (Chained ?: reads "if u is K ... else if u is C ... else it must be F".)
// Celsius to Kelvin adds 273.15; Fahrenheit to Kelvin subtracts 32, scales by 5/9, then adds 273.15.
function toKelvin(v, u) { return u === "K" ? v : u === "C" ? v + 273.15 : (v - 32) * 5 / 9 + 273.15; }
function fromKelvin(k, u) { return u === "K" ? k : u === "C" ? k - 273.15 : (k - 273.15) * 9 / 5 + 32; }

// Convert `value` from unit `from` to unit `to` and return the number.
// Throws "cannot convert ..." for unknown units or units of different kinds (kg to m), and "below absolute zero"
// for a temperature colder than 0 Kelvin, which cannot exist.
function convert(value, from, to) {
  const a = kindOf(from), b = kindOf(to);
  if (!a || !b || a !== b) throw new Error(`cannot convert ${from} to ${to}`);
  if (a === "temperature") {
    const k = toKelvin(value, from);
    // Allow a hair below zero (-1e-9) so tiny rounding errors on exactly 0 K are not reported as errors.
    if (k < -1e-9) throw new Error("below absolute zero");
    return fromKelvin(k, to);
  }
  // Other kinds: go to the base unit (multiply by the "from" factor), then to the target unit (divide by the "to" factor).
  return value * FACTORS[a][from] / FACTORS[a][to];
}

// Make a number nice to show: round to 4 decimals and drop useless trailing zeros (2.5000 -> "2.5", 5 -> "5").
function format(n) {
  // Math.round(n * 10000) / 10000 rounds to 4 places; toFixed(4) writes exactly 4 decimals; the regex (text pattern)
  // /\.?0+$/ then removes an optional "." plus the zeros at the very end of the text.
  const s = (Math.round(n * 10000) / 10000).toFixed(4).replace(/\.?0+$/, "");
  // A tiny negative number rounds to "-0"; show it as plain "0".
  return s === "-0" ? "0" : s;
}

// In a browser there is no "module", so this does nothing there; in Node.js (the tests) it exports the functions.
if (typeof module !== "undefined") module.exports = { convert, units, format };
