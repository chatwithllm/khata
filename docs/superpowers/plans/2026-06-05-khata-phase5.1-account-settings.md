# Khata Phase 5 · Plan 5.1 — Account Settings Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8) per task; done-gate = real end-to-end. Do NOT touch `build_status.json`, `khata_live.db*`, `OD_khata_mockup/`.

**Goal:** Settings page — set/change password (incl. Google-only accounts), edit display name, manage base currency + FX. Backend = 2 small endpoints; frontend = a settings page.

---

### Task 1: Service + API (set_password, update_profile, has_password)

**Files:** Modify `src/khata/services/auth.py`, `src/khata/api/auth.py`; Test `tests/test_auth_service.py`, `tests/test_auth_api.py`

- [ ] **Step 1: Append failing tests to `tests/test_auth_service.py`**
```python
def test_set_password_for_google_user(session):
    from khata.services.auth import set_password, authenticate_user
    from khata.models import User
    u = User(email="g@b.com", display_name="G", password_hash=None, google_sub="sub-x")
    session.add(u); session.flush()
    set_password(session, user=u, password="newpw123"); session.commit()
    assert authenticate_user(session, email="g@b.com", password="newpw123").id == u.id


def test_set_password_too_short_rejected(session):
    import pytest
    from khata.services.auth import set_password, AuthError
    from khata.models import User
    u = User(email="g@b.com", display_name="G", password_hash=None); session.add(u); session.flush()
    with pytest.raises(AuthError):
        set_password(session, user=u, password="x")


def test_update_profile(session):
    import pytest
    from khata.services.auth import update_profile, AuthError, register_user
    u = register_user(session, email="a@b.com", display_name="Old", password="pw12345"); session.commit()
    update_profile(session, user=u, display_name="  New Name  "); session.commit()
    assert u.display_name == "New Name"
    with pytest.raises(AuthError):
        update_profile(session, user=u, display_name="   ")
```

- [ ] **Step 2: Run → FAIL** (import error).

- [ ] **Step 3: Add to `src/khata/services/auth.py`** (after `authenticate_user`):
```python
def set_password(session: Session, *, user: User, password: str) -> User:
    if len(password or "") < 6:
        raise AuthError("password too short")
    user.password_hash = hash_password(password)
    session.flush()
    return user


def update_profile(session: Session, *, user: User, display_name: str) -> User:
    name = (display_name or "").strip()
    if not name:
        raise AuthError("display name required")
    user.display_name = name
    session.flush()
    return user
```
(`hash_password`, `Session`, `User`, `AuthError` already imported.)

- [ ] **Step 4: Append failing tests to `tests/test_auth_api.py`** (uses the existing `client` fixture):
```python
def test_set_and_change_password(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "display_name": "A", "password": "pw12345"})
    assert client.post("/api/auth/password", json={"password": "x"}).status_code == 400
    assert client.post("/api/auth/password", json={"password": "newpw99"}).status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "a@b.com", "password": "newpw99"}).status_code == 200


def test_password_requires_auth(client):
    assert client.post("/api/auth/password", json={"password": "newpw99"}).status_code == 401


def test_update_profile_api(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "display_name": "Old", "password": "pw12345"})
    r = client.post("/api/auth/profile", json={"display_name": "New Name"})
    assert r.status_code == 200 and r.get_json()["user"]["display_name"] == "New Name"
    assert client.post("/api/auth/profile", json={"display_name": "  "}).status_code == 400
    assert client.get("/api/auth/me").get_json()["user"]["has_password"] is True
```

- [ ] **Step 5: Run → FAIL**.

- [ ] **Step 6: Modify `src/khata/api/auth.py`**
  - Extend the service import to add `set_password, update_profile`.
  - In `_user_json`, add `"has_password": bool(user.password_hash)` to the returned dict.
  - Add the two endpoints:
```python
@bp.post("/password")
def set_password_route():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    try:
        set_password(g.db, user=user, password=data.get("password", ""))
        g.db.commit()
    except AuthError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True), 200


@bp.post("/profile")
def update_profile_route():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    try:
        update_profile(g.db, user=user, display_name=data.get("display_name", ""))
        g.db.commit()
    except AuthError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(user=_user_json(user)), 200
```

- [ ] **Step 7: Run + full suite** — `pytest tests/test_auth_service.py tests/test_auth_api.py -q`, then `pytest -q` (expect 159 — 153 + 6).

- [ ] **Step 8: Commit** `feat(auth): set_password + update_profile endpoints; has_password in /me`.

---

### Task 2: Settings page + route + app nav link

**Files:** Create `src/khata/static/settings.html`; Modify `src/khata/web.py`, `src/khata/static/app.html`; Test `tests/test_web.py`

- [ ] **Step 1: Append failing test to `tests/test_web.py`**
```python
def test_settings_page_served(client):
    r = client.get("/settings")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/auth/password", "/api/auth/profile", "/api/base-currency", "ledger.css"]:
        assert needle in body
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: `src/khata/web.py`** — after `retirement_detail()` (or any view) add:
```python
@bp.get("/settings")
def settings():
    return send_from_directory(_static_dir(), "settings.html")
```

- [ ] **Step 4: Create `src/khata/static/settings.html`** EXACTLY:
```html
<!DOCTYPE html>
<html lang="en" data-cur="inr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Khata — Settings</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/assets/ledger.css">
<style>
  .topbar{display:flex;align-items:center;justify-content:space-between;padding:18px 0}
  .topbar .brand{display:flex;align-items:center;gap:10px;font-family:"Fraunces",serif;font-weight:600;font-size:20px}
  .topbar .glyph{width:26px;height:26px;border-radius:7px;background:linear-gradient(145deg,var(--primary),var(--primary-deep))}
  .formcard{max-width:560px;margin:8px auto 40px}
  .card2{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:20px 22px;margin-bottom:16px;box-shadow:var(--shadow)}
  .card2 h2{font-family:"Fraunces",serif;font-size:20px;margin-bottom:12px}
  .fld{display:flex;flex-direction:column;gap:5px;margin-bottom:12px}
  .fld label{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--ink-faint);font-weight:700}
  .fld input,.fld select{font-family:inherit;font-size:15px;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:var(--card);color:var(--ink)}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .msg{font-size:13px;min-height:18px}
  .msg.ok{color:var(--pos)} .msg.err{color:var(--neg)}
  .acts{display:flex;gap:10px;align-items:center;margin-top:4px}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <a class="brand" href="/app"><span class="glyph"></span> Khata</a>
    <a class="link" href="/app">← Back to app</a>
  </div>
  <div class="formcard">
    <h1 style="font-family:'Fraunces',serif;font-weight:600;font-size:28px;margin-bottom:14px">Settings</h1>

    <div class="card2">
      <h2>Profile</h2>
      <div class="fld"><label>Display name</label><input id="display_name"></div>
      <div class="msg" id="pmsg"></div>
      <div class="acts"><button class="btn" id="saveprofile">Save</button></div>
    </div>

    <div class="card2">
      <h2 id="pwtitle">Password</h2>
      <div class="muted" id="pwhint" style="margin-bottom:8px"></div>
      <div class="fld"><label>New password</label><input id="password" type="password" placeholder="at least 6 characters"></div>
      <div class="msg" id="wmsg"></div>
      <div class="acts"><button class="btn" id="savepw">Save password</button></div>
    </div>

    <div class="card2">
      <h2>Currency</h2>
      <div class="fld"><label>Base currency</label>
        <select id="base"><option value="INR">INR ₹</option><option value="USD">USD $</option></select>
      </div>
      <div class="row2">
        <div class="fld"><label>FX quote</label>
          <select id="fxq"><option value="USD">USD</option><option value="INR">INR</option></select>
        </div>
        <div class="fld"><label>Rate (1 quote = ? base)</label><input id="fxr" placeholder="83.42"></div>
      </div>
      <div class="msg" id="cmsg"></div>
      <div class="acts"><button class="btn" id="savebase">Set base</button><button class="btn" id="savefx">Set rate</button></div>
    </div>
  </div>
