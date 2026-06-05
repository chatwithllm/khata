# Khata Phase 3 · Plan 3.5 — Holding Detail + Sharing Panel Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8 + the K5 enum rule) before the task; done-gate = real end-to-end. Do NOT touch `build_status.json`.

**Goal:** `/holding/<id>` detail page (value/gain/qty, buy/sell/quote) + a reusable `sharing.js` members panel mounted on every plan-detail page. Frontend-only; closes Plan-4 sharing in the UI.

---

### Task 1: sharing.js + holding-detail page + route + mount on all detail pages

**Files:** Create `src/khata/static/assets/sharing.js`, `src/khata/static/holding-detail.html`; Modify `src/khata/web.py`, `src/khata/static/asset-detail.html`, `src/khata/static/loan-detail.html`; Test `tests/test_web.py`

- [ ] **Step 1: Append failing tests to `tests/test_web.py`**
```python
def test_holding_detail_served(client):
    r = client.get("/holding/1")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/plans", "/holding/buys", "/holding/quote", "sharing.js", "ledger.css"]:
        assert needle in body

def test_sharing_js_served_and_mounted(client):
    assert client.get("/static/assets/sharing.js").status_code == 200
    for path in ["/asset/1", "/loan/1", "/holding/1"]:
        assert "sharing.js" in client.get(path).data.decode()
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_web.py::test_holding_detail_served tests/test_web.py::test_sharing_js_served_and_mounted -q` → FAIL.

- [ ] **Step 3: Add route to `src/khata/web.py`** (after `loan_detail()`):
```python
@bp.get("/holding/<int:plan_id>")
def holding_detail(plan_id):
    return send_from_directory(_static_dir(), "holding-detail.html")
```

- [ ] **Step 4: Create `src/khata/static/assets/sharing.js`** EXACTLY:
```javascript
// Reusable plan-sharing panel — mountSharing(planId, containerEl). XSS-safe (textContent only).
(function () {
  function el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  async function mountSharing(planId, box) {
    box.textContent = "";
    let meId = null;
    try { const me = await fetch("/api/auth/me"); if (me.ok) meId = (await me.json()).user.id; } catch (_) {}
    const r = await fetch("/api/plans/" + planId + "/members");
    if (!r.ok) return;
    const members = (await r.json()).members || [];
    const owner = members.find((m) => m.role === "owner");
    const isOwner = owner && meId === owner.user_id;

    const h = el("h2", null, "Shared with");
    h.style.fontFamily = "Fraunces, serif"; h.style.fontSize = "19px"; h.style.marginBottom = "10px";
    box.appendChild(h);

    const list = el("div");
    for (const m of members) {
      const row = el("div");
      row.style.display = "flex"; row.style.alignItems = "center"; row.style.gap = "10px";
      row.style.padding = "8px 0"; row.style.borderBottom = "1px solid var(--line)";
      const nm = el("div");
      nm.appendChild(el("div", null, m.display_name || m.email));
      const sub = el("div", "muted", m.email + " · " + m.role); sub.style.fontSize = "12px";
      nm.appendChild(sub);
      row.appendChild(nm);
      if (isOwner && m.role !== "owner") {
        const rm = el("span", "tlink", "Remove");
        rm.style.marginLeft = "auto"; rm.style.color = "var(--neg)"; rm.style.cursor = "pointer";
        rm.addEventListener("click", async () => {
          await fetch("/api/plans/" + planId + "/members/" + m.user_id, { method: "DELETE" });
          mountSharing(planId, box);
        });
        row.appendChild(rm);
      }
      list.appendChild(row);
    }
    box.appendChild(list);

    if (isOwner) {
      const form = el("div");
      form.style.display = "flex"; form.style.gap = "8px"; form.style.marginTop = "10px";
      const input = el("input"); input.placeholder = "add by email"; input.style.flex = "1";
      input.style.fontFamily = "inherit"; input.style.fontSize = "14px"; input.style.padding = "8px 11px";
      input.style.border = "1px solid var(--line)"; input.style.borderRadius = "9px";
      input.style.background = "var(--card)"; input.style.color = "var(--ink)";
      const btn = el("button", "btn", "Add");
      const err = el("div", "err");
      err.style.color = "var(--neg)"; err.style.fontSize = "13px"; err.style.minHeight = "16px"; err.style.marginTop = "6px";
      btn.addEventListener("click", async () => {
        err.textContent = "";
        const res = await fetch("/api/plans/" + planId + "/members", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: input.value }) });
        if (res.ok) { input.value = ""; mountSharing(planId, box); return; }
        const e = await res.json().catch(() => ({}));
        err.textContent = ({ user_not_found: "No account with that email.",
                             already_member: "Already shared with them." })[e.error] || e.detail || "Could not add.";
      });
      form.append(input, btn); box.appendChild(form); box.appendChild(err);
    }
  }
  window.mountSharing = mountSharing;
})();
```

