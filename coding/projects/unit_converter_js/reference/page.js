// The browser side of the unit converter: fills the unit drop-downs and shows the result as the user types.
// It uses units(), convert() and format() from convert.js (loaded first by index.html).

// The page elements we read from and write to: the kind/from/to drop-downs, the number box, and the result line.
const kind = document.getElementById("kind"), from = document.getElementById("from"), to = document.getElementById("to");
const value = document.getElementById("value"), out = document.getElementById("result");

// Fill both unit drop-downs with the units of the chosen kind, then show a result.
function fill() {
  // Build the <option> tags as text, one per unit, and set them as the drop-down's contents.
  for (const sel of [from, to]) sel.innerHTML = units(kind.value).map((u) => `<option>${u}</option>`).join("");
  // Start with the second unit selected in "To" so From and To differ (otherwise the answer would just be the input).
  to.selectedIndex = 1;
  update();
}
// Recalculate and show "<number> <unit>", or show the error message (for example "below absolute zero") if conversion fails.
function update() {
  try { out.textContent = format(convert(Number(value.value), from.value, to.value)) + " " + to.value; }
  catch (e) { out.textContent = e.message; }
}
// Changing the kind refills the units; changing any unit or typing a number recalculates.
kind.onchange = fill;
[from, to, value].forEach((el) => el.addEventListener("input", update));
fill();
