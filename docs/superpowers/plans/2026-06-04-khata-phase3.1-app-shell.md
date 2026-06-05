# Khata Phase 3 · Plan 3.1 — App Shell + Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder `/app` with a real authenticated app shell — sidebar nav, topbar (signed-in user + logout), a dashboard overview (net worth + position cards), and a type-filterable plan list — wired to the existing `/api/auth/me`, `/api/networth`, `/api/dashboard`, `/api/plans`.

**Architecture:** Frontend-only. A single static `app.html` on `ledger.css` (+ inline app-shell CSS), vanilla JS with a client-side auth guard (401→`/`), parallel fetches, and XSS-safe DOM rendering. The existing `/app` route is reused (the file is replaced). No backend changes.

**Tech Stack:** HTML/CSS/vanilla JS, Flask static serving, pytest (route/markup level).

---

## File Structure

```
src/khata/static/app.html   # REPLACE 12-line placeholder: the app shell
tests/test_web.py           # MODIFY: /app shell markers
build_status.json / docs/AGENT_LEARNINGS.md / docs/superpowers/ROADMAP.md  # MODIFY (Task 2)
```
(`web.py` already serves `/app` from `app.html` — no route change.)

---

### Task 1: App shell page (`app.html`)

**Files:** Replace `src/khata/static/app.html`; Test `tests/test_web.py`

- [ ] **Step 1: Append failing test to `tests/test_web.py`**

```python
def test_app_shell_served(client):
    r = client.get("/app")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/auth/me", "/api/networth", "/api/dashboard", "/api/plans",
                   "Net worth", "ledger.css", "/holdings", "/features"]:
        assert needle in body
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_web.py::test_app_shell_served -q`
Expected: FAIL (the 12-line placeholder lacks these strings).

- [ ] **Step 3: Replace `src/khata/static/app.html`** EXACTLY as below:

