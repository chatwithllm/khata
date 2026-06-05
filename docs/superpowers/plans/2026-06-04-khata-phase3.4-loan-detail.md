# Khata Phase 3 · Plan 3.4 — Loan Detail Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8 + the K5 enum rule) before the task; pass the done-gate (real end-to-end). Do NOT touch `build_status.json`.

**Goal:** `/loan/<id>` detail page — principal/interest/total cards, monthly-interest schedule, and an action modal (disbursement / interest payment / principal repayment). Frontend-only.

---

### Task 1: Loan detail page + `/loan/<id>` route

**Files:** Create `src/khata/static/loan-detail.html`; Modify `src/khata/web.py`; Test `tests/test_web.py`

- [ ] **Step 1: Append failing test to `tests/test_web.py`**
```python
def test_loan_detail_served(client):
    r = client.get("/loan/1")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/plans", "/loan/disbursements", "/loan/entries", "ledger.css"]:
        assert needle in body
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_web.py::test_loan_detail_served -q` → FAIL (404).

- [ ] **Step 3: Add route to `src/khata/web.py`** (after `asset_detail()`):
```python
@bp.get("/loan/<int:plan_id>")
def loan_detail(plan_id):
    return send_from_directory(_static_dir(), "loan-detail.html")
```

- [ ] **Step 4: Create `src/khata/static/loan-detail.html`** EXACTLY:

```html
<!DOCTYPE html>
<html lang="en" data-cur="inr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Khata — Loan</title>
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
  .cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:14px}
  @media(max-width:680px){.cards{grid-template-columns:1fr}}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;box-shadow:var(--shadow)}
  .stat .k{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink-faint);font-weight:700}
  .stat .v{font-family:"Fraunces",serif;font-size:24px;margin-top:6px}
  .statusline{font-size:13px;color:var(--ink-soft);margin-bottom:18px}
  .sec{margin:22px 0}
  .sec h2{font-family:"Fraunces",serif;font-size:19px;margin-bottom:10px}
  table.sched{width:100%;border-collapse:collapse}
  table.sched th,table.sched td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);font-size:13.5px}
  table.sched th{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--ink-faint)}
  .badge{font-size:11px;font-family:"JetBrains Mono";font-weight:700;padding:2px 8px;border-radius:100px}
  .badge.paid{color:var(--pos);background:color-mix(in srgb,var(--pos) 12%,transparent)}
  .badge.partial{color:var(--primary);background:color-mix(in srgb,var(--primary) 12%,transparent)}
  .badge.due{color:var(--ink-faint);background:var(--paper-2)}
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
    <div><h1 id="name">Loan</h1><div class="meta" id="meta">—</div></div>
    <button class="btn" id="addbtn">Add entry</button>
  </div>

  <div class="cards">
    <div class="stat"><div class="k">Principal outstanding</div><div class="v mono" id="principal">—</div></div>
    <div class="stat"><div class="k">Interest due</div><div class="v mono" id="intdue">—</div></div>
    <div class="stat"><div class="k">Total owed</div><div class="v mono" id="total">—</div></div>
  </div>
  <div class="statusline" id="statusline"></div>

  <div class="sec"><h2>Interest schedule</h2>
    <table class="sched"><thead><tr><th>Month</th><th>Period start</th><th>Expected</th><th>Applied</th><th>Status</th></tr></thead>
    <tbody id="sched"></tbody></table>
  </div>
</div>

<div class="modal" id="modal">
  <div class="sheet">
    <h3>Add a loan entry</h3>
    <div class="fld"><label>Type</label>
      <select id="etype"><option value="disbursement">Disbursement (tranche)</option><option value="interest_payment">Interest payment</option><option value="principal_repayment">Principal repayment</option></select>
    </div>
    <div class="fld"><label>Amount</label><input id="amount" placeholder="1,00,000"></div>
    <div class="fld" id="methodfld" style="display:none"><label>Method</label>
      <select id="method"><option value="transfer">Transfer</option><option value="upi">UPI</option><option value="cash">Cash</option><option value="cheque">Cheque</option></select>
    </div>
    <div class="fld"><label>Note (optional)</label><input id="note" placeholder=""></div>
    <div class="err" id="err"></div>
    <div class="acts"><button class="btn" id="save">Save</button><a class="link" id="cancel">Cancel</a></div>
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
    if (d.plan.type !== "loan") { window.location.href = "/app"; return; }
    currency = d.plan.currency;
    const st = d.state, p = d.plan;
    $("name").textContent = p.name;
    $("meta").textContent = (st.direction === "taken" ? "borrowed" : "lent")
      + (p.counterparty ? " · " + p.counterparty : "") + " · " + currency + " · " + p.status;
    $("principal").textContent = fmtMinor(st.principal_outstanding_minor, currency);
    $("intdue").textContent = fmtMinor(st.interest_due_minor, currency);
    $("total").textContent = fmtMinor(st.total_minor, currency);
    const behind = st.months_behind || 0;
    $("statusline").textContent = "Interest accrued " + fmtMinor(st.interest_accrued_minor, currency)
      + " · paid " + fmtMinor(st.interest_paid_minor, currency)
      + (behind ? " · " + behind + " month(s) behind" : " · up to date") + " (as of " + st.as_of + ")";

    const sb = $("sched"); sb.textContent = "";
    if (!st.schedule.length) { const tr = document.createElement("tr"); tr.appendChild(cell("No interest schedule (interest-free or not yet accruing).")); sb.appendChild(tr); }
    for (const row of st.schedule) {
      const tr = document.createElement("tr");
      const badge = document.createElement("span"); badge.className = "badge " + (row.status || "due"); badge.textContent = row.status || "due";
      const stTd = document.createElement("td"); stTd.appendChild(badge);
      tr.append(cell("#" + (row.month_index + 1)), cell(row.period_start),
                cell(fmtMinor(row.expected_minor, currency), "mono"),
                cell(fmtMinor(row.applied_minor, currency), "mono"), stTd);
      sb.appendChild(tr);
    }
  }

  $("etype").addEventListener("change", () => {
    $("methodfld").style.display = $("etype").value === "disbursement" ? "none" : "block";
  });
  $("addbtn").addEventListener("click", () => { $("err").textContent = ""; $("modal").classList.add("on"); });
  $("cancel").addEventListener("click", () => $("modal").classList.remove("on"));
  $("save").addEventListener("click", async () => {
    $("err").textContent = "";
    const kind = $("etype").value;
    let url, body;
    if (kind === "disbursement") {
      url = "/api/plans/" + pid + "/loan/disbursements";
      body = { amount: $("amount").value, note: $("note").value || null };
    } else {
      url = "/api/plans/" + pid + "/loan/entries";
      body = { kind, amount: $("amount").value, method: $("method").value, note: $("note").value || null };
    }
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) { $("modal").classList.remove("on"); $("amount").value = ""; load(); return; }
    const e = await r.json().catch(() => ({})); $("err").textContent = e.detail || e.error || "Could not save the entry.";
  });

  load();
</script>
</body>
</html>
```

