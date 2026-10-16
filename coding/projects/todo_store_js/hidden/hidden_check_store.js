const assert = require("assert");
const path = require("path");
const { createStore } = require(path.join(__dirname, "store.js"));
let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log("PASS " + name); } catch (e) { failed++; console.log("FAIL " + name + ": " + e.message); }
}
function fake(initial) {
  const data = initial === undefined ? {} : { todos: initial };
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); } };
}

test("add and list", () => {
  const s = createStore(fake());
  assert.deepStrictEqual(s.add("  milk "), { id: 1, text: "milk", done: false });
  s.add("eggs");
  assert.deepStrictEqual(s.list().map((i) => i.text), ["milk", "eggs"]);
  assert.throws(() => s.add("   "));
});
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
test("clearDone", () => {
  const s = createStore(fake());
  s.add("a"); s.add("b"); s.add("c");
  s.toggle(1); s.toggle(3);
  assert.strictEqual(s.clearDone(), 2);
  assert.deepStrictEqual(s.list().map((i) => i.text), ["b"]);
});
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
process.exit(failed ? 1 : 0);
