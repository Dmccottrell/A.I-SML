"""
site_fx.py - The website's motion layer: a field of dashes that turn towards the pointer, headline and cards that rise into place as you
scroll, a menu that frosts over the page, a progress line, and cards with a light that follows the pointer.

WHAT THIS FILE DOES
    Holds the CSS and JavaScript that build_site.py adds to every page. It changes nothing in the page by itself: the script finds the
    headings and cards that are already there. Without JavaScript, or with "reduce motion" on, the page is just the plain page.
"""

FX_CSS = """
.fx-has body{background:transparent!important}
.fx-dots{position:fixed;inset:0;width:100%;height:100%;z-index:0;pointer-events:none}
.fx-has body>*:not(.fx-dots):not(.fx-bar):not(.theme-toggle):not(script){position:relative;z-index:1}
.nav{position:sticky;top:0;z-index:40;transition:background-color .3s ease,box-shadow .3s ease,backdrop-filter .3s ease}
.nav::before{content:'';position:absolute;top:0;bottom:0;left:50%;width:100vw;transform:translateX(-50%);z-index:-1;opacity:0;transition:opacity .3s ease;background:color-mix(in srgb,var(--bg) 72%,transparent);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);box-shadow:0 1px 0 var(--line)}
.fx-on .nav.fx-solid::before{opacity:1}
.fx-bar{position:fixed;left:0;top:0;height:3px;width:100%;transform-origin:0 50%;transform:scaleX(0);background:linear-gradient(90deg,var(--accent),var(--core,var(--accent)));z-index:60;pointer-events:none}
.fx-on .fx-r{opacity:0;transform:translate3d(0,34px,0) scale(.985);transition:opacity .8s cubic-bezier(.2,.7,.2,1),transform .8s cubic-bezier(.2,.7,.2,1);transition-delay:var(--fx-d,0ms);will-change:opacity,transform}
.fx-on .fx-r.fx-in{opacity:1;transform:none}
.fx-on .fx-w{display:inline-block;opacity:0;transform:translate3d(0,.55em,0);animation:fxWord .9s cubic-bezier(.2,.7,.2,1) forwards;animation-delay:calc(120ms + var(--i)*70ms)}
@keyframes fxWord{to{opacity:1;transform:none}}
.fx-card{position:relative;transition:transform .25s ease,border-color .25s ease}
.fx-card::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:opacity .25s ease;
  background:radial-gradient(320px circle at var(--mx,50%) var(--my,50%),color-mix(in srgb,var(--accent) 22%,transparent),transparent 65%)}
.fx-card:hover{border-color:color-mix(in srgb,var(--accent) 55%,var(--line))}
.fx-card:hover::after{opacity:1}
.fx-hero-in{will-change:transform,opacity}
@media (prefers-reduced-motion:reduce){.fx-on .fx-r,.fx-on .fx-w{opacity:1;transform:none;animation:none;transition:none}.fx-bar{display:none}}
"""