</div>
<script>
  const $ = (id) => document.getElementById(id);
  function show(el, ok, text) { el.className = "msg " + (ok ? "ok" : "err"); el.textContent = text; }
  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    return { ok: r.ok, j };
  }

  async function load() {
    const me = await fetch("/api/auth/me");
    if (me.status === 401) { window.location.href = "/"; return; }
    const u = (await me.json()).user;
    $("display_name").value = u.display_name || "";
    $("pwtitle").textContent = u.has_password ? "Change password" : "Set a password";
    $("pwhint").textContent = u.has_password ? "Update your email/password login." : "Add a password so you can also log in with email + password.";
    try { const nw = await (await fetch("/api/networth")).json(); $("base").value = nw.base_currency || "INR"; } catch (_) {}
  }

  $("saveprofile").addEventListener("click", async () => {
    const { ok, j } = await post("/api/auth/profile", { display_name: $("display_name").value });
    show($("pmsg"), ok, ok ? "Saved." : (j.detail || j.error || "Failed."));
    if (ok) load();
  });
  $("savepw").addEventListener("click", async () => {
    const { ok, j } = await post("/api/auth/password", { password: $("password").value });
    show($("wmsg"), ok, ok ? "Password updated." : (j.detail || j.error || "Failed."));
    if (ok) { $("password").value = ""; load(); }
  });
  $("savebase").addEventListener("click", async () => {
    const { ok, j } = await post("/api/base-currency", { currency: $("base").value });
    show($("cmsg"), ok, ok ? "Base currency set." : (j.detail || j.error || "Failed."));
  });
  $("savefx").addEventListener("click", async () => {
    const { ok, j } = await post("/api/fx-rates", { quote: $("fxq").value, rate: $("fxr").value });
    show($("cmsg"), ok, ok ? "Rate set." : (j.detail || j.error || "Failed."));
    if (ok) $("fxr").value = "";
  });

  load();
</script>
</body>
</html>
```

- [ ] **Step 5: `src/khata/static/app.html`** — change the sidebar Settings placeholder. Replace:
```html
    <div class="nav-i soon">Settings <span class="ct">soon</span></div>
```
with:
```html
    <a class="nav-i" href="/settings">Settings</a>
```

- [ ] **Step 6: Run + full suite** — `pytest tests/test_web.py -q`, then `pytest -q` (expect 160 — 159 + 1).

- [ ] **Step 7: Commit** `feat(web): settings page (password, display name, base currency, FX)`.

---

### Task 3: Done-gate smoke + docs

- [ ] **Step 1: End-to-end smoke** (scratch DB on 5050, NOT khata_live.db; free 5050 first): register → `/settings` 200 → POST `/api/auth/profile {display_name:"Renamed"}` 200 → POST `/api/auth/password {password:"brandnew"}` 200 → logout → login with `brandnew` → 200 → `/api/auth/me` has_password true. Capture output.
- [ ] **Step 2: Append to `docs/AGENT_LEARNINGS.md`**:
```markdown

## 2026-06-05 — Plan 5.1 (Account settings)
- `/settings` page: edit display name (`/api/auth/profile`), set/change password (`/api/auth/password` —
  session-authed, no old password, so Google-created `password_hash=None` users can add one and then use
  email/password login), and manage base currency + FX (existing endpoints). `_user_json` now exposes
  `has_password` so the UI shows "Set" vs "Change". Sidebar Settings is now a real link. createElement-only.
```
- [ ] **Step 3: Flip 5.1 boxes** in Progress.md + ROADMAP.md; bump tests to 160. Commit (orchestrator owns build_status.json).

---

## Self-Review
set_password (min 6, sets hash — Google users gain password login) + update_profile (non-empty). API auth-gated, commit/rollback. has_password in /me. Settings page wires profile/password/currency/FX, all textContent. No model change. Tests 153→160. ✓

## Next
5.2 Hardening sweep.