```html
<!DOCTYPE html>
<html lang="en" data-cur="inr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Khata — App</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/assets/ledger.css">
<style>
  .app{display:grid;grid-template-columns:236px 1fr;min-height:100vh;position:relative;z-index:1}
  @media(max-width:880px){.app{grid-template-columns:1fr}.side{display:none}}
  .side{border-right:1px solid var(--line);background:var(--paper-2);padding:20px 14px;position:sticky;top:0;height:100vh}
  .side .brand{display:flex;align-items:center;gap:10px;font-family:"Fraunces",serif;font-weight:600;font-size:20px;padding:4px 8px 16px}
  .side .glyph{width:26px;height:26px;border-radius:7px;background:linear-gradient(145deg,var(--primary),var(--primary-deep));box-shadow:0 6px 14px -6px var(--primary)}
  .newplan{display:block;text-align:center;background:linear-gradient(145deg,var(--primary),var(--primary-deep));color:#fff;font-weight:600;padding:9px;border-radius:10px;margin:0 4px 12px}
  .navsec{font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;color:var(--ink-faint);font-weight:700;padding:14px 10px 6px}
  .nav-i{display:flex;align-items:center;gap:9px;padding:8px 11px;border-radius:9px;font-weight:500;color:var(--ink-soft);font-size:14px;cursor:pointer}
  .nav-i:hover{background:var(--line-2);color:var(--ink)}
  .nav-i.on{background:var(--ink);color:var(--paper)}
  .nav-i.soon{opacity:.5;cursor:default}
  .nav-i .ct{margin-left:auto;font-size:10px;font-family:"JetBrains Mono";opacity:.7}
  .main{min-width:0}
  .top{display:flex;align-items:center;justify-content:space-between;padding:18px 28px;border-bottom:1px solid var(--line);position:sticky;top:0;background:color-mix(in srgb,var(--paper) 84%,transparent);backdrop-filter:blur(8px);z-index:20}
  .top h1{font-family:"Fraunces",serif;font-weight:600;font-size:22px}
  .top .sub{font-size:12.5px;color:var(--ink-faint)}
  .top-right{display:flex;align-items:center;gap:12px}
  .badge{font-family:"JetBrains Mono";font-weight:700;font-size:12px;background:var(--paper-2);border:1px solid var(--line);border-radius:100px;padding:5px 11px}
  .lo{font-size:13px;color:var(--ink-soft);cursor:pointer}
  .lo:hover{color:var(--neg)}
  .body{padding:24px 28px}
  .cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
  @media(max-width:760px){.cards{grid-template-columns:repeat(2,1fr)}}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;box-shadow:var(--shadow)}
  .stat .k{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink-faint);font-weight:700}
  .stat .v{font-family:"Fraunces",serif;font-size:24px;margin-top:6px}
  .stat .v.pos{color:var(--pos)} .stat .v.neg{color:var(--neg)}
  .chips{display:flex;gap:8px;margin:22px 0 10px;flex-wrap:wrap}
  .chip{font-size:13px;border:1px solid var(--line);background:var(--card);border-radius:100px;padding:6px 14px;cursor:pointer;color:var(--ink-soft)}
  .chip.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
  .plan{display:flex;align-items:center;gap:12px;padding:13px 16px;border:1px solid var(--line);border-radius:12px;background:var(--card);margin-bottom:9px}
  .plan .nm{font-weight:600} .plan .meta{font-size:12.5px;color:var(--ink-faint)}
  .plan .tag{margin-left:auto;font-size:11px;font-family:"JetBrains Mono";text-transform:uppercase;letter-spacing:.06em;color:var(--ink-soft);border:1px solid var(--line);border-radius:100px;padding:3px 9px}
  .empty{color:var(--ink-faint);padding:24px;text-align:center}
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <a class="brand" href="/app"><span class="glyph"></span> Khata</a>
    <a class="newplan" href="/create">+ New plan</a>
    <div class="navsec">Overview</div>
    <a class="nav-i on" href="/app">Dashboard</a>
    <a class="nav-i" href="/holdings">Holdings &amp; net worth</a>
    <div class="navsec">Money plans</div>
    <div class="nav-i" data-filter="asset">Assets <span class="ct" id="ct-asset"></span></div>
    <div class="nav-i" data-filter="loan">Loans <span class="ct" id="ct-loan"></span></div>
    <div class="nav-i" data-filter="holding">Holdings <span class="ct" id="ct-holding"></span></div>
    <div class="navsec">More</div>
    <a class="nav-i" href="/features">Features</a>
    <div class="nav-i soon">Settings <span class="ct">soon</span></div>
  </aside>

  <main class="main">
    <header class="top">
      <div><h1 id="greet">Welcome</h1><div class="sub" id="sub">Your money, your ledger.</div></div>
      <div class="top-right">
        <span class="badge" id="basebadge">—</span>
        <span class="lo" id="logout">Log out</span>
      </div>
    </header>
    <div class="body">
      <div class="cards">
        <div class="stat"><div class="k">Net worth</div><div class="v mono" id="networth">—</div></div>
        <div class="stat"><div class="k">Paid to date</div><div class="v mono" id="paid">—</div></div>
        <div class="stat"><div class="k">I owe</div><div class="v mono neg" id="iowe">—</div></div>
        <div class="stat"><div class="k">Owed to me</div><div class="v mono pos" id="owed">—</div></div>
      </div>

      <div class="chips" id="chips">
        <span class="chip on" data-f="all">All</span>
        <span class="chip" data-f="asset">Assets</span>
        <span class="chip" data-f="loan">Loans</span>
        <span class="chip" data-f="holding">Holdings</span>
      </div>
      <div id="plans"></div>
    </div>
  </main>
</div>

<script>
  const $ = (id) => document.getElementById(id);
  const SYM = { INR: "₹", USD: "$" };
  let ALL = [];
  let base = "INR";

  function fmtMinor(m, ccy) {
    if (m === null || m === undefined) return "—";
    const neg = m < 0, v = Math.abs(m) / 100;
    return (neg ? "-" : "") + (SYM[ccy] || "") + v.toLocaleString("en-IN", { minimumFractionDigits: 2 });
  }

  function planTag(p) {
    if (p.type === "loan") return (p.direction || "loan");
    if (p.type === "holding") return (p.asset_class || "holding");
    return "asset";
  }

  function render(filter) {
    const rows = filter === "all" ? ALL : ALL.filter((p) => p.type === filter);
    const box = $("plans");
    box.textContent = "";
    if (!rows.length) {
      const e = document.createElement("div"); e.className = "empty";
      e.textContent = "No plans yet. Create one to get started.";
      box.appendChild(e); return;
    }
    for (const p of rows) {
      const row = document.createElement("div"); row.className = "plan";
      const left = document.createElement("div");
      const nm = document.createElement("div"); nm.className = "nm"; nm.textContent = p.name;
      const meta = document.createElement("div"); meta.className = "meta";
      meta.textContent = p.type + " · " + p.currency + " · " + p.status;
      left.append(nm, meta);
      const tag = document.createElement("span"); tag.className = "tag"; tag.textContent = planTag(p);
      row.append(left, tag);
      box.appendChild(row);
    }
  }

  async function boot() {
    const me = await fetch("/api/auth/me");
    if (me.status === 401) { window.location.href = "/"; return; }
    const user = (await me.json()).user;
    $("greet").textContent = "Hello, " + user.display_name;

    const [nw, dash, plans] = await Promise.all([
      fetch("/api/networth").then((r) => r.json()),
      fetch("/api/dashboard").then((r) => r.json()),
      fetch("/api/plans").then((r) => r.json()),
    ]);
    base = nw.base_currency || "INR";
    $("basebadge").textContent = "Base " + base;
    $("networth").textContent = fmtMinor(nw.net_worth_minor, base);
    $("paid").textContent = fmtMinor(dash.paid_to_date_minor, base);
    $("iowe").textContent = fmtMinor(dash.i_owe_minor, base);
    $("owed").textContent = fmtMinor(dash.owed_to_me_minor, base);

    ALL = plans.plans || [];
    const by = (t) => ALL.filter((p) => p.type === t).length || "";
    $("ct-asset").textContent = by("asset");
    $("ct-loan").textContent = by("loan");
    $("ct-holding").textContent = by("holding");
    render("all");
  }

  document.querySelectorAll("#chips .chip").forEach((c) => {
    c.addEventListener("click", () => {
      document.querySelectorAll("#chips .chip").forEach((x) => x.classList.remove("on"));
      c.classList.add("on");
      render(c.dataset.f);
    });
  });
  document.querySelectorAll(".nav-i[data-filter]").forEach((n) => {
    n.addEventListener("click", () => {
      const f = n.dataset.filter;
      document.querySelectorAll("#chips .chip").forEach((x) => x.classList.toggle("on", x.dataset.f === f));
      render(f);
    });
  });
  $("logout").addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/";
  });

  boot();
</script>
</body>
</html>
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_web.py -q` (expect all pass — the existing `test_*` still pass), then `.venv/bin/python -m pytest -q` (expect 113 passed — 112 + 1).

