# Khata Phase 3 · Plan 3.3 — Asset Detail + Log-Payment Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Harness: read `agent-rules.md` (K1–K8) before each task; pass the done-gate (real end-to-end), not just a green test. Do NOT touch `build_status.json` (orchestrator-owned).

**Goal:** `/asset/<id>` detail page (total/paid/remaining, schedule, funding, contributors) + a log-payment modal posting to `/api/plans/<id>/payments`; make app-shell asset rows clickable. Frontend-only.

**Tech Stack:** HTML/CSS/vanilla JS (XSS-safe DOM), Flask static, pytest.

---

### Task 1: Asset detail page + `/asset/<id>` route + clickable app rows

**Files:** Create `src/khata/static/asset-detail.html`; Modify `src/khata/web.py`, `src/khata/static/app.html`; Test `tests/test_web.py`

- [ ] **Step 1: Append failing test to `tests/test_web.py`**

```python
def test_asset_detail_served(client):
    r = client.get("/asset/1")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/plans", "/payments", "Log payment", "ledger.css"]:
        assert needle in body
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest tests/test_web.py::test_asset_detail_served -q` → FAIL (404).

- [ ] **Step 3: Add the route to `src/khata/web.py`** (after `create_plan()`):
```python
@bp.get("/asset/<int:plan_id>")
def asset_detail(plan_id):
    return send_from_directory(_static_dir(), "asset-detail.html")
```

- [ ] **Step 4: Create `src/khata/static/asset-detail.html`** EXACTLY:

```html
<!DOCTYPE html>
<html lang="en" data-cur="inr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Khata — Asset</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/assets/ledger.css">
<style>
  .topbar{display:flex;align-items:center;justify-content:space-between;padding:18px 0}
  .topbar .brand{display:flex;align-items:center;gap:10px;font-family:"Fraunces",serif;font-weight:600;font-size:20px}
  .topbar .glyph{width:26px;height:26px;border-radius:7px;background:linear-gradient(145deg,var(--primary),var(--primary-deep))}
  .head{display:flex;align-items:flex-end;justify-content:space-between;margin:8px 0 16px;gap:12px}
  .head h1{font-family:"Fraunces",serif;font-weight:600;font-size:30px}
  .head .meta{font-size:13px;color:var(--ink-faint)}
  .cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:22px}
  @media(max-width:680px){.cards{grid-template-columns:1fr}}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;box-shadow:var(--shadow)}
  .stat .k{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink-faint);font-weight:700}
  .stat .v{font-family:"Fraunces",serif;font-size:24px;margin-top:6px}
  .sec{margin:24px 0}
  .sec h2{font-family:"Fraunces",serif;font-size:19px;margin-bottom:10px}
  table.sched{width:100%;border-collapse:collapse}
  table.sched th,table.sched td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);font-size:13.5px}
  table.sched th{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--ink-faint)}
  .badge{font-size:11px;font-family:"JetBrains Mono";font-weight:700;padding:2px 8px;border-radius:100px}
  .badge.paid{color:var(--pos);background:color-mix(in srgb,var(--pos) 12%,transparent)}
  .badge.partial{color:var(--primary);background:color-mix(in srgb,var(--primary) 12%,transparent)}
  .badge.due{color:var(--ink-faint);background:var(--paper-2)}
  .fund{display:flex;align-items:center;gap:10px;margin-bottom:7px}
  .fund .nm{width:120px;font-size:13px} .fund .bar{flex:1;height:8px;background:var(--paper-2);border-radius:100px;overflow:hidden}
  .fund .bar i{display:block;height:100%;background:linear-gradient(90deg,var(--primary),var(--primary-deep))}
  .fund .amt{font-family:"JetBrains Mono";font-size:12.5px;color:var(--ink-soft);width:120px;text-align:right}
  .con{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid var(--line)}
  .con .pct{margin-left:auto;font-family:"JetBrains Mono";font-size:12.5px;color:var(--ink-soft)}
  .modal{position:fixed;inset:0;background:rgba(20,16,12,.45);display:none;align-items:center;justify-content:center;z-index:50}
  .modal.on{display:flex}
  .sheet{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px;width:min(440px,92vw);box-shadow:var(--shadow)}
  .sheet h3{font-family:"Fraunces",serif;font-size:20px;margin-bottom:12px}
  .fld{display:flex;flex-direction:column;gap:5px;margin-bottom:12px}
  .fld label{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--ink-faint);font-weight:700}
  .fld input,.fld select{font-family:inherit;font-size:15px;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:var(--card);color:var(--ink)}
  .err{color:var(--neg);font-size:13px;min-height:18px}
  .acts{display:flex;gap:10px;align-items:center;margin-top:6px}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <a class="brand" href="/app"><span class="glyph"></span> Khata</a>
    <a class="link" href="/app">← Back to app</a>
  </div>

  <div class="head">
    <div><h1 id="name">Asset</h1><div class="meta" id="meta">—</div></div>
    <button class="btn" id="logbtn">Log payment</button>
  </div>

  <div class="cards">
    <div class="stat"><div class="k">Total</div><div class="v mono" id="total">—</div></div>
    <div class="stat"><div class="k">Paid to date</div><div class="v mono" id="paid">—</div></div>
    <div class="stat"><div class="k">Remaining</div><div class="v mono" id="remaining">—</div></div>
  </div>

  <div class="sec"><h2>Installment schedule</h2>
    <table class="sched"><thead><tr><th>#</th><th>Planned</th><th>Applied</th><th>Status</th></tr></thead>
    <tbody id="sched"></tbody></table>
  </div>

  <div class="sec"><h2>Funding</h2><div id="funding"></div></div>
  <div class="sec"><h2>Contributors</h2><div id="contribs"></div></div>
</div>

<div class="modal" id="modal">
  <div class="sheet">
    <h3>Log a payment</h3>
    <div class="fld"><label>Amount</label><input id="amount" placeholder="50,000"></div>
    <div class="fld"><label>Method</label>
      <select id="method"><option>transfer</option><option>upi</option><option>cash</option><option>card</option></select>
    </div>
    <div class="fld"><label>Funding source</label>
      <select id="fsource"><option>savings</option><option>salary</option><option>chit payout</option><option>other</option></select>
    </div>
    <div class="fld"><label>Note (optional)</label><input id="note" placeholder=""></div>
    <div class="err" id="err"></div>
    <div class="acts"><button class="btn" id="save">Save payment</button><a class="link" id="cancel">Cancel</a></div>
  </div>
</div>

<script>
  const $ = (id) => document.getElementById(id);
  const SYM = { INR: "₹", USD: "$" };
  const pid = parseInt(location.pathname.split("/").pop(), 10);
  let currency = "INR";

  function fmtMinor(m, ccy) {
    if (m === null || m === undefined) return "—";
    const neg = m < 0, v = Math.abs(m) / 100;
    return (neg ? "-" : "") + (SYM[ccy] || "") + v.toLocaleString("en-IN", { minimumFractionDigits: 2 });
  }
  const cell = (txt, cls) => { const td = document.createElement("td"); if (cls) td.className = cls; td.textContent = txt; return td; };

  async function load() {
    const r = await fetch("/api/plans/" + pid);
    if (r.status === 401) { window.location.href = "/"; return; }
    if (!r.ok) { window.location.href = "/app"; return; }
    const d = await r.json();
    if (d.plan.type !== "asset") { window.location.href = "/app"; return; }
    currency = d.plan.currency;
    const st = d.state;
    $("name").textContent = d.plan.name;
    $("meta").textContent = d.plan.type + " · " + currency + " · " + d.plan.status;
    $("total").textContent = fmtMinor(st.total_price_minor, currency);
    $("paid").textContent = fmtMinor(st.paid_to_date_minor, currency);
    $("remaining").textContent = fmtMinor(st.remaining_minor, currency);

    const sb = $("sched"); sb.textContent = "";
    if (!st.installments.length) sb.appendChild(cell("No schedule set."));
    for (const it of st.installments) {
      const tr = document.createElement("tr");
      const badge = document.createElement("span"); badge.className = "badge " + it.status; badge.textContent = it.status;
      const stTd = document.createElement("td"); stTd.appendChild(badge);
      tr.append(cell("#" + it.seq), cell(fmtMinor(it.planned_amount_minor, currency), "mono"),
                cell(fmtMinor(it.applied_minor, currency), "mono"), stTd);
      sb.appendChild(tr);
    }

    const fb = $("funding"); fb.textContent = "";
    if (!st.funding_breakdown.length) fb.appendChild((() => { const e = document.createElement("div"); e.className = "muted"; e.textContent = "No payments yet."; return e; })());
    for (const f of st.funding_breakdown) {
      const row = document.createElement("div"); row.className = "fund";
      const nm = document.createElement("div"); nm.className = "nm"; nm.textContent = f.source || "—";
      const bar = document.createElement("div"); bar.className = "bar";
      const i = document.createElement("i"); i.style.width = (f.pct || 0) + "%"; bar.appendChild(i);
      const amt = document.createElement("div"); amt.className = "amt"; amt.textContent = fmtMinor(f.amount_minor, currency) + " · " + (f.pct || 0) + "%";
      row.append(nm, bar, amt); fb.appendChild(row);
    }

    const cb = $("contribs"); cb.textContent = "";
    if (!st.contributors || !st.contributors.length) cb.appendChild((() => { const e = document.createElement("div"); e.className = "muted"; e.textContent = "Just you so far."; return e; })());
    for (const c of (st.contributors || [])) {
      const row = document.createElement("div"); row.className = "con";
      const nm = document.createElement("span"); nm.textContent = c.display_name || ("user " + c.user_id);
      const pct = document.createElement("span"); pct.className = "pct"; pct.textContent = fmtMinor(c.paid_minor, currency) + " · " + c.pct + "%";
      row.append(nm, pct); cb.appendChild(row);
    }
  }

  $("logbtn").addEventListener("click", () => { $("err").textContent = ""; $("modal").classList.add("on"); });
  $("cancel").addEventListener("click", () => $("modal").classList.remove("on"));
  $("save").addEventListener("click", async () => {
    $("err").textContent = "";
    const body = { amount: $("amount").value, method: $("method").value,
                   funding_source: $("fsource").value, note: $("note").value || null };
    const r = await fetch("/api/plans/" + pid + "/payments", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) { $("modal").classList.remove("on"); $("amount").value = ""; load(); return; }
    const e = await r.json().catch(() => ({})); $("err").textContent = e.detail || e.error || "Could not log payment.";
  });

  load();
</script>
</body>
</html>
```