- [ ] **Step 5: Create `src/khata/static/holding-detail.html`** EXACTLY:
```html
<!DOCTYPE html>
<html lang="en" data-cur="inr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Khata — Holding</title>
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
  .cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:10px}
  @media(max-width:680px){.cards{grid-template-columns:1fr}}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;box-shadow:var(--shadow)}
  .stat .k{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink-faint);font-weight:700}
  .stat .v{font-family:"Fraunces",serif;font-size:24px;margin-top:6px}
  .stat .v.pos{color:var(--pos)} .stat .v.neg{color:var(--neg)}
  .statusline{font-size:13px;color:var(--ink-soft);margin-bottom:18px}
  .sec{margin:22px 0}
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
    <div><h1 id="name">Holding</h1><div class="meta" id="meta">—</div></div>
    <button class="btn" id="actbtn">Buy / Sell / Quote</button>
  </div>
  <div class="cards">
    <div class="stat"><div class="k">Current value</div><div class="v mono" id="value">—</div></div>
    <div class="stat"><div class="k">Unrealized gain</div><div class="v mono" id="gain">—</div></div>
    <div class="stat"><div class="k">Quantity held</div><div class="v mono" id="qty">—</div></div>
  </div>
  <div class="statusline" id="statusline"></div>
  <div class="sec"><div id="sharing"></div></div>
</div>

<div class="modal" id="modal">
  <div class="sheet">
    <h3>Holding action</h3>
    <div class="fld"><label>Action</label>
      <select id="act"><option value="buy">Buy</option><option value="sell">Sell</option><option value="quote">Set quote (price/unit)</option></select>
    </div>
    <div class="fld" id="qtyfld"><label>Quantity</label><input id="quantity" placeholder="10"></div>
    <div class="fld" id="amtfld"><label>Amount (total cash)</label><input id="amount" placeholder="5,00,000"></div>
    <div class="fld" id="pricefld" style="display:none"><label>Price per unit</label><input id="price" placeholder="60,000"></div>
    <div class="err" id="err"></div>
    <div class="acts"><button class="btn" id="save">Save</button><a class="link" id="cancel">Cancel</a></div>
  </div>
</div>

<script src="/static/assets/sharing.js"></script>
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
  function fmtMicro(q) { if (q === null || q === undefined) return "—"; return (q / 1e6).toLocaleString("en-IN"); }

  async function load() {
    const r = await fetch("/api/plans/" + pid);
    if (r.status === 401) { window.location.href = "/"; return; }
    if (!r.ok) { window.location.href = "/app"; return; }
    const d = await r.json();
    if (d.plan.type !== "holding") { window.location.href = "/app"; return; }
    currency = d.plan.currency;
    const st = d.state, p = d.plan;
    $("name").textContent = p.name;
    $("meta").textContent = st.asset_class + (st.purity ? " · " + st.purity : "")
      + (st.symbol ? " · " + st.symbol : "") + " · " + currency + " · " + p.status;
    $("value").textContent = fmtMinor(st.current_value_minor, currency);
    const g = $("gain"); g.textContent = fmtMinor(st.unrealized_gain_minor, currency);
    g.classList.toggle("pos", (st.unrealized_gain_minor || 0) > 0);
    g.classList.toggle("neg", (st.unrealized_gain_minor || 0) < 0);
    $("qty").textContent = fmtMicro(st.qty_held_micro) + " " + st.unit;
    $("statusline").textContent = "Avg cost " + fmtMinor(st.avg_cost_per_unit_minor, currency) + "/" + st.unit
      + " · cost of held " + fmtMinor(st.cost_of_held_minor, currency)
      + " · realized " + fmtMinor(st.realized_gain_minor, currency)
      + (st.current_price_minor != null ? " · quote " + fmtMinor(st.current_price_minor, currency) + "/" + st.unit : " · no quote");
    mountSharing(pid, $("sharing"));
  }

  function syncFields() {
    const a = $("act").value;
    $("qtyfld").style.display = a === "quote" ? "none" : "block";
    $("amtfld").style.display = a === "quote" ? "none" : "block";
    $("pricefld").style.display = a === "quote" ? "block" : "none";
  }
  $("act").addEventListener("change", syncFields);
  $("actbtn").addEventListener("click", () => { $("err").textContent = ""; syncFields(); $("modal").classList.add("on"); });
  $("cancel").addEventListener("click", () => $("modal").classList.remove("on"));
  $("save").addEventListener("click", async () => {
    $("err").textContent = "";
    const a = $("act").value;
    let url, body;
    if (a === "quote") { url = "/api/plans/" + pid + "/holding/quote"; body = { price: $("price").value }; }
    else { url = "/api/plans/" + pid + "/holding/" + (a === "buy" ? "buys" : "sells");
           body = { quantity: $("quantity").value, amount: $("amount").value }; }
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) { $("modal").classList.remove("on"); $("quantity").value = ""; $("amount").value = ""; $("price").value = ""; load(); return; }
    const e = await r.json().catch(() => ({})); $("err").textContent = e.detail || e.error || "Could not save.";
  });

  load();
</script>
</body>
</html>
```

