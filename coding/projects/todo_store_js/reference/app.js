// The browser side of the to-do app: draws the list from the store and wires up the buttons and the form.
// It uses createStore() from store.js (loaded first by index.html).

// Use the browser's localStorage so tasks survive a page reload.
const store = createStore(window.localStorage);
// Which tasks are shown: "all", "active" or "done".
let filter = "all";
const list = document.getElementById("list");

// Rebuild the visible list from the store, then update the counts line. Called after every change.
function render() {
  list.innerHTML = "";
  for (const item of store.list(filter)) {
    // Each task is a list row with a checkbox, the text, and Edit and Delete buttons.
    const li = document.createElement("li");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = item.done;
    box.setAttribute("aria-label", "done");
    box.onchange = () => { store.toggle(item.id); render(); };
    const span = document.createElement("span");
    // textContent (not innerHTML) so task text is never treated as HTML.
    span.textContent = item.text;
    const edit = document.createElement("button");
    edit.textContent = "Edit";
    // prompt() shows the browser's small "type here" box; nothing is changed if the user cancels or leaves it blank.
    edit.onclick = () => { const t = prompt("Edit", item.text); if (t && t.trim()) { store.edit(item.id, t); render(); } };
    const del = document.createElement("button");
    del.textContent = "Delete";
    del.onclick = () => { store.remove(item.id); render(); };
    li.append(box, span, edit, del);
    list.appendChild(li);
  }
  const c = store.counts();
  document.getElementById("counts").textContent = `${c.active} active, ${c.done} done`;
}

// Add form: stop the browser's normal "reload the page on submit" (preventDefault), add the task if it is not blank, clear the box.
document.getElementById("add-form").onsubmit = (e) => {
  e.preventDefault();
  const input = document.getElementById("text");
  if (input.value.trim()) { store.add(input.value); input.value = ""; render(); }
};
// The All / Active / Done buttons each carry their filter name in a data-filter attribute.
document.querySelectorAll("[data-filter]").forEach((b) => { b.onclick = () => { filter = b.dataset.filter; render(); }; });
// "Clear done" button, then show the list for the first time.
document.getElementById("clear").onclick = () => { store.clearDone(); render(); };
render();