- [ ] **Step 5: Make app-shell plan rows clickable** — in `src/khata/static/app.html`, in the `render(filter)` function, change the row element from a `div` to an anchor linking to the type's detail page. Replace:
```javascript
      const row = document.createElement("div"); row.className = "plan";
```
with:
```javascript
      const row = document.createElement("a"); row.className = "plan";
      row.href = "/" + p.type + "/" + p.id; row.style.color = "inherit";
```
(The rest of the row-building loop is unchanged. `/asset/<id>` exists now; `/loan/<id>` and `/holding/<id>` land in Plans 3.4 and 3.5 — all three exist by the end of this Phase-3 branch.)

- [ ] **Step 6: Run + full suite** — `.venv/bin/python -m pytest tests/test_web.py -q`, then `.venv/bin/python -m pytest -q` (expect 115 — 114 + 1).

- [ ] **Step 7: Commit**
```bash
git add src/khata/static/asset-detail.html src/khata/static/app.html src/khata/web.py tests/test_web.py
git commit -m "feat(web): asset detail page + log-payment modal; clickable app rows

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Done-gate smoke + docs

- [ ] **Step 1: End-to-end done-gate** (free port 5050 first; `lsof -ti tcp:5050 | xargs kill 2>/dev/null`):
```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db PYTHONPATH=src .venv/bin/python wsgi.py > /tmp/k33.log 2>&1 &
sleep 2.5
curl -s -c /tmp/cj33 -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' -d '{"email":"a@b.com","display_name":"A","password":"pw12345"}' >/dev/null
curl -s -b /tmp/cj33 -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"name":"Plot","currency":"INR","total_price":"20,00,000","installments":[{"amount":"5,00,000"}]}' >/dev/null
echo "== /asset/1 =="; curl -s -o /dev/null -w "%{http_code}\n" localhost:5050/asset/1
curl -s -b /tmp/cj33 -X POST localhost:5050/api/plans/1/payments -H 'Content-Type: application/json' -d '{"amount":"5,00,000","method":"transfer","funding_source":"savings"}' -o /dev/null -w "payment %{http_code}\n"
echo "== paid_to_date =="; curl -s -b /tmp/cj33 localhost:5050/api/plans/1 | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['state']['paid_to_date_minor'])"
kill %1 2>/dev/null; rm -f /tmp/cj33 /tmp/k33.log khata.db khata.db-wal khata.db-shm
```
Expected: `/asset/1` 200; payment 201; `paid_to_date` `50000000`. Capture actual output.

- [ ] **Step 2: Append to `docs/AGENT_LEARNINGS.md`**:
```markdown

## 2026-06-04 — Plan 3.3 (Asset detail + log-payment)
- `/asset/<id>` page (id from `location.pathname`): total/paid/remaining cards, installment schedule with
  status badges, funding-breakdown bars, contributors — from `GET /api/plans/<id>` (asset_state). A
  log-payment modal posts `{amount,method,funding_source,note?}` to `/api/plans/<id>/payments` and
  re-fetches. Redirects to `/app` if the plan isn't an asset. All cells via createElement (K4).
- App-shell plan rows are now anchors → `/<type>/<id>`. Loan/holding detail pages land in 3.4/3.5.
```

- [ ] **Step 3: Flip the 3.3 boxes** in `docs/superpowers/Progress.md` and `docs/superpowers/ROADMAP.md`; bump Progress tests to 115; prepend a 3.3 log line.

- [ ] **Step 4: Commit**
```bash
git add docs/AGENT_LEARNINGS.md docs/superpowers/Progress.md docs/superpowers/ROADMAP.md
git commit -m "chore(process): Plan 3.3 complete — learnings, progress, roadmap

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review
Spec coverage: detail cards + schedule + funding + contributors + log-payment modal + clickable rows → Task 1; done-gate + docs → Task 2. Contract keys (`total_price_minor`/`paid_to_date_minor`/`remaining_minor`/`installments[seq,planned_amount_minor,applied_minor,status]`/`funding_breakdown[source,amount_minor,pct]`/`contributors[display_name,paid_minor,pct]`) match `asset_state`. Payment payload `{amount,method,funding_source,note}` matches `payment()`. XSS-safe. Test 114→115. ✓

## Next (Plan 3.4)
Loan detail page (`loan-detail.html` at `/loan/<id>`).
