# Khata — Mockup Generation Prompt

Hand the prompt below to any capable model (v0, Claude, GPT, etc.) to generate the
full set of UI mockups in one consistent design language — no vague input needed.
Generate screens one at a time (paste the prompt, then say "Build: <screen>").

---

## THE PROMPT (copy everything below this line)

You are a senior product designer + front-end engineer. Build **production-grade, visually
distinctive** HTML mockups for a web app called **Khata**. Avoid generic "AI slop" — no Inter,
no Roboto, no purple-on-white gradients, no cookie-cutter Bootstrap look. Commit fully to the
art direction below and execute it with precision.

### Product
Khata is a privacy-first, self-hosted **personal money-plans & net-worth ledger** for money
patterns generic budgeting apps ignore. It is INR-native but multi-currency. It tracks:
- **Asset purchase** — buying a big asset in irregular installments; short/over payments
  "roll forward" to the next installment; payments tagged by method + funding source + proof;
  multiple people (e.g. husband/wife) can contribute with auto ownership-share.
- **Chit fund (Indian chitti)** — rotating money pool; pure or auction variant; member or
  organizer; monthly contributions, who took the pot, winning bids, commission, dividends,
  your running net position.
- **Loan** — money given out or taken; unsecured or secured (gold/property collateral, LTV);
  EMI or bullet/interest-only; interest tiers; principal-vs-interest ledger; top-up tranches.
- **401(k)** (US) — contribution maximizer that fills the annual limit without losing the
  per-paycheck employer match; 401(k)-loan offset planner.
- **Holdings + net worth** — gold/silver/cash/stocks valued at live market prices; unrealized
  gain; a **hold-vs-sell** insight comparing an asset's appreciation against loan interest paid.

### Art direction — "editorial ledger"
Warm, refined, accounting-book feel. Not flashy; confident and clean.
- **Typography:** display = **Fraunces** (characterful serif, weights 400–600, use italics for
  emphasis); body = **Hanken Grotesk**; all numbers/figures = **JetBrains Mono** with tabular
  digits. Load from Google Fonts. Never use Inter/Roboto/Arial.
- **Currency-driven theming** (important): a primary-currency toggle (₹ INR / $ USD) re-themes
  the entire UI live AND reformats numbers:
  - **INR theme** = Indian rupee-note palette: warm paper cream `#F7F1E6`, deep ink `#241B16`,
    primary saffron `#C05E1B`/`#9C4711` (₹200 note), positive emerald `#1F6B53`, magenta accent
    `#9E3B6E` (₹2000 note). Numbers use **Indian grouping** (₹2,00,000; lakh/crore abbreviations
    like ₹12.4L, ₹1.18Cr).
  - **USD theme** = greenback palette: pale bill-green paper `#E9EFE8`, deep green-ink `#16241B`,
    dollar-green `#1C7A45`/`#115C32`, treasury-seal gold accent `#A9852F`. Numbers use **Western
    grouping** ($14,900; k/M abbreviations). Demo FX: 1 USD = 83 INR.
  - The currency symbol, grouping, and color theme all switch together with a smooth transition.
- **Motion:** one well-orchestrated page-load with staggered reveals (animation-delay); scroll-
  triggered reveals (IntersectionObserver); animated count-ups for headline figures; bars/rings
  that fill on reveal. Easing `cubic-bezier(.22,.68,0,1)`. Respect `prefers-reduced-motion`.
- **Texture/depth:** subtle SVG film-grain overlay; thin "ledger ruling" lines; soft layered
  shadows; dominant color with sharp accents (not timid even palettes).
- **Layout:** generous negative space; clear hierarchy; app screens use a left sidebar + top bar;
  marketing landing is a single scroll. Fully responsive (works on a phone browser).

### Technical constraints
- Each screen = **one self-contained `.html` file** — inline `<style>` + inline `<script>`, no
  build step, no external CSS/JS except Google Fonts. Vanilla JS only (no React/Vue).
