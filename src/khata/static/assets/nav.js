// ── PWA: make Khata installable (manifest + apple meta + service worker) ──
(function () {
  function add(tag, attrs) {
    var e = document.createElement(tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    document.head.appendChild(e);
  }
  add('link', { rel: 'manifest', href: '/manifest.webmanifest' });
  add('meta', { name: 'apple-mobile-web-app-capable', content: 'yes' });
  add('meta', { name: 'apple-mobile-web-app-status-bar-style', content: 'default' });
  add('meta', { name: 'apple-mobile-web-app-title', content: 'Khata' });
  add('meta', { name: 'theme-color', content: '#C05E1B' });
  add('link', { rel: 'apple-touch-icon', href: '/static/assets/icons/apple-touch-icon.png' });
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () {});
    });
  }
})();

// Responsive sidebar: hamburger toggles off-canvas on mobile, collapses in-place on desktop.
// Desktop state persists in localStorage ('khata-nav' = 'open' | 'closed').
(function () {
  var app = document.querySelector('.app');
  var top = document.querySelector('.top');
  var side = document.querySelector('.side');
  if (!app || !top || !side) return;

  var ham = document.createElement('button');
  ham.className = 'hamburger';
  ham.type = 'button';
  ham.setAttribute('aria-label', 'Toggle menu');
  for (var i = 0; i < 3; i++) ham.appendChild(document.createElement('span'));
  top.insertBefore(ham, top.firstChild);

  var scrim = document.createElement('div');
  scrim.className = 'nav-scrim';
  app.appendChild(scrim);

  function isDesktop() { return window.matchMedia('(min-width:881px)').matches; }

  function openMobile()  { app.classList.add('nav-open');    ham.setAttribute('aria-expanded', 'true');  }
  function closeMobile() { app.classList.remove('nav-open'); ham.setAttribute('aria-expanded', 'false'); }

  function openDesktop()  { app.classList.remove('nav-closed'); try { localStorage.setItem('khata-nav', 'open');   } catch(e){} }
  function closeDesktop() { app.classList.add('nav-closed');    try { localStorage.setItem('khata-nav', 'closed'); } catch(e){} }

  // Restore desktop sidebar state across page loads
  if (isDesktop()) {
    try { if (localStorage.getItem('khata-nav') === 'closed') app.classList.add('nav-closed'); } catch(e) {}
  }

  ham.addEventListener('click', function () {
    if (isDesktop()) {
      if (app.classList.contains('nav-closed')) openDesktop(); else closeDesktop();
    } else {
      if (app.classList.contains('nav-open')) closeMobile(); else openMobile();
    }
  });

  scrim.addEventListener('click', closeMobile);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMobile(); });
  side.querySelectorAll('.nav-i').forEach(function (a) {
    a.addEventListener('click', function () { if (!isDesktop()) closeMobile(); });
  });
})();