FX_JS = """<script>
(function () {
  var doc = document.documentElement, still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var cs = function (e) { return getComputedStyle(e); };
  /* ---- the dashes that turn to face the pointer */
  var canvas = document.createElement('canvas'); canvas.className = 'fx-dots'; canvas.setAttribute('aria-hidden', 'true'); document.body.prepend(canvas); doc.classList.add('fx-has');
  var ctx = canvas.getContext && canvas.getContext('2d');
  var w = 0, h = 0, mx = null, my = null, cx = 0, cy = 0, rgb = '245,165,36', GAP = 34, last = 0, fade = 1;
  function size() { var d = Math.min(window.devicePixelRatio || 1, 2); w = innerWidth; h = innerHeight; canvas.width = w * d; canvas.height = h * d; if (ctx) ctx.setTransform(d, 0, 0, d, 0, 0); }
  function colour() {
    var c = cs(doc).getPropertyValue('--accent').trim(), m = /^#([0-9a-f]{6})$/i.exec(c);
    rgb = m ? [1, 3, 5].map(function (i) { return parseInt(m[1].slice(i - 1, i + 1), 16); }).join(',') : '245,165,36';
  }
  function draw() {
    ctx.clearRect(0, 0, w, h);
    var R = Math.max(180, Math.min(w, h) * .38), light = doc.getAttribute('data-theme') === 'light', base = light ? .22 : .16;
    ctx.lineCap = 'round';
    for (var y = GAP / 2, row = 0; y < h; y += GAP, row++) for (var x = GAP / 2 + (row % 2) * GAP / 2; x < w; x += GAP) {
      var dx = cx - x, dy = cy - y, d = Math.hypot(dx, dy) || 1, near = Math.max(0, 1 - d / R), a = Math.atan2(dy, dx);
      var push = near * near * 16, px = x - dx / d * push, py = y - dy / d * push, len = 5 + near * 11;
      var ux = Math.cos(a) * len / 2, uy = Math.sin(a) * len / 2;
      ctx.strokeStyle = 'rgba(' + rgb + ',' + ((base + near * .8) * fade).toFixed(3) + ')';
      ctx.lineWidth = 1.4 + near * 1.6;
      ctx.beginPath(); ctx.moveTo(px - ux, py - uy); ctx.lineTo(px + ux, py + uy); ctx.stroke();
    }
  }
  function frame(now) {
    requestAnimationFrame(frame);
    var dt = Math.min(50, now - (last || now)); last = now;
    var tx, ty;
    if (mx === null) { var t = now / 1000; tx = w * (.5 + .36 * Math.sin(t * .33)); ty = h * (.38 + .3 * Math.sin(t * .27 + 1.3)); } else { tx = mx; ty = my; }
    var k = 1 - Math.exp(-dt / (mx === null ? 420 : 90)); cx += (tx - cx) * k; cy += (ty - cy) * k;
    draw();
  }
  if (ctx) {
    size(); colour(); cx = w / 2; cy = h * .4;
    addEventListener('resize', function () { size(); if (still) draw(); });
    addEventListener('pointermove', function (e) { mx = e.clientX; my = e.clientY; });
    document.addEventListener('pointerleave', function () { mx = null; });
    addEventListener('touchmove', function (e) { var t = e.touches[0]; if (t) { mx = t.clientX; my = t.clientY; } }, {passive: true});
    new MutationObserver(colour).observe(doc, {attributes: true, attributeFilter: ['data-theme', 'style']});
    if (still) draw(); else requestAnimationFrame(frame);
  }
  /* page wrappers that paint the page colour themselves would hide the dashes: let the page colour show through */
  var pageBg = cs(doc).backgroundColor;
  Array.prototype.slice.call(document.body.querySelectorAll('div,section,main,header')).forEach(function (e) {
    var r = e.getBoundingClientRect();
    if (r.width >= innerWidth * .9 && cs(e).backgroundColor === pageBg) e.style.backgroundColor = 'transparent';
  });
  if (still) return;
  doc.classList.add('fx-on');
  /* ---- headline words rise one after another */
  var h1 = document.querySelector('h1');
  if (h1 && !h1.querySelector('*:not(em)')) {
    var i = 0;
    (function split(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (n) {
        if (n.nodeType === 3) {
          var frag = document.createDocumentFragment();
          n.textContent.split(/(\\s+)/).forEach(function (part) {
            if (!part) return;
            if (/^\\s+$/.test(part)) { frag.appendChild(document.createTextNode(' ')); return; }
            var s = document.createElement('span'); s.className = 'fx-w'; s.style.setProperty('--i', i++); s.textContent = part; frag.appendChild(s);
          });
          node.replaceChild(frag, n);
        } else if (n.nodeType === 1) split(n);
      });
    })(h1);
  }
  /* ---- things rise into place as they are scrolled to */
  var cards = [];
  Array.prototype.slice.call(document.querySelectorAll('div,a,li,section,article')).forEach(function (e) {
    var s = cs(e), r = e.getBoundingClientRect();
    if (parseFloat(s.borderTopWidth) > 0 && parseFloat(s.borderTopLeftRadius) >= 14 && r.height > 56 && r.width > 120 && !e.closest('.nav') && !cards.some(function (c) { return c.contains(e); })) cards.push(e);
  });
  cards.forEach(function (c) {
    c.classList.add('fx-card');
    c.addEventListener('pointermove', function (ev) { var b = c.getBoundingClientRect(); c.style.setProperty('--mx', (ev.clientX - b.left) + 'px'); c.style.setProperty('--my', (ev.clientY - b.top) + 'px'); });
  });
  var targets = Array.prototype.slice.call(document.querySelectorAll('h2,h3,.doc > *')).filter(function (e) { return !e.closest('.nav') && !cards.some(function (c) { return c.contains(e); }); }).concat(cards);
  var seen = new Map();
  targets.forEach(function (e) {
    var p = e.parentElement, n = seen.get(p) || 0; seen.set(p, n + 1);
    e.classList.add('fx-r'); e.style.setProperty('--fx-d', Math.min(n, 5) * 90 + 'ms');
  });
  var io = new IntersectionObserver(function (list) {
    list.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add('fx-in'); io.unobserve(en.target); } });
  }, {rootMargin: '0px 0px -8% 0px', threshold: .08});
  targets.forEach(function (e) { io.observe(e); });
  setTimeout(function () { targets.forEach(function (e) { var r = e.getBoundingClientRect(); if (r.top < innerHeight) e.classList.add('fx-in'); }); }, 2500);   // never leave anything hidden
  /* ---- scroll: progress line, frosted menu, hero drifting away, dashes dimming */
  var bar = document.createElement('div'); bar.className = 'fx-bar'; document.body.appendChild(bar);
  var nav = document.querySelector('.nav'), heroBlock = h1 && (h1.closest('section') || h1.parentElement), ticking = false;
  if (heroBlock) heroBlock.classList.add('fx-hero-in');
  function onScroll() {
    var y = window.pageYOffset, max = Math.max(1, doc.scrollHeight - innerHeight);
    bar.style.transform = 'scaleX(' + Math.min(1, y / max).toFixed(4) + ')';
    if (nav) nav.classList.toggle('fx-solid', y > 24);
    fade = Math.max(.35, 1 - y / (innerHeight * 1.3));
    if (heroBlock) { var p = Math.min(1, y / (innerHeight * .9)); heroBlock.style.transform = 'translate3d(0,' + (y * .22).toFixed(1) + 'px,0)'; heroBlock.style.opacity = (1 - p * .85).toFixed(3); }
    ticking = false;
  }
  addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, {passive: true});
  onScroll();
})();
</script>"""
