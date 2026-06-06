// Responsive off-canvas sidebar. Injects a hamburger into the topbar + a scrim,
// and toggles `.nav-open` on `.app`. The drawer transform lives in app.css (≤880px).
// Loaded on every app page so the per-page markup stays untouched.
(function () {
  var app = document.querySelector('.app');
  var top = document.querySelector('.top');
  var side = document.querySelector('.side');
  if (!app || !top || !side) return;

  // hamburger (3 bars built via createElement — no innerHTML on dynamic data)
  var ham = document.createElement('button');
  ham.className = 'hamburger';
  ham.type = 'button';
  ham.setAttribute('aria-label', 'Open menu');
  for (var i = 0; i < 3; i++) ham.appendChild(document.createElement('span'));
  top.insertBefore(ham, top.firstChild);

  var scrim = document.createElement('div');
  scrim.className = 'nav-scrim';
  app.appendChild(scrim);

  function open() { app.classList.add('nav-open'); ham.setAttribute('aria-expanded', 'true'); }
  function close() { app.classList.remove('nav-open'); ham.setAttribute('aria-expanded', 'false'); }
  ham.addEventListener('click', function () {
    if (app.classList.contains('nav-open')) close(); else open();
  });
  scrim.addEventListener('click', close);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  // tapping a nav item closes the drawer (navigations close it anyway; this covers
  // same-page filters like /app?type=…)
  side.querySelectorAll('.nav-i').forEach(function (a) { a.addEventListener('click', close); });

  // ── currency switch inside the drawer ──
  // The topbar currency toggle is hidden on phones to declutter, which left no way to
  // switch base currency on mobile. Inject one into the sidebar (drawer) so every page
  // can switch; hidden on desktop (≥881px) via .side-cur CSS, where the topbar toggle shows.
  var box = document.createElement('div');
  box.className = 'side-cur';
  var label = document.createElement('div');
  label.className = 'side-cur-label';
  label.textContent = 'Currency';
  box.appendChild(label);
  var row = document.createElement('div');
  row.className = 'side-cur-row';
  ['INR', 'USD'].forEach(function (c) {
    var b = document.createElement('button');
    b.type = 'button';
    b.dataset.cur = c;
    b.textContent = (c === 'INR' ? '₹ ' : '$ ') + c;
    b.addEventListener('click', function () {
      if (b.classList.contains('on')) return;
      b.disabled = true;
      fetch('/api/base-currency', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ currency: c })
      }).then(function (r) {
        if (r.ok) { location.reload(); } else { b.disabled = false; }
      }).catch(function () { b.disabled = false; });
    });
    row.appendChild(b);
  });
  box.appendChild(row);
  side.appendChild(box);
  // highlight the active currency (from /api/networth base_currency)
  fetch('/api/networth').then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      var base = (d && d.base_currency) || 'INR';
      row.querySelectorAll('button').forEach(function (b) {
        b.classList.toggle('on', b.dataset.cur === base);
      });
    }).catch(function () {});
})();
