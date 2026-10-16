function createStore(storage) {
  let state = { nextId: 1, items: [] };
  try {
    const saved = JSON.parse(storage.getItem("todos"));
    if (saved && Array.isArray(saved.items) && Number.isInteger(saved.nextId)) state = saved;
  } catch (e) { /* broken value: start empty */ }

  const save = () => storage.setItem("todos", JSON.stringify(state));
  const clean = (text) => {
    const t = String(text == null ? "" : text).trim();
    if (!t) throw new Error("text is empty");
    return t;
  };
  const find = (id) => {
    const item = state.items.find((i) => i.id === id);
    if (!item) throw new Error("no item " + id);
    return item;
  };

  return {
    add(text) {
      const item = { id: state.nextId++, text: clean(text), done: false };
      state.items.push(item);
      save();
      return { ...item };
    },
    toggle(id) { const it = find(id); it.done = !it.done; save(); return { ...it }; },
    edit(id, text) { const it = find(id); it.text = clean(text); save(); return { ...it }; },
    remove(id) { find(id); state.items = state.items.filter((i) => i.id !== id); save(); },
    list(filter = "all") {
      return state.items.filter((i) => filter === "all" || (filter === "done" ? i.done : !i.done)).map((i) => ({ ...i }));
    },
    clearDone() {
      const before = state.items.length;
      state.items = state.items.filter((i) => !i.done);
      save();
      return before - state.items.length;
    },
    counts() {
      const done = state.items.filter((i) => i.done).length;
      return { all: state.items.length, active: state.items.length - done, done };
    },
  };
}

if (typeof module !== "undefined") module.exports = { createStore };