- [ ] **Step 6: Mount the panel on `asset-detail.html` and `loan-detail.html`.**
  For BOTH files: (a) immediately after the last `</div>` that closes the final content `.sec` and
  before the `</div>` that closes `.wrap`, insert `\n  <div class="sec"><div id="sharing"></div></div>`;
  (b) add `<script src="/static/assets/sharing.js"></script>` on the line immediately before the page's
  own `<script>` tag; (c) inside `load()`, on success (right before the function's closing `}`), add
  `mountSharing(pid, $("sharing"));`. Read each file and place these precisely — the `#sharing` div must
  be inside `.wrap`, the script include before the inline script, and the mount call at the end of `load()`.

- [ ] **Step 7: Run + full suite** — `pytest tests/test_web.py -q`, then `pytest -q` (expect 118 — 116 + 2).

- [ ] **Step 8: Commit**
```bash
git add src/khata/static/assets/sharing.js src/khata/static/holding-detail.html src/khata/static/asset-detail.html src/khata/static/loan-detail.html src/khata/web.py tests/test_web.py
git commit -m "feat(web): holding detail page + reusable sharing panel on all plan details

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Done-gate smoke + docs

- [ ] **Step 1: End-to-end done-gate** (free 5050 first):
```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db PYTHONPATH=src .venv/bin/python wsgi.py > /tmp/k35.log 2>&1 &
sleep 2.5
curl -s -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' -d '{"email":"b@b.com","display_name":"Bee","password":"pw12345"}' >/dev/null
curl -s -c /tmp/cj35 -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' -d '{"email":"a@b.com","display_name":"A","password":"pw12345"}' >/dev/null
curl -s -b /tmp/cj35 -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"type":"holding","name":"Gold","currency":"INR","asset_class":"gold","unit":"gram"}' >/dev/null
curl -s -b /tmp/cj35 -X POST localhost:5050/api/plans/1/holding/buys -H 'Content-Type: application/json' -d '{"quantity":"10","amount":"5,00,000"}' >/dev/null
curl -s -b /tmp/cj35 -X POST localhost:5050/api/plans/1/holding/quote -H 'Content-Type: application/json' -d '{"price":"60,000"}' >/dev/null
echo "== /holding/1 =="; curl -s -o /dev/null -w "%{http_code}\n" localhost:5050/holding/1
echo "== sharing.js =="; curl -s -o /dev/null -w "%{http_code}\n" localhost:5050/static/assets/sharing.js
echo "== value =="; curl -s -b /tmp/cj35 localhost:5050/api/plans/1 | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['state']['current_value_minor'])"
echo "== add member =="; curl -s -b /tmp/cj35 -X POST localhost:5050/api/plans/1/members -H 'Content-Type: application/json' -d '{"email":"b@b.com"}' -o /dev/null -w "%{http_code}\n"
echo "== members =="; curl -s -b /tmp/cj35 localhost:5050/api/plans/1/members | .venv/bin/python -c "import sys,json;print(len(json.load(sys.stdin)['members']))"
kill %1 2>/dev/null; rm -f /tmp/cj35 /tmp/k35.log khata.db khata.db-wal khata.db-shm
```
Expected: `/holding/1` 200; `sharing.js` 200; value `60000000`; add member 201; members `2`. Capture actual.

- [ ] **Step 2: Append to `docs/AGENT_LEARNINGS.md`**:
```markdown

## 2026-06-04 — Plan 3.5 (Holding detail + sharing panel)
- `/holding/<id>` page: value/gain/qty cards, avg-cost + quote status line, a Buy/Sell/Set-quote modal →
  `/holding/{buys,sells,quote}`. Reusable `static/assets/sharing.js` (`mountSharing(planId, box)`) renders
  the members list and — for the owner only — an add-by-email form + per-contributor remove, posting to
  the `/members` endpoints. Mounted on holding/asset/loan detail pages. All DOM via createElement (K4).
- Phase 3 complete: every existing domain (asset/loan/holding) is fully operable in the browser —
  create, view, log, and share — with no curl.
```

- [ ] **Step 3: Flip 3.5 box** in Progress.md + ROADMAP.md; mark Phase 3 done; bump tests to 118; prepend a 3.5 log line.

- [ ] **Step 4: Commit**
```bash
git add docs/AGENT_LEARNINGS.md docs/superpowers/Progress.md docs/superpowers/ROADMAP.md
git commit -m "chore(process): Plan 3.5 complete — Phase 3 done; learnings, progress, roadmap

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review
Holding contract keys (`current_value_minor`/`unrealized_gain_minor`/`qty_held_micro`/`avg_cost_per_unit_minor`/`cost_of_held_minor`/`realized_gain_minor`/`current_price_minor`/`unit`/`asset_class`/`purity`/`symbol`) match `holding_state`. Actions match `/holding/{buys,sells,quote}` payloads (`{quantity,amount}` / `{price}`). Members panel matches `/members` POST `{email}` → 201 / GET `{members:[{user_id,email,display_name,role}]}` / DELETE `/<user_id>`. XSS-safe (textContent). Tests 116→118. ✓

## Next
Phase-3 integration review → PR → merge → Phase 4 (chit funds).
