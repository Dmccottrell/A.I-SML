const store = createStore(window.localStorage);
let filter = "all";
const list = document.getElementById("list");

function render() {
  list.innerHTML = "";
  for (const item of store.list(filter)) {
    const li = document.createElement("li");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = item.done;
    box.setAttribute("aria-label", "done");
    box.onchange = () => { store.toggle(item.id); render(); };
    const span = document.createElement("span");
    span.textContent = item.text;
    const edit = document.createElement("button");
    edit.textContent = "Edit";
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

document.getElementById("add-form").onsubmit = (e) => {
  e.preventDefault();
  const input = document.getElementById("text");
  if (input.value.trim()) { store.add(input.value); input.value = ""; render(); }
};
document.querySelectorAll("[data-filter]").forEach((b) => { b.onclick = () => { filter = b.dataset.filter; render(); }; });
document.getElementById("clear").onclick = () => { store.clearDone(); render(); };
render();
