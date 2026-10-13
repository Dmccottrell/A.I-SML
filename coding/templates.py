"""
templates.py - VryxCode starters: a small working project the model fills in, instead of a blank folder.

A small model does much better when it edits a page that already runs than when it writes everything from nothing: the structure is fixed, so its steps are
"change this", "add that" and every step can be checked in the preview. Each starter is plain HTML, CSS and JavaScript (no build step) and opens straight in the
Preview tab.

    list_templates()                  -> [{"id", "name", "icon", "desc", "idea"}] for the page
    apply(folder, id)                 -> the names of the files written (a file that already exists is never overwritten)
    task_for(id, idea)                -> the task the model gets: the starter's files are already there, make them into the idea
"""
import os

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<main>
{body}
</main>
<script src="app.js"></script>
</body>
</html>
"""

_CSS = """* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: system-ui, sans-serif; background: #12111a; color: #f2f0ff; }
main { width: min(92vw, 420px); padding: 24px; border-radius: 18px; background: #1d1b2b; box-shadow: 0 12px 40px rgba(0, 0, 0, .35); }
h1 { margin: 0 0 14px; font-size: 1.4rem; }
button { border: 0; border-radius: 10px; padding: 10px 14px; font: inherit; background: #8b5cf6; color: #fff; cursor: pointer; }
input { border: 1px solid #3a3752; border-radius: 10px; padding: 10px 12px; font: inherit; background: #12111a; color: inherit; }
ul { list-style: none; margin: 14px 0 0; padding: 0; }
"""

TEMPLATES = {
    "todo": {
        "name": "To-do list", "icon": "✅", "desc": "Add, tick off and delete tasks. Saved in the browser.", "idea": "a to-do list I can add, tick off and delete tasks in",
        "files": {
            "index.html": _PAGE.format(title="To-do list", body='<h1>To-do list</h1>\n<form id="add"><input id="text" placeholder="What needs doing?" autocomplete="off"> <button>Add</button></form>\n<ul id="list"></ul>'),
            "style.css": _CSS + "li { display: flex; gap: 8px; align-items: center; padding: 8px 0; border-bottom: 1px solid #2d2a40; }\nli.done span { text-decoration: line-through; opacity: .5; }\nli span { flex: 1; }\n",
            "app.js": """let tasks = JSON.parse(localStorage.getItem('tasks') || '[]');
const list = document.getElementById('list');
function save() { localStorage.setItem('tasks', JSON.stringify(tasks)); render(); }
function render() {
  list.replaceChildren(...tasks.map((t, i) => {
    const li = document.createElement('li'); li.className = t.done ? 'done' : '';
    const box = document.createElement('input'); box.type = 'checkbox'; box.checked = t.done; box.onchange = () => { t.done = box.checked; save(); };
    const label = document.createElement('span'); label.textContent = t.text;
    const del = document.createElement('button'); del.textContent = '\\u00d7'; del.onclick = () => { tasks.splice(i, 1); save(); };
    li.append(box, label, del); return li;
  }));
}
document.getElementById('add').onsubmit = (e) => {
  e.preventDefault(); const text = document.getElementById('text').value.trim();
  if (text) { tasks.push({text, done: false}); document.getElementById('text').value = ''; save(); }
};
render();
""",
        },
    },
    "timer": {
        "name": "Focus timer", "icon": "⏱", "desc": "A countdown with start, pause and reset.", "idea": "a focus timer with 25 and 5 minute rounds and a progress ring",
        "files": {
            "index.html": _PAGE.format(title="Focus timer", body='<h1>Focus timer</h1>\n<div id="time">25:00</div>\n<p><button id="go">Start</button> <button id="reset">Reset</button></p>'),
            "style.css": _CSS + "#time { font-size: 4rem; font-variant-numeric: tabular-nums; text-align: center; margin: 12px 0; }\np { text-align: center; }\n",
            "app.js": """const LENGTH = 25 * 60;
let left = LENGTH, timer = null;
const show = () => { document.getElementById('time').textContent = String(Math.floor(left / 60)).padStart(2, '0') + ':' + String(left % 60).padStart(2, '0'); };
function tick() { left -= 1; show(); if (left <= 0) { clearInterval(timer); timer = null; document.getElementById('go').textContent = 'Start'; } }
document.getElementById('go').onclick = (e) => {
  if (timer) { clearInterval(timer); timer = null; e.target.textContent = 'Start'; }
  else { timer = setInterval(tick, 1000); e.target.textContent = 'Pause'; }
};
document.getElementById('reset').onclick = () => { clearInterval(timer); timer = null; left = LENGTH; document.getElementById('go').textContent = 'Start'; show(); };
show();
""",
        },
    },
    "calculator": {
        "name": "Calculator", "icon": "\U0001f9ee", "desc": "Digits, the four operations and clear.", "idea": "a calculator with big buttons that works well on a phone",
        "files": {
            "index.html": _PAGE.format(title="Calculator", body='<h1>Calculator</h1>\n<div id="screen">0</div>\n<div id="keys"></div>'),
            "style.css": _CSS + "#screen { font-size: 2.4rem; text-align: right; padding: 12px; background: #12111a; border-radius: 12px; margin-bottom: 12px; overflow: hidden; }\n#keys { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }\n#keys button { padding: 16px 0; font-size: 1.2rem; }\n",
            "app.js": """const keys = ['7', '8', '9', '/', '4', '5', '6', '*', '1', '2', '3', '-', '0', '.', '=', '+', 'C'];
const screen = document.getElementById('screen');
let text = '';
function press(k) {
  if (k === 'C') text = '';
  else if (k === '=') { try { text = String(Function('"use strict"; return (' + (text || '0') + ')')()); } catch (e) { text = ''; } }
  else text += k;
  screen.textContent = text || '0';
}
document.getElementById('keys').replaceChildren(...keys.map((k) => { const b = document.createElement('button'); b.textContent = k; b.onclick = () => press(k); return b; }));
""",
        },
    },
    "landing": {
        "name": "Landing page", "icon": "\U0001f310", "desc": "A page with a headline, three features and a sign-up button.", "idea": "a landing page for my idea, with a headline, three features and a sign-up button",
        "files": {
            "index.html": _PAGE.format(title="My product", body='<h1>Your headline goes here</h1>\n<p>One sentence about what it does and who it is for.</p>\n<ul id="features"></ul>\n<p><button id="cta">Sign up</button></p>'),
            "style.css": _CSS + "main { width: min(94vw, 640px); }\nli { padding: 12px 0; border-bottom: 1px solid #2d2a40; }\n",
            "app.js": """const features = ['First feature', 'Second feature', 'Third feature'];
document.getElementById('features').replaceChildren(...features.map((f) => { const li = document.createElement('li'); li.textContent = f; return li; }));
document.getElementById('cta').onclick = () => alert('Thanks! Sign-ups are not connected yet.');
""",
        },
    },
    "game": {
        "name": "Mini game", "icon": "\U0001f3ae", "desc": "A canvas game with a score: catch the falling dots.", "idea": "a small game with a score, played with touch or the arrow keys",
        "files": {
            "index.html": _PAGE.format(title="Mini game", body='<h1>Catch the dots</h1>\n<p id="score">Score: 0</p>\n<canvas id="c" width="360" height="420"></canvas>'),
            "style.css": _CSS + "canvas { width: 100%; background: #12111a; border-radius: 12px; touch-action: none; }\n",
            "app.js": """const canvas = document.getElementById('c'), g = canvas.getContext('2d');
let x = 180, dots = [], score = 0;
function move(clientX) { const r = canvas.getBoundingClientRect(); x = (clientX - r.left) * canvas.width / r.width; }
canvas.addEventListener('pointermove', (e) => move(e.clientX));
addEventListener('keydown', (e) => { if (e.key === 'ArrowLeft') x -= 20; if (e.key === 'ArrowRight') x += 20; });
function frame() {
  if (Math.random() < 0.04) dots.push({x: Math.random() * canvas.width, y: 0});
  g.clearRect(0, 0, canvas.width, canvas.height);
  g.fillStyle = '#8b5cf6'; g.fillRect(x - 30, canvas.height - 20, 60, 12);
  dots = dots.filter((d) => {
    d.y += 3; g.beginPath(); g.arc(d.x, d.y, 8, 0, 7); g.fillStyle = '#c4b5fd'; g.fill();
    if (d.y > canvas.height - 24 && Math.abs(d.x - x) < 34) { score += 1; document.getElementById('score').textContent = 'Score: ' + score; return false; }
    return d.y < canvas.height;
  });
  requestAnimationFrame(frame);
}
frame();
""",
        },
    },
}


def list_templates():
    return [{"id": k, "name": v["name"], "icon": v["icon"], "desc": v["desc"], "idea": v["idea"]} for k, v in TEMPLATES.items()]


def apply(folder, template_id):
    """Write the starter's files into `folder` (made if needed). Files that already exist are left alone. Returns the names written."""
    t = TEMPLATES.get(str(template_id or ""))
    if not t:
        return []
    os.makedirs(folder, exist_ok=True)
    written = []
    for rel, text in t["files"].items():
        full = os.path.join(folder, rel)
        if os.path.exists(full):
            continue
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written.append(rel)
    return written


def task_for(template_id, idea=""):
    t = TEMPLATES.get(str(template_id or ""))
    idea = str(idea or "").strip()
    if not t:
        return idea
    files = ", ".join(t["files"])
    return (f'This project already has the "{t["name"]}" starter ({files}), and it runs as it is. Do not start from scratch: read the files, then change them one small step at a time '
            f'to make: {idea or t["idea"]}. Keep the file names. Check the page after your changes.')
