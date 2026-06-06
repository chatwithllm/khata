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
})();