- [ ] **Step 5: Commit**

```bash
git add src/khata/static/app.html tests/test_web.py
git commit -m "feat(web): real app shell — sidebar, dashboard cards, filterable plan list

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Smoke test + process docs

**Files:** Modify `build_status.json`, `docs/AGENT_LEARNINGS.md`, `docs/superpowers/ROADMAP.md`

- [ ] **Step 1: Smoke-test the shell + the APIs it calls**

```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db PYTHONPATH=src .venv/bin/python wsgi.py > /tmp/khata_p31.log 2>&1 &
sleep 2.5
curl -s -c /tmp/cj31 -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' -d '{"email":"arjun@b.com","display_name":"Arjun","password":"pw12345"}' >/dev/null
curl -s -b /tmp/cj31 -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"name":"Devanahalli plot","currency":"INR","total_price":"20,00,000"}' >/dev/null
curl -s -b /tmp/cj31 -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"type":"loan","name":"Gold loan","currency":"INR","direction":"taken","interest_type":"none","start_date":"2026-01-01"}' >/dev/null
echo "== /app =="; curl -s -o /dev/null -w "%{http_code}\n" localhost:5050/app
echo "== me =="; curl -s -b /tmp/cj31 -o /dev/null -w "%{http_code}\n" localhost:5050/api/auth/me
echo "== dashboard =="; curl -s -b /tmp/cj31 -o /dev/null -w "%{http_code}\n" localhost:5050/api/dashboard
echo "== networth =="; curl -s -b /tmp/cj31 -o /dev/null -w "%{http_code}\n" localhost:5050/api/networth
echo "== plans count =="; curl -s -b /tmp/cj31 localhost:5050/api/plans | .venv/bin/python -c "import sys,json;print(len(json.load(sys.stdin)['plans']))"
kill %1 2>/dev/null
rm -f /tmp/cj31 /tmp/khata_p31.log khata.db khata.db-wal khata.db-shm
```
Expected: `/app` 200; me/dashboard/networth all 200; plans count `2`. If port 5050 is busy, free it first (`lsof -ti tcp:5050 | xargs kill 2>/dev/null`).

- [ ] **Step 2: Replace `build_status.json`** with exactly:

```json
{
  "project": "khata",
  "phase": 3,
  "plan": "3.1-app-shell",
  "tasks_total": 2,
  "tasks_done": 2,
  "last_updated": "2026-06-04",
  "tests": "113 passed",
  "python": "3.12",
  "notes": "Phase 3 begun. Plan 3.1 complete: real /app shell (sidebar nav, topbar with greeting + base badge + logout, dashboard cards [net worth / paid / i owe / owed to me], type-filterable plan list) wired to /api/auth/me + /api/networth + /api/dashboard + /api/plans. Client-side auth guard (401→/). XSS-safe DOM rendering. Next: Plan 3.2 (create-plan flow)."
}
```

- [ ] **Step 3: Append to `docs/AGENT_LEARNINGS.md`** exactly this block:

```markdown

