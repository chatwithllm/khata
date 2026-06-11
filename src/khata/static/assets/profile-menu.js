/* profile-menu.js — topbar avatar becomes a profile dropdown (like every web app).
 *
 *   mountProfileMenu()
 *
 * Turns the #avatar widget into a button that opens a small menu: the signed-in user's
 * name + email, a Settings link, and Log out. Loads /api/auth/me to fill name/email/photo.
 * Closes on outside-click or Escape. All DOM via createElement/textContent (rule K4).
 */
(function () {
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function mountProfileMenu() {
    var av = document.getElementById("avatar");
    if (!av || av.dataset.pmenu) return;     // idempotent
    av.dataset.pmenu = "1";

    // Neutralize the legacy in-place photo input + camera overlay (photo editing lives
    // in Settings now; the topbar avatar is an account button, not an uploader).
    try { localStorage.removeItem("khata_avatar"); } catch (e) {}
    var inp = av.querySelector("input");
    if (inp) inp.disabled = true;
    var cam = av.querySelector(".ava-ov");
    if (cam) cam.style.display = "none";
    av.style.cursor = "pointer";
    av.title = "Account";
    av.setAttribute("role", "button");
    av.setAttribute("aria-haspopup", "menu");
    av.setAttribute("aria-expanded", "false");

    var menu = el("div", "pmenu");
    menu.hidden = true;
    menu.setAttribute("role", "menu");

    var head = el("div", "pmenu-head");
    var nm = el("div", "pmenu-name", "—");
    var em = el("div", "pmenu-email", "");
    head.append(nm, em);

    var settings = el("a", "pmenu-item");
    settings.href = "/settings";
    settings.append(el("span", "pmenu-ico", "⚙"), el("span", null, "Settings"));

    var logout = el("button", "pmenu-item pmenu-danger");
    logout.type = "button";
    logout.append(el("span", "pmenu-ico", "⏻"), el("span", null, "Log out"));
    logout.addEventListener("click", function () {
      fetch("/api/auth/logout", { method: "POST" }).finally(function () {
        window.location.href = "/";
      });
    });

    menu.append(head, el("div", "pmenu-sep"), settings, logout);
    document.body.appendChild(menu);

    function place() {
      var r = av.getBoundingClientRect();
      menu.style.top = (r.bottom + 8) + "px";
      menu.style.right = Math.max(8, window.innerWidth - r.right) + "px";
    }
    function open() {
      place();
      menu.hidden = false;
      av.setAttribute("aria-expanded", "true");
      document.addEventListener("click", onDoc, true);
      document.addEventListener("keydown", onKey, true);
      window.addEventListener("resize", place);
    }
    function close() {
      menu.hidden = true;
      av.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", onDoc, true);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", place);
    }
    function onDoc(e) { if (!menu.contains(e.target) && !av.contains(e.target)) close(); }
    function onKey(e) { if (e.key === "Escape") close(); }

    av.addEventListener("click", function (e) {
      e.preventDefault();
      if (menu.hidden) open(); else close();
    });

    fetch("/api/auth/me").then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (!d || !d.user) return;
      var u = d.user;
      nm.textContent = u.display_name || u.email || "Account";
      em.textContent = u.email || "";
      var init = av.querySelector(".ava-init");
      if (init && !init.textContent) init.textContent = ((u.display_name || u.email || "?")[0] || "?").toUpperCase();
      if (u.avatar) { av.style.backgroundImage = 'url("' + u.avatar + '")'; av.classList.add("has-img"); }
      else { av.style.backgroundImage = ""; av.classList.remove("has-img"); }
    }).catch(function () {});
  }

  window.mountProfileMenu = mountProfileMenu;
})();
