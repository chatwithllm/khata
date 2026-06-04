# Khata mockups — SHARED KIT (cohesion backbone)

> Every screen reuses this VERBATIM so all 9 files look like one product.
> Do NOT alter token names, the JS contract, or the markup of curtog / sidebar / topbar.
> Reference screens already built to this system: `index.html` (landing, count-ups, grain,
> denom band, IntersectionObserver reveals) and `app.html` (sidebar + topbar + stat cards).
> Open them for patterns: ledger rows, `.pill`, `.tag`, bars, roll-forward badges, panels.

---

## 1. `<head>` — fonts (identical on every file)

```html
<!DOCTYPE html>
<html lang="en" data-cur="inr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Khata — <SCREEN NAME></title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
```

## 2. CSS — design tokens + base (paste at top of every `<style>`)

```css
:root{
  --paper:#F7F1E6;--paper-2:#F1E8D7;--ink:#241B16;--ink-soft:#4A4035;--ink-faint:#8C8068;
  --line:#DBCDB0;--line-2:#E7DCC6;--primary:#C05E1B;--primary-deep:#9C4711;
  --pos:#1F6B53;--pos-soft:#2E8C6E;--neg:#A6321F;--accent:#9E3B6E;--card:#FFFDF8;
  --glow:color-mix(in srgb,var(--primary) 12%,transparent);
  --shadow:0 1px 0 rgba(28,24,19,.04),0 16px 36px -24px rgba(28,24,19,.45);
  --r:16px;--ease:cubic-bezier(.22,.68,0,1);
}
html[data-cur="usd"]{
  --paper:#E9EFE8;--paper-2:#DDE7DB;--ink:#16241B;--ink-soft:#36473B;--ink-faint:#74866F;
  --line:#C2D4C0;--line-2:#D2E0D0;--primary:#1C7A45;--primary-deep:#115C32;
  --pos:#1C7A45;--pos-soft:#2E9457;--neg:#A6471F;--accent:#A9852F;--card:#FBFEFA;
  --glow:color-mix(in srgb,var(--primary) 14%,transparent);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--paper);color:var(--ink);font-family:"Hanken Grotesk",system-ui,sans-serif;
  font-size:15px;-webkit-font-smoothing:antialiased;position:relative;
  transition:background .6s var(--ease),color .6s var(--ease)}
/* film-grain overlay — keep on every screen */
body::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.5;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.045'/%3E%3C/svg%3E");}
.mono{font-family:"JetBrains Mono",monospace;font-variant-numeric:tabular-nums}
a{color:inherit;text-decoration:none}
```

## 3. CSS — app shell (sidebar + topbar + curtog + reveals) for ALL app screens