## 2026-06-04 — Plan 3.1 (App shell + dashboard)
- Real `/app` shell replaces the placeholder: sidebar + topbar + dashboard cards + a client-side
  type-filterable plan list, all wired to the existing read APIs (`/api/auth/me`, `/api/networth`,
  `/api/dashboard`, `/api/plans`). No backend changes — Phase 3 is wiring mockups to built APIs.
- Auth guard is client-side (`GET /api/auth/me`, 401→`/`), consistent with the static-page pattern;
  pages stay static, no server templating. Parallel `Promise.all` fetch for the three dashboards.
- All dynamic rows are built with `createElement`+`textContent` (XSS-safe) per the Plan-2B lesson.
- App-shell CSS (sidebar/topbar/cards/rows) lives inline in `app.html`; tokens + grain come from
  `ledger.css`. When 3.2–3.5 add more app pages, consider promoting the shell CSS into a shared sheet.
- The "New plan" button + plan-row detail links point at routes that Plans 3.2–3.5 add; informational
  rows for now (clickable detail lands with the detail pages).
```

- [ ] **Step 4: Check the Phase 3.1 box in `docs/superpowers/ROADMAP.md`**

Change `- [ ] **3.1 App shell + dashboard**` to `- [x] **3.1 App shell + dashboard**`.

- [ ] **Step 5: Commit**

```bash
git add build_status.json docs/AGENT_LEARNINGS.md docs/superpowers/ROADMAP.md
git commit -m "chore(process): Plan 3.1 complete — build status, learnings, roadmap

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** app shell (sidebar/topbar/logout) · dashboard cards (net worth + paid/iowe/owed) ·
type-filterable plan list · client-side auth guard · XSS-safe rendering · base-currency badge → all in
Task 1. Smoke + docs → Task 2. ✓

**Placeholder scan:** Complete HTML/CSS/JS; the only intentionally-unbuilt links (`/create`, detail
pages) are documented as landing in 3.2–3.5. ✓

**Type consistency:** Consumes the real, unchanged response keys (`net_worth_minor`, `base_currency`,
`paid_to_date_minor`/`i_owe_minor`/`owed_to_me_minor`, `plans[]` with `type`/`name`/`currency`/`status`/
`direction`/`asset_class`). Test count 112 → 113. ✓

---

## Next (Plan 3.2)
Create-plan flow (`create-plan.html`): wired form → `POST /api/plans` for asset | loan | holding;
redirect to the new plan's detail; makes the shell's "New plan" button live.
