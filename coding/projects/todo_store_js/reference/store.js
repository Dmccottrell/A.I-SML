// The data layer of the to-do app (reference solution for the "todo_store_js" exercise): a "store" that keeps the task list,
// changes it, and saves it. It never touches the page, so it can be tested in Node.js. app.js uses it in the browser.

// createStore(storage) builds a store. `storage` is anything with getItem(key) and setItem(key, text) -
// in the browser that is window.localStorage (small data the browser remembers); tests pass a fake one.
function createStore(storage) {
  // state: the next id to hand out, and the list of items {id, text, done}.
  let state = { nextId: 1, items: [] };
  try {
    // Load earlier data if there is any. JSON.parse turns the saved text back into an object.
    const saved = JSON.parse(storage.getItem("todos"));
    // Only trust it if it has the right shape; anything else is ignored.
    if (saved && Array.isArray(saved.items) && Number.isInteger(saved.nextId)) state = saved;
  } catch (e) { /* broken value: start empty */ }

  // Write the whole state to storage as text (JSON). Called after every change.
  const save = () => storage.setItem("todos", JSON.stringify(state));
  // Tidy a piece of text: turn null/undefined into "", cut spaces at both ends, and refuse an empty result.
  const clean = (text) => {
    const t = String(text == null ? "" : text).trim();
    if (!t) throw new Error("text is empty");
    return t;
  };
  // Find an item by id, or throw an error if there is none.
  const find = (id) => {
    const item = state.items.find((i) => i.id === id);
    if (!item) throw new Error("no item " + id);
    return item;
  };

  // The public methods. Methods that return an item return a COPY ({ ...item }) so callers cannot change the stored data by accident.
  return {
    // Add a task with the cleaned text; ids count up and are never reused. Returns the new item.
    add(text) {
      const item = { id: state.nextId++, text: clean(text), done: false };
      state.items.push(item);
      save();
      return { ...item };
    },
    // Flip a task between done and not done. Unknown id throws.
    toggle(id) { const it = find(id); it.done = !it.done; save(); return { ...it }; },
    // Change a task's text (empty text or unknown id throws).
    edit(id, text) { const it = find(id); it.text = clean(text); save(); return { ...it }; },
    // Delete a task. find() first so an unknown id throws.
    remove(id) { find(id); state.items = state.items.filter((i) => i.id !== id); save(); },
    // The tasks, filtered by "all" (default), "done" or "active" (anything else counts as not done), as copies.
    list(filter = "all") {
      return state.items.filter((i) => filter === "all" || (filter === "done" ? i.done : !i.done)).map((i) => ({ ...i }));
    },
    // Delete every finished task and return how many were removed.
    clearDone() {
      const before = state.items.length;
      state.items = state.items.filter((i) => !i.done);
      save();
      return before - state.items.length;
    },
    // How many tasks in total, still to do, and finished.
    counts() {
      const done = state.items.filter((i) => i.done).length;
      return { all: state.items.length, active: state.items.length - done, done };
    },
  };
}

// In a browser there is no "module", so this does nothing there; in Node.js (the tests) it exports createStore.
if (typeof module !== "undefined") module.exports = { createStore };