```css
.app{display:grid;grid-template-columns:240px 1fr;min-height:100vh;position:relative;z-index:1}
@media(max-width:880px){.app{grid-template-columns:1fr}.side{display:none}}
.side{border-right:1px solid var(--line);background:var(--paper-2);padding:22px 16px;position:sticky;top:0;height:100vh;transition:.6s}
.brand{display:flex;align-items:center;gap:10px;font-family:"Fraunces",serif;font-weight:600;font-size:21px;padding:6px 8px 22px}
.glyph{width:28px;height:28px;border-radius:8px;flex:none;background:linear-gradient(145deg,var(--primary),var(--primary-deep));position:relative;box-shadow:0 6px 14px -6px var(--primary)}
.glyph::before,.glyph::after{content:"";position:absolute;left:6px;right:6px;height:2px;background:var(--paper);border-radius:2px;opacity:.85}
.glyph::before{top:10px}.glyph::after{top:16px;right:11px}
.navsec{font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;color:var(--ink-faint);font-weight:700;padding:16px 10px 8px}
.nav-i{display:flex;align-items:center;gap:11px;padding:9px 11px;border-radius:10px;font-weight:500;color:var(--ink-soft);cursor:pointer;transition:.2s;font-size:14.5px}
.nav-i svg{width:18px;height:18px;flex:none}
.nav-i:hover{background:var(--line-2);color:var(--ink)}
.nav-i.on{background:var(--ink);color:var(--paper)}
.nav-i .ct{margin-left:auto;font-size:11px;font-family:"JetBrains Mono";opacity:.7}
.main{min-width:0}
.top{display:flex;align-items:center;justify-content:space-between;padding:18px 30px;border-bottom:1px solid var(--line);position:sticky;top:0;background:color-mix(in srgb,var(--paper) 82%,transparent);backdrop-filter:blur(8px);z-index:20;transition:.6s}
.top h1{font-family:"Fraunces",serif;font-weight:600;font-size:23px;letter-spacing:-.01em}
.top .sub{font-size:12.5px;color:var(--ink-faint)}
.top-right{display:flex;align-items:center;gap:14px}
.curtog{display:inline-flex;background:var(--paper-2);border:1px solid var(--line);border-radius:100px;padding:3px;position:relative}
.curtog button{font-family:"JetBrains Mono";font-weight:700;font-size:12.5px;border:none;background:transparent;color:var(--ink-faint);width:44px;height:28px;border-radius:100px;cursor:pointer;z-index:1;transition:color .3s}
.curtog button.on{color:#fff}
.curtog .slide{position:absolute;top:3px;left:3px;width:44px;height:28px;border-radius:100px;background:linear-gradient(145deg,var(--primary),var(--primary-deep));transition:transform .4s var(--ease),background .6s}
html[data-cur="usd"] .curtog .slide{transform:translateX(44px)}
.addbtn{font-weight:600;font-size:14px;padding:9px 16px;border-radius:10px;background:var(--ink);color:var(--paper);border:none;cursor:pointer;display:flex;align-items:center;gap:7px;transition:transform .2s}
.addbtn:hover{transform:translateY(-2px)}
.avatar{width:34px;height:34px;border-radius:50%;background:linear-gradient(145deg,var(--accent),var(--primary-deep));color:#fff;display:grid;place-items:center;font-weight:700;font-size:13px}
.content{padding:28px 30px 60px;max-width:1200px;position:relative;z-index:1}
.panel{background:var(--card);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;transition:.6s}
.ph{display:flex;align-items:center;justify-content:space-between;padding:18px 22px;border-bottom:1px solid var(--line)}
.ph .t{font-family:"Fraunces",serif;font-weight:600;font-size:18px;display:flex;align-items:center;gap:10px}
.ph .meta{font-size:12.5px;color:var(--ink-faint);font-family:"JetBrains Mono"}
.tag{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:3px 7px;border-radius:5px}
.tag.asset{background:color-mix(in srgb,var(--primary) 16%,transparent);color:var(--primary-deep)}
.tag.chit{background:color-mix(in srgb,var(--pos) 16%,transparent);color:var(--pos)}
.tag.loan{background:color-mix(in srgb,var(--neg) 15%,transparent);color:var(--neg)}
.pill{font-size:10px;font-weight:600;padding:2px 8px;border-radius:20px;border:1px solid var(--line);color:var(--ink-soft);text-transform:capitalize}
.proof{font-size:10px;color:var(--primary-deep);font-weight:600;display:inline-flex;gap:3px;align-items:center}
/* on-load stagger + scroll reveal */
.fade{opacity:0;transform:translateY(16px);animation:rise .7s var(--ease) forwards}
.fade.d1{animation-delay:.06s}.fade.d2{animation-delay:.13s}.fade.d3{animation-delay:.2s}.fade.d4{animation-delay:.27s}.fade.d5{animation-delay:.34s}
@keyframes rise{to{opacity:1;transform:none}}
[data-rise]{opacity:0;transform:translateY(22px);transition:opacity .8s var(--ease),transform .8s var(--ease)}
[data-rise].in{opacity:1;transform:none}
@media(prefers-reduced-motion:reduce){.fade{animation:none;opacity:1;transform:none}[data-rise]{opacity:1;transform:none}}
```

## 4. Sidebar + topbar markup (paste in `<body>`, mark current screen `.on`)

Sidebar nav order from spec: Dashboard, Holdings, Assets, Chit funds, Loans, Ledger, Settings.
(`app.html` groups them — match its grouping/icons; just move `.on` to the active item and link items: Dashboard→app.html, Holdings→holdings.html, Assets→asset-detail.html, Chit funds→chit-detail.html, Loans→loan-detail.html, 401(k)→retirement-401k.html.)