- Use CSS variables for the theme; implement the ₹/$ toggle by swapping a `data-cur` attribute
  on `<html>` that overrides the variables, plus a JS reformat of every figure (store each
  figure's base value in a data attribute; render Indian vs Western grouping per currency).
- Money shown as if integer-accurate; tabular figures aligned. Accessible contrast, semantic HTML,
  keyboard-focusable controls.
- Each figure that represents money carries its base amount in a `data-` attribute so the toggle
  can re-render it; abbreviated styles (lakh/crore vs k/M) supported.

### Deliverables — build these screens (one file each)
For every screen: include the sidebar/topbar (for app screens) with the working ₹/$ toggle, the
art direction above, on-load + scroll animations, and realistic Indian-context sample data.

1. **`index.html` — Landing (marketing).** Sticky nav with ₹/$ toggle + Sign in. Hero: headline
   ("Money the way you actually pay it"), subhead, two CTAs, and a live dashboard-preview card
   (animated net-position count-up + 2–3 plan rows with filling progress bars). Trust strip
   (privacy-first · single source of truth · multi-currency). Problem section (dark, ledger-ruled).
   Two-to-three plan-type cards. "Single source of truth" ledger sample with proof. 3-step
   how-it-works. Net-position finale with Google + local sign-in. Footer. A subtle row of swatches
   echoing Indian rupee-note denomination colors (recolor for USD).
2. **`app.html` — Dashboard.** Sidebar (Dashboard, Holdings, Assets, Chit funds, Loans, Ledger,
   Settings). Top bar (greeting, ₹/$ toggle, "Log payment", avatar). 4 stat cards: Net position
   (hero, inverted), Paid to date, I owe, Owed to me. Then panels: active asset with progress +
   installment schedule (roll-forward badges), a recent ledger, a chit-fund summary with a round
   strip, and a liabilities/loans list. Count-ups + bar fills on load.
3. **`asset-detail.html` — Asset (with joint contributors).** Header KPIs (paid/remaining/total)
   + progress + recent-pace estimate. Full installment schedule (planned vs paid, statuses,
   "−₹60k rolled fwd" and "+₹60k carried in" badges). Full ledger (method + funding-source pills,
   in/out, proof). Right column: funding-source **donut** (savings/borrowed/chit/sold) with legend;
   **Contributors** panel (e.g. You 58% / Priya 42% with a stacked share bar and per-person totals);
   projection card + payment sparkline; linked liability; proof thumbnail gallery.
4. **`chit-detail.html` — Chit fund (auction, organizer+member).** Header (variant, role, pot,
   base/mo, commission, round X of N) + KPIs. **Rounds table**: per round → taker, winning bid
   (discount %), commission, dividend/member, your effective pay; mark completed rounds, the
   current round, and the round you plan to take (highlighted). A **"net position over rounds"**
   line chart that dips while you pay in then jumps up when you take the pot, settling positive.
   My-position breakdown + a member roster with took/paid/pending status (you highlighted).
5. **`loan-detail.html` — Secured loan (gold).** Header (Loan·taken, secured, rate, basis, bullet)
   + KPIs (principal owed / interest paid / next interest). Repayment-structure segmented control
   (Bullet vs EMI). Ledger splitting interest from principal prepayments + disbursement. Right:
   **Collateral card** (gold weight/purity/₹-per-gram → valuation, an **LTV gauge** with a lender-
   cap line, pledge status, link-or-standalone); loan terms; a **release tracker** ("clear ₹X more
   to release the gold").
6. **`holdings.html` — Holdings & net worth.** Top: a **live price ticker** (gold 24K/22K, silver,
   an index, a stock, USD/INR with up/down + "auto-fetched · tap to set manually"). Holdings list
   (gold [pledged], silver, equity, cash) valued live with gain %. **Net-worth** breakdown
   (own − owe). The standout: a **"Gold loan vs selling"** decision card — two columns (Held &
   borrowed vs Sold instead) with appreciation vs interest, a **gold-appreciation-vs-interest
   crossover line chart**, and a live verdict chip ("Holding ahead by ₹X").
7. **`retirement-401k.html` — 401(k) planner (USD).** Stats (contributed YTD / annual limit /
   match captured / **match at risk**). **Contribution maximizer**: a recommended-% ring, and two
   **per-paycheck timelines** (Recommended fills on the last check = match every period; Current
   too-high % maxes early so the last checks turn red = match lost), with a true-up toggle and a
   warning quantifying $ lost. Per-paycheck breakdown + match formula. **401(k)-loan offset**
   planner: numbered steps to lower the contribution to free repayment cash while staying above
   the match line, with the tradeoff + payoff date.
8. **`log-payment.html` — Log-payment slide-over.** A right slide-over sheet over a dimmed
   dashboard. Fields: plan picker, entry-type segmented (Installment/Extra/Adjust), amount with a
   ₹/$ dropdown + "of ₹X due", date+time, method chips (cash/UPI/transfer/cheque) SEPARATE from
   funding-source chips (savings/loan/borrowed/sold-asset/chit-payout), a proof dropzone with an
   "OCR detected ₹X" chip, a note. Sticky footer **live preview** computing roll-forward
   ("+₹60,000 → #6, balance after ₹6,10,000"). Save / Cancel.
9. **`create-plan.html` — Create-plan wizard.** A centered wizard over a dimmed dashboard. Step
   rail (Type ✓ · Details · Schedule · Review). A 5-card plan-type picker (Asset / Chit / Loan /
   401(k) / Holding). Below it, the **adaptive details form** for the selected type (show Chit:
   name, variant auction/pure, role member/org+me, members, pot, commission, slot/take, start) with
   an auto-computed contribution line and a plain-language summary banner. Back / Continue footer.

(Optional extras if asked: `settings.html` — currency/FX, price source auto/manual, auth methods,
backup/export; `features.html` — every feature with its honest limitations.)

### Quality bar
- Cohesive across all screens: same fonts, palette tokens, motion, sidebar/topbar, ₹/$ toggle.
- Realistic Indian-context data (names, ₹ amounts in lakhs, UPI, gold in grams/22K).
- The ₹/$ toggle MUST actually re-theme colors AND reformat every figure (Indian vs Western
  grouping). Demonstrate it works.
- Polished micro-details: hover states, focus rings, tabular number alignment, consistent radii
  and spacing, subtle grain + ledger lines. Nothing should look like a default template.

Build the requested screen now as a single complete HTML file. If I name a screen, build only that
one; if I say "build all", produce them in sequence as separate files.

---

## Reference
The original mockups (already built in this exact style) are in `docs/mockups/` — use them as the
visual source of truth if the model supports image input. The full product spec is in
`docs/specs/2026-06-04-khata-design.md`.
