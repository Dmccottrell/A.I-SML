// Hidden checks for the "todo_store_js" coding exercise. The agent never sees this file; it is run afterwards with Node.js
// to decide whether the agent's store.js works. It prints PASS/FAIL per test and exits with code 1 if any failed.
const assert = require("assert");
const path = require("path");
// Load the agent's store.js that sits next to this file.
const { createStore } = require(path.join(__dirname, "store.js"));
let passed = 0, failed = 0;
// A tiny test runner: run fn; if it throws (a failed assert), count and print a FAIL line, otherwise a PASS line.
function test(name, fn) {
  try { fn(); passed++; console.log("PASS " + name); } catch (e) { failed++; console.log("FAIL " + name + ": " + e.message); }
}
// A fake localStorage kept in a plain object. fake() starts empty; fake(text) starts with that text saved under "todos".
// The `data` object is exposed so tests can look at exactly what was saved. Real storage keeps only text, hence String(v).
function fake(initial) {
  const data = initial === undefined ? {} : { todos: initial };
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); } };
}

// add() trims the text, gives ids from 1, keeps order, and refuses blank text.
test("add and list", () => {
  const s = createStore(fake());
  assert.deepStrictEqual(s.add("  milk "), { id: 1, text: "milk", done: false });
  s.add("eggs");
  assert.deepStrictEqual(s.list().map((i) => i.text), ["milk", "eggs"]);
  assert.throws(() => s.add("   "));
});
// Toggling flips done; list("done"/"active") filter; counts() adds up.
test("toggle, filters, counts", () => {
  const s = createStore(fake());
  s.add("a"); s.add("b"); s.add("c");
  s.toggle(2);
  assert.deepStrictEqual(s.list("done").map((i) => i.id), [2]);
  assert.deepStrictEqual(s.list("active").map((i) => i.id), [1, 3]);
  assert.deepStrictEqual(s.counts(), { all: 3, active: 2, done: 1 });
  s.toggle(2);
  assert.deepStrictEqual(s.counts(), { all: 3, active: 3, done: 0 });
});
// edit() trims and rejects blank text; unknown ids throw; after removing id 2 the next new item gets 3, not 2.
test("edit, remove, unknown ids, no reuse", () => {
  const s = createStore(fake());
  s.add("a"); s.add("b");
  s.edit(1, " A ");
  assert.strictEqual(s.list()[0].text, "A");
  assert.throws(() => s.edit(1, ""));
  s.remove(2);
  assert.throws(() => s.remove(2));
  assert.throws(() => s.toggle(9));
  assert.strictEqual(s.add("c").id, 3);
});
// clearDone() removes finished tasks (here 1 and 3), returns how many (2), and leaves the rest.
test("clearDone", () => {
  const s = createStore(fake());
  s.add("a"); s.add("b"); s.add("c");
  s.toggle(1); s.toggle(3);
  assert.strictEqual(s.clearDone(), 2);
  assert.deepStrictEqual(s.list().map((i) => i.text), ["b"]);
});
// Every change is saved as JSON under "todos" ({nextId, items}); a new store on the same storage sees the data and
// carries on counting ids; and a broken saved value does not crash, it just gives an empty list.
test("saves and loads", () => {
  const st = fake();
  const s = createStore(st);
  s.add("keep me"); s.add("x"); s.toggle(1); s.remove(2);
  const saved = JSON.parse(st.data.todos);
  assert.strictEqual(saved.nextId, 3);
  assert.deepStrictEqual(saved.items, [{ id: 1, text: "keep me", done: true }]);
  const again = createStore(st);
  assert.deepStrictEqual(again.list(), [{ id: 1, text: "keep me", done: true }]);
  assert.strictEqual(again.add("new").id, 3);
  assert.deepStrictEqual(createStore(fake("{broken")).list(), []);
});
console.log(`passed ${passed} of ${passed + failed}`);
// A non-zero exit code tells whoever ran this file that something failed.
process.exit(failed ? 1 : 0);