```html
<div class="app">
  <aside class="side">
    <a class="brand" href="index.html"><span class="glyph"></span> Khata</a>
    <div class="navsec">Overview</div>
    <a class="nav-i" href="app.html"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="11" width="8" height="10" rx="1.5"/><rect x="3" y="14" width="8" height="7" rx="1.5"/></svg> Dashboard</a>
    <a class="nav-i" href="holdings.html"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12l9-8 9 8M5 10v10h14V10"/></svg> Holdings</a>
    <div class="navsec">Money plans</div>
    <a class="nav-i" href="asset-detail.html"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M5 21V10l7-5 7 5v11"/></svg> Assets <span class="ct">2</span></a>
    <a class="nav-i" href="chit-detail.html"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg> Chit funds <span class="ct">3</span></a>
    <a class="nav-i" href="loan-detail.html"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7h18v12H3zM3 11h18"/></svg> Loans <span class="ct">2</span></a>
    <a class="nav-i" href="retirement-401k.html"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v18M5 8h9a3 3 0 010 6H5"/></svg> 401(k)</a>
    <div class="navsec">Records</div>
    <a class="nav-i" href="#"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 5h16M4 12h16M4 19h10"/></svg> Ledger</a>
    <a class="nav-i" href="#"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 00-.1-1l2-1.5-2-3.5-2.4 1a7 7 0 00-1.7-1l-.3-2.5h-4l-.3 2.5a7 7 0 00-1.7 1l-2.4-1-2 3.5L4.1 11a7 7 0 000 2l-2 1.5 2 3.5 2.4-1a7 7 0 001.7 1l.3 2.5h4l.3-2.5a7 7 0 001.7-1l2.4 1 2-3.5-2-1.5a7 7 0 00.1-1z"/></svg> Settings</a>
  </aside>
  <main class="main">
    <div class="top">
      <div>
        <h1><!-- screen title --></h1>
        <div class="sub"><!-- breadcrumb / context --></div>
      </div>
      <div class="top-right">
        <div class="curtog" id="curtog" title="Primary currency"><span class="slide"></span><button data-set="inr" class="on">₹ INR</button><button data-set="usd">$ USD</button></div>
        <button class="addbtn"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 5v14M5 12h14"/></svg> Log payment</button>
        <div class="avatar">A</div>
      </div>
    </div>
    <div class="content">
      <!-- SCREEN BODY HERE -->
    </div>
  </main>
</div>
```

## 5. The currency JS engine — number-format CONTRACT (paste before `</body>`)

Every figure stores its **base INR amount** in `data-inr` on a `.cv` element.
`data-style="lakh"` → abbreviated (₹12.4L / ₹1.18Cr  vs  $14.9k / $1.2M).
`.cv.count` → animated count-up on load/reveal. `.symword` → live ₹/$ glyph.
`.unitword` → "rupee"/"dollar". Bars: `<i data-w="62">` fill to width% on load/reveal.
Toggle re-themes (via `data-cur` on `<html>`) AND reformats every figure. FX 1 USD = 83 INR.

```html
<script>
const RATE=83; let CUR=(location.hash==='#usd')?'usd':'inr';
function indGroup(n){n=Math.round(n);let s=Math.abs(n).toString();if(s.length>3){let l=s.slice(-3),r=s.slice(0,-3).replace(/\B(?=(\d{2})+(?!\d))/g,',');s=r+','+l;}return (n<0?'-':'')+s;}
function usGroup(n){return Math.round(n).toLocaleString('en-US');}
function abbr(v){if(CUR==='inr'){if(Math.abs(v)>=1e7)return (v/1e7).toFixed(2).replace(/\.?0+$/,'')+'Cr';return (v/1e5).toFixed(Math.abs(v)%1e5?2:0).replace(/\.?0+$/,'')+'L';}if(Math.abs(v)>=1e6)return (v/1e6).toFixed(2).replace(/\.?0+$/,'')+'M';return (v/1e3).toFixed(Math.abs(v)%1e3?1:0)+'k';}
function sym(){return CUR==='inr'?'₹':'$';}
function val(inr){return CUR==='inr'?inr:inr/RATE;}
function renderCV(el,animate){
  const inr=+el.dataset.inr, base=val(inr), lakh=el.dataset.style==='lakh';
  const out = lakh?abbr(base):(CUR==='inr'?indGroup(base):usGroup(base));
  if(animate && el.classList.contains('count')){
    const t0=performance.now(),dur=1300;
    (function tick(t){const p=Math.min(1,(t-t0)/dur),e=1-Math.pow(1-p,3),v=base*e;
      el.textContent=lakh?abbr(v):(CUR==='inr'?indGroup(v):usGroup(v));
      if(p<1)requestAnimationFrame(tick);})(performance.now());
  } else { el.textContent = out; }
}
function applyCurrency(animate){
  document.documentElement.dataset.cur=CUR;
  document.querySelectorAll('.symword').forEach(s=>s.textContent=sym());
  document.querySelectorAll('.unitword').forEach(s=>s.textContent=CUR==='inr'?'rupee':'dollar');
  document.querySelectorAll('.cv').forEach(el=>renderCV(el,animate));
  document.querySelectorAll('#curtog button').forEach(b=>b.classList.toggle('on',b.dataset.set===CUR));
}
const tog=document.getElementById('curtog');
if(tog)tog.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;CUR=b.dataset.set;applyCurrency(false);});
// scroll reveals + fire bars/counts when in view
const io=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');
  e.target.querySelectorAll?.('[data-w]').forEach(b=>b.style.width=b.dataset.w+'%');
  e.target.querySelectorAll?.('.cv.count').forEach(el=>renderCV(el,true));
  io.unobserve(e.target);}});},{threshold:.16});
document.querySelectorAll('[data-rise]').forEach(el=>io.observe(el));
applyCurrency(false);
addEventListener('load',()=>setTimeout(()=>{
  document.querySelectorAll('[data-w]').forEach(b=>b.style.width=b.dataset.w+'%');
  document.querySelectorAll('.cv.count').forEach(el=>renderCV(el,true));
},350));
</script>
</body>
</html>
```

