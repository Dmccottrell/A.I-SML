// Hidden checks for the "unit_converter_js" coding exercise. The agent never sees this file; it is run afterwards with Node.js
// to decide whether the agent's convert.js works. It prints PASS/FAIL per test and exits with code 1 if any failed.
const assert = require("assert");
const path = require("path");
// Load the agent's convert.js that sits next to this file.
const { convert, units, format } = require(path.join(__dirname, "convert.js"));
let passed = 0, failed = 0;
// A tiny test runner: run fn; if it throws (a failed assert), count and print a FAIL line, otherwise a PASS line.
function test(name, fn) {
  try { fn(); passed++; console.log("PASS " + name); } catch (e) { failed++; console.log("FAIL " + name + ": " + e.message); }
}
// "Nearly equal": decimals are never exact, so allow a relative error of one in a million (and an absolute one for numbers under 1).
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-6 * Math.max(1, Math.abs(b)), `${a} is not ${b}`);

// units(kind) returns the exact lists in this order, and an unknown kind throws.
test("units", () => {
  assert.deepStrictEqual(units("length"), ["mm", "cm", "m", "km", "in", "ft", "yd", "mi"]);
  assert.deepStrictEqual(units("mass"), ["g", "kg", "oz", "lb"]);
  assert.deepStrictEqual(units("temperature"), ["C", "F", "K"]);
  assert.throws(() => units("time"));
});
// Well-known length facts: 1 inch = 2.54 cm, 1 mile = 1.609344 km, 3 ft = 1 yd, 2500 mm = 2.5 m.
test("length", () => {
  near(convert(1, "in", "cm"), 2.54);
  near(convert(1, "mi", "km"), 1.609344);
  near(convert(3, "ft", "yd"), 1);
  near(convert(2500, "mm", "m"), 2.5);
});
// 1 pound = 16 ounces; 1 kg is about 2.2046 pounds.
test("mass", () => {
  near(convert(1, "lb", "oz"), 16);
  near(convert(1, "kg", "lb"), 2.2046226218);
});
// Boiling point 100 C = 212 F, freezing 32 F = 0 C, 0 K = -273.15 C; -300 C is below absolute zero so it must throw.
test("temperature", () => {
  near(convert(100, "C", "F"), 212);
  near(convert(32, "F", "C"), 0);
  near(convert(0, "K", "C"), -273.15);
  assert.throws(() => convert(-300, "C", "K"));
});
// Mixing kinds (kg to m) or using an unknown unit must throw an error whose message contains "cannot convert".
test("errors", () => {
  assert.throws(() => convert(1, "kg", "m"), /cannot convert/);
  assert.throws(() => convert(1, "furlong", "m"), /cannot convert/);
});
// format rounds to 4 decimals without trailing zeros, never prints "-0".
test("format", () => {
  assert.strictEqual(format(2.5), "2.5");
  assert.strictEqual(format(1 / 3), "0.3333");
  assert.strictEqual(format(5), "5");
  assert.strictEqual(format(-0.00001), "0");
  assert.strictEqual(format(1234.56789), "1234.5679");
});
console.log(`passed ${passed} of ${passed + failed}`);
// A non-zero exit code tells whoever ran this file that something failed.
process.exit(failed ? 1 : 0);
