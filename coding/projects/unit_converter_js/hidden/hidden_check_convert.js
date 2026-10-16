const assert = require("assert");
const path = require("path");
const { convert, units, format } = require(path.join(__dirname, "convert.js"));
let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log("PASS " + name); } catch (e) { failed++; console.log("FAIL " + name + ": " + e.message); }
}
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-6 * Math.max(1, Math.abs(b)), `${a} is not ${b}`);

test("units", () => {
  assert.deepStrictEqual(units("length"), ["mm", "cm", "m", "km", "in", "ft", "yd", "mi"]);
  assert.deepStrictEqual(units("mass"), ["g", "kg", "oz", "lb"]);
  assert.deepStrictEqual(units("temperature"), ["C", "F", "K"]);
  assert.throws(() => units("time"));
});
test("length", () => {
  near(convert(1, "in", "cm"), 2.54);
  near(convert(1, "mi", "km"), 1.609344);
  near(convert(3, "ft", "yd"), 1);
  near(convert(2500, "mm", "m"), 2.5);
});
test("mass", () => {
  near(convert(1, "lb", "oz"), 16);
  near(convert(1, "kg", "lb"), 2.2046226218);
});
test("temperature", () => {
  near(convert(100, "C", "F"), 212);
  near(convert(32, "F", "C"), 0);
  near(convert(0, "K", "C"), -273.15);
  assert.throws(() => convert(-300, "C", "K"));
});
test("errors", () => {
  assert.throws(() => convert(1, "kg", "m"), /cannot convert/);
  assert.throws(() => convert(1, "furlong", "m"), /cannot convert/);
});
test("format", () => {
  assert.strictEqual(format(2.5), "2.5");
  assert.strictEqual(format(1 / 3), "0.3333");
  assert.strictEqual(format(5), "5");
  assert.strictEqual(format(-0.00001), "0");
  assert.strictEqual(format(1234.56789), "1234.5679");
});
console.log(`passed ${passed} of ${passed + failed}`);
process.exit(failed ? 1 : 0);
