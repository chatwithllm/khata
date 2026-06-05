# Khata Phase 3 · Plan 3.2 — Create-Plan Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A real `/create` page with type tabs (asset/loan/holding) that posts to `POST /api/plans` and redirects to `/app`. Frontend-only; makes the shell's "New plan" button live.

**Architecture:** Static `create-plan.html` on `ledger.css`, vanilla JS: auth guard → tab switch → build the type-matched payload → `POST /api/plans` → redirect on ok / inline error otherwise. New `/create` route.

**Tech Stack:** HTML/CSS/vanilla JS, Flask static, pytest.

---

### Task 1: Create-plan page (`create-plan.html`) + `/create` route

**Files:** Create `src/khata/static/create-plan.html`; Modify `src/khata/web.py`; Test `tests/test_web.py`

- [ ] **Step 1: Append failing test to `tests/test_web.py`**

```python
def test_create_page_served(client):
    r = client.get("/create")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/plans", "Asset", "Loan", "Holding", "ledger.css", "/api/auth/me"]:
        assert needle in body
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_web.py::test_create_page_served -q`
Expected: FAIL (404 — no `/create` route / file).

- [ ] **Step 3: Add the `/create` route to `src/khata/web.py`**

After the `holdings()` view (or after `features()` if `holdings` isn't present), add:
```python
@bp.get("/create")
def create_plan():
    return send_from_directory(_static_dir(), "create-plan.html")
```

- [ ] **Step 4: Create `src/khata/static/create-plan.html`** EXACTLY as below:

```html
<!DOCTYPE html>
<html lang="en" data-cur="inr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Khata — New plan</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/assets/ledger.css">
<style>
  .topbar{display:flex;align-items:center;justify-content:space-between;padding:18px 0}
  .topbar .brand{display:flex;align-items:center;gap:10px;font-family:"Fraunces",serif;font-weight:600;font-size:20px}
  .topbar .glyph{width:26px;height:26px;border-radius:7px;background:linear-gradient(145deg,var(--primary),var(--primary-deep))}
  .formcard{max-width:560px;margin:8px auto 40px}
  .tabs{display:flex;gap:8px;margin:6px 0 18px}
  .tab{flex:1;text-align:center;border:1px solid var(--line);background:var(--card);border-radius:10px;padding:10px;cursor:pointer;font-weight:600;color:var(--ink-soft)}
  .tab.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
  .fld{display:flex;flex-direction:column;gap:5px;margin-bottom:13px}
  .fld label{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--ink-faint);font-weight:700}
  .fld input,.fld select{font-family:inherit;font-size:15px;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:var(--card);color:var(--ink)}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .grp{display:none} .grp.on{display:block}
  .inst{display:grid;grid-template-columns:1fr 1fr auto;gap:8px;margin-bottom:7px}
  .lnk{color:var(--primary);font-weight:600;cursor:pointer;font-size:13px}
  .err{color:var(--neg);font-size:13px;min-height:18px;margin:4px 0}
  .actions{display:flex;gap:12px;align-items:center;margin-top:10px}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <a class="brand" href="/app"><span class="glyph"></span> Khata</a>
    <a class="link" href="/app">← Back to app</a>
  </div>

  <div class="formcard">
    <h1 style="font-family:'Fraunces',serif;font-weight:600;font-size:28px;margin-bottom:6px">New plan</h1>
    <p class="muted" style="margin-bottom:14px">Track a purchase, a loan, or a holding.</p>

    <div class="tabs">
      <div class="tab on" data-t="asset">Asset</div>
      <div class="tab" data-t="loan">Loan</div>
      <div class="tab" data-t="holding">Holding</div>
    </div>

    <div class="fld"><label>Name</label><input id="name" placeholder="Devanahalli plot"></div>
    <div class="fld"><label>Currency</label>
      <select id="currency"><option value="INR">INR ₹</option><option value="USD">USD $</option></select>
    </div>

    <!-- Asset -->
    <div class="grp on" id="g-asset">
      <div class="fld"><label>Total price</label><input id="total_price" placeholder="20,00,000"></div>
      <label class="lbl" style="font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--ink-faint);font-weight:700">Installments (optional)</label>
      <div id="insts"></div>
      <span class="lnk" id="addinst">+ Add installment</span>
    </div>

    <!-- Loan -->
    <div class="grp" id="g-loan">
      <div class="row2">
        <div class="fld"><label>Direction</label>
          <select id="direction"><option value="taken">I borrowed (taken)</option><option value="given">I lent (given)</option></select>
        </div>
        <div class="fld"><label>Counterparty</label><input id="counterparty" placeholder="HDFC / Priya"></div>
      </div>
      <div class="row2">
        <div class="fld"><label>Interest</label>
          <select id="interest_type"><option value="none">None</option><option value="monthly">Per month</option><option value="yearly">Per year</option></select>
        </div>
        <div class="fld" id="ratefld" style="display:none"><label>Rate %</label><input id="rate" placeholder="8.5"></div>
      </div>
      <div class="row2">
        <div class="fld"><label>Start date</label><input id="start_date" type="date"></div>
        <div class="fld"><label>Tenure (months)</label><input id="tenure_months" placeholder="optional"></div>
      </div>
    </div>

    <!-- Holding -->
    <div class="grp" id="g-holding">
      <div class="row2">
        <div class="fld"><label>Asset class</label>
          <select id="asset_class"><option>gold</option><option>silver</option><option>equity</option><option>mf</option><option>cash</option><option>other</option></select>
        </div>
        <div class="fld"><label>Unit</label><input id="unit" placeholder="gram / share / unit"></div>
      </div>
      <div class="row2">
        <div class="fld"><label>Symbol</label><input id="symbol" placeholder="HDFC (optional)"></div>
        <div class="fld"><label>Purity</label><input id="purity" placeholder="22K (optional)"></div>
      </div>
    </div>

    <div class="err" id="err"></div>
    <div class="actions">
      <button class="btn" id="submit">Create plan</button>
      <a class="link" href="/app">Cancel</a>
    </div>
  </div>
</div>

<script>
  const $ = (id) => document.getElementById(id);
  let type = "asset";

  // auth guard
  (async () => { if ((await fetch("/api/auth/me")).status === 401) window.location.href = "/"; })();

  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
    type = t.dataset.t;
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("on", x === t));
    ["asset", "loan", "holding"].forEach((g) => $("g-" + g).classList.toggle("on", g === type));
    $("err").textContent = "";
  }));

  $("interest_type").addEventListener("change", () => {
    $("ratefld").style.display = $("interest_type").value === "none" ? "none" : "block";
  });

  function addInst(amount, due) {
    const row = document.createElement("div"); row.className = "inst";
    const a = document.createElement("input"); a.placeholder = "amount"; a.className = "i-amt"; a.value = amount || "";
    const d = document.createElement("input"); d.type = "date"; d.className = "i-due"; if (due) d.value = due;
    const x = document.createElement("span"); x.className = "lnk"; x.textContent = "✕";
    x.addEventListener("click", () => row.remove());
    row.append(a, d, x); $("insts").appendChild(row);
  }
  $("addinst").addEventListener("click", () => addInst());

  function payload() {
    const name = $("name").value, currency = $("currency").value;
    if (type === "loan") {
      const it = $("interest_type").value;
      const p = { type: "loan", name, currency, direction: $("direction").value,
                  counterparty: $("counterparty").value || null, interest_type: it,
                  start_date: $("start_date").value || null };
      if (it !== "none") p.rate = $("rate").value;
      if ($("tenure_months").value) p.tenure_months = parseInt($("tenure_months").value, 10);
      return p;
    }
    if (type === "holding") {
      return { type: "holding", name, currency, asset_class: $("asset_class").value,
               unit: $("unit").value, symbol: $("symbol").value || null, purity: $("purity").value || null };
    }
    const insts = [...document.querySelectorAll(".inst")].map((r) => ({
      amount: r.querySelector(".i-amt").value, due_date: r.querySelector(".i-due").value || null,
    })).filter((i) => i.amount);
    const p = { name, currency, total_price: $("total_price").value };
    if (insts.length) p.installments = insts;
    return p;
  }

  $("submit").addEventListener("click", async () => {
    $("err").textContent = "";
    const r = await fetch("/api/plans", { method: "POST", headers: { "Content-Type": "application/json" },
                                          body: JSON.stringify(payload()) });
    if (r.ok) { window.location.href = "/app"; return; }
    const e = await r.json().catch(() => ({}));
    $("err").textContent = (e.detail || e.error || "Could not create the plan.");
  });
</script>
</body>
</html>
```

- [ ] **Step 5: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_web.py -q` (expect all pass), then `.venv/bin/python -m pytest -q` (expect 114 passed — 113 + 1).

- [ ] **Step 6: Commit**

```bash
git add src/khata/static/create-plan.html src/khata/web.py tests/test_web.py
git commit -m "feat(web): create-plan flow — tabbed form (asset/loan/holding) → POST /api/plans

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Smoke test + process docs

**Files:** Modify `docs/AGENT_LEARNINGS.md`, `docs/superpowers/Progress.md`, `docs/superpowers/ROADMAP.md`
(NOTE: do NOT touch `build_status.json` — the web-app-builder dashboard feed is owned by the orchestrator and updated outside this plan.)

- [ ] **Step 1: Smoke-test create for all three types**

```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db PYTHONPATH=src .venv/bin/python wsgi.py > /tmp/k32.log 2>&1 &
sleep 2.5
curl -s -c /tmp/cj32 -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' -d '{"email":"a@b.com","display_name":"A","password":"pw12345"}' >/dev/null
echo "== /create =="; curl -s -o /dev/null -w "%{http_code}\n" localhost:5050/create
curl -s -b /tmp/cj32 -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"name":"Plot","currency":"INR","total_price":"20,00,000","installments":[{"amount":"5,00,000","due_date":"2026-03-01"}]}' -o /dev/null -w "asset %{http_code}\n"
curl -s -b /tmp/cj32 -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"type":"loan","name":"GL","currency":"INR","direction":"taken","interest_type":"monthly","rate":"2","start_date":"2026-01-01"}' -o /dev/null -w "loan %{http_code}\n"
curl -s -b /tmp/cj32 -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"type":"holding","name":"Gold","currency":"INR","asset_class":"gold","unit":"gram"}' -o /dev/null -w "holding %{http_code}\n"
echo "== plans count =="; curl -s -b /tmp/cj32 localhost:5050/api/plans | .venv/bin/python -c "import sys,json;print(len(json.load(sys.stdin)['plans']))"
kill %1 2>/dev/null; rm -f /tmp/cj32 /tmp/k32.log khata.db khata.db-wal khata.db-shm
```
Expected: `/create` 200; asset/loan/holding all 201; plans count `3`. Free port 5050 first if busy.

- [ ] **Step 2: Append to `docs/AGENT_LEARNINGS.md`**

```markdown

## 2026-06-04 — Plan 3.2 (Create-plan flow)
- `/create` page: a single tabbed form (asset/loan/holding) that builds the exact JSON shape each type
  needs and posts to `POST /api/plans`, redirecting to `/app`. Auth-guarded client-side. The asset
  installments builder is a small add/remove row list; rate field reveals only for interest≠none.
- Reuses the existing create dispatch verbatim — no backend change. Error `{detail|error}` shown inline
  via textContent.
```

- [ ] **Step 3: Update `docs/superpowers/Progress.md`** — flip `- [ ] 3.2 Create-plan flow` to `- [x]`,
  update the snapshot tests count to 114, and prepend a one-line log entry for 3.2. Update
  `docs/superpowers/ROADMAP.md` — flip `- [ ] **3.2 Create-plan flow**` to `- [x]`.

- [ ] **Step 4: Commit**

```bash
git add docs/AGENT_LEARNINGS.md docs/superpowers/Progress.md docs/superpowers/ROADMAP.md
git commit -m "chore(process): Plan 3.2 complete — learnings, progress, roadmap

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review
Spec coverage: tabbed create for all 3 types + installments + redirect + auth guard → Task 1; smoke + docs → Task 2. Placeholder scan: complete page; payloads match the create API exactly. Type consistency: payload keys (`total_price`/`installments`; loan `direction`/`interest_type`/`rate`/`start_date`/`tenure_months`; holding `asset_class`/`unit`/`symbol`/`purity`) match `api/plans.py:create`. Test 113 → 114. ✓

## Next (Plan 3.3)
Asset detail page + log-payment modal.
