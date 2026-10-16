const kind = document.getElementById("kind"), from = document.getElementById("from"), to = document.getElementById("to");
const value = document.getElementById("value"), out = document.getElementById("result");

function fill() {
  for (const sel of [from, to]) sel.innerHTML = units(kind.value).map((u) => `<option>${u}</option>`).join("");
  to.selectedIndex = 1;
  update();
}
function update() {
  try { out.textContent = format(convert(Number(value.value), from.value, to.value)) + " " + to.value; }
  catch (e) { out.textContent = e.message; }
}
kind.onchange = fill;
[from, to, value].forEach((el) => el.addEventListener("input", update));
fill();