- [ ] **Step 5: Run + full suite** — `pytest tests/test_web.py -q`, then `pytest -q` (expect 116 — 115 + 1).

- [ ] **Step 6: Commit**
```bash
git add src/khata/static/loan-detail.html src/khata/web.py tests/test_web.py
git commit -m "feat(web): loan detail page — principal/interest cards, schedule, entry modal

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Done-gate smoke + docs

- [ ] **Step 1: End-to-end done-gate** (free 5050 first):
```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db PYTHONPATH=src .venv/bin/python wsgi.py > /tmp/k34.log 2>&1 &
sleep 2.5
curl -s -c /tmp/cj34 -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' -d '{"email":"a@b.com","display_name":"A","password":"pw12345"}' >/dev/null
curl -s -b /tmp/cj34 -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"type":"loan","name":"GL","currency":"INR","direction":"taken","interest_type":"monthly","rate":"2","start_date":"2026-01-01"}' >/dev/null
echo "== /loan/1 =="; curl -s -o /dev/null -w "%{http_code}\n" localhost:5050/loan/1
curl -s -b /tmp/cj34 -X POST localhost:5050/api/plans/1/loan/disbursements -H 'Content-Type: application/json' -d '{"amount":"6,00,000","occurred_at":"2026-01-01T00:00:00"}' -o /dev/null -w "disbursement %{http_code}\n"
echo "== principal =="; curl -s -b /tmp/cj34 localhost:5050/api/plans/1 | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['state']['principal_outstanding_minor'])"
kill %1 2>/dev/null; rm -f /tmp/cj34 /tmp/k34.log khata.db khata.db-wal khata.db-shm
```
Expected: `/loan/1` 200; disbursement 201; principal `60000000`. Capture actual.

- [ ] **Step 2: Append to `docs/AGENT_LEARNINGS.md`**:
```markdown

## 2026-06-04 — Plan 3.4 (Loan detail)
- `/loan/<id>` page: principal-outstanding / interest-due / total cards, a status line (accrued/paid/
  months-behind/as-of), and the monthly-interest schedule — from `loan_state`. One action modal routes
  by type: disbursement → `/loan/disbursements`; interest/principal → `/loan/entries` with the right
  `kind` (method select shows only for entries; values from `METHODS`). All cells via createElement (K4).
```

- [ ] **Step 3: Flip 3.4 boxes** in Progress.md + ROADMAP.md; bump Progress tests to 116; prepend a 3.4 log line.

- [ ] **Step 4: Commit**
```bash
git add docs/AGENT_LEARNINGS.md docs/superpowers/Progress.md docs/superpowers/ROADMAP.md
git commit -m "chore(process): Plan 3.4 complete — learnings, progress, roadmap

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review
Contract keys (`principal_outstanding_minor`/`interest_due_minor`/`total_minor`/`interest_accrued_minor`/`interest_paid_minor`/`months_behind`/`as_of`/`schedule[month_index,period_start,expected_minor,applied_minor,status]`) match `loan_state`. Disbursement `{amount,note}` + entry `{kind,amount,method,note}` match the endpoints. Method enum mirrors `METHODS`. XSS-safe. Test 115→116. ✓

## Next (Plan 3.5)
Holding detail + reusable sharing panel.