## 6. Sample-data canon (keep consistent across screens)

- User: **Arjun** (avatar "A"). Joint contributor: **Priya** (You 58% / Priya 42%).
- Asset: **Devanahalli plot** — total ₹20,00,000; paid ₹12,40,000; remaining ₹7,60,000;
  8 installments of ₹1,50,000 base; #3 short by ₹60k rolled fwd; #5 carries +₹60k.
  Methods: cash / UPI / transfer / cheque. Funding: savings / loan / borrowed / sold-asset / chit-payout.
- Chit: **12-member auction**, pot ₹2,00,000, base ₹16,667/mo, 5% commission, round 5 of 12,
  your take = round 9; dividends earned ₹18,400.
- Loan taken (secured gold): **HDFC gold loan**, principal ₹6,00,000, owed ₹3,96,000, 8.5%,
  bullet/interest-only; collateral 92g 22K gold; LTV gauge w/ 75% lender cap.
- Loan given: **S. Mehta**, principal ₹7,00,000 (₹5L + ₹2L top-up), 2%/mo reducing, interest recd ₹28,000.
- Liability informal: **Borrowed — R. Kumar** ₹5,00,000, ₹3,10,000 left, no interest.
- 401(k) screen is USD-context (set `data-cur="usd"` default OK): limit $23,000, employer match,
  per-paycheck timeline, true-up, loan-offset planner.
- Holdings: gold 22K (some pledged), silver, equity index/stock, cash; USD/INR ticker; live prices.

## 7. Quality bar (every screen)
Same fonts/palette/motion/sidebar/topbar/toggle. Tabular-aligned mono figures. Hover states,
focus rings, consistent radii/spacing, grain + ledger-ruling lines. Charts = inline SVG
(line/donut/gauge/ring/sparkline) that animate on reveal (stroke-dashoffset / width). Realistic
Indian-context data. ₹/$ toggle MUST re-theme colors AND reformat every figure. Fully responsive.
Self-contained: inline `<style>` + inline `<script>`, Google Fonts only, vanilla JS.

## 8. Layout standard — columns fill to a shared bottom (NO blank space)

Every two-column section (main + rail) must end flush at the bottom — no column
leaves dead space under its last card. This is a **hard rule across all app screens**.

How it works (utility classes, present in every detail file's `<style>`):

```css
.fillcol{display:flex;flex-direction:column;gap:22px}          /* the column wrapper */
.fill{flex:1 1 auto;display:flex;flex-direction:column}        /* card that absorbs slack */
.fillrows{flex:1 1 auto;display:flex;flex-direction:column;justify-content:space-between} /* lists → space rows */
.fillmid{flex:1 1 auto;display:flex;flex-direction:column;justify-content:center}         /* charts → center */
```

To apply on a page:
1. The two-column grid keeps default `align-items:stretch` (never `align-items:start`)
   so both columns are forced to equal height.
2. Add `.fillcol` to the **shorter** column's wrapper (or both — harmless).
3. On that column, add `.fill` to the card chosen to absorb the slack — usually the
   longest **list** (ledger / schedule / loan-terms) or a **chart** card.
4. On that card's body add `.fillrows` (a row list → rows breathe via `space-between`)
   or `.fillmid` (a chart → centered with even padding).

Pick the slack-absorber per page so the result reads intentionally:
- **asset-detail** → Ledger (`.fill` + `.fillrows`)
- **chit-detail** → "Net position" chart (`.fill` + `.fillmid`); grid must NOT use `align-items:start`
- **dashboard (app.html)** → "Lent · S. Mehta" card (`.fill` + `.fillrows`)
- **loan-detail** → Loan terms card grows + rows distribute (same behavior, `.r-stack` column)
- **retirement-401k** → planner's numbered Steps absorb the slack (same behavior)
- **holdings** → already balanced (full-width sections), no fill needed

Rule of thumb: a row-list distributes (`.fillrows`), a chart centers (`.fillmid`),
and you never leave a column ending high with paper showing beneath it.
