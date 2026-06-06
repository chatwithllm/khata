# Personal Money-Plans Tracker ("Khata") — Intent Brief

> **As-built / rebuild blueprint:** see [`khata-AS-BUILT.md`](./khata-AS-BUILT.md) for the current implemented system (data model, APIs, state contracts, deviations, deploy). This file is the original *intent brief* (the why).

## One line
A privacy-first personal app to plan and track the money commitments I run in irregular, real-world Indian patterns — buying an asset in piecemeal installments, and participating in or running chit funds — recording every transaction as a single source of truth with proof, live balances, and my true net position across all of them, in multiple currencies.

## Problem / context
My money moves in ways generic budgeting apps don't model. I buy a big asset by paying small portions whenever funds appear, from mixed sources. I also join (and sometimes run) chit funds — rotating money pools where everyone contributes monthly and each member takes the full pot once over the cycle. Today this lives in my head and scattered notes. I want one trustworthy ledger that tells me, at any moment: what I've paid, what remains, what I owe and to whom, what I'm owed, and where I stand net across every plan.

## Core concept — two plan types, one spine
The app holds multiple money plans. Each plan is one of two types today, but they share a common spine: a plan/schedule of expected money movements + a ledger of actual movements, with all balances computed from the ledger (never stored stale).

### Type 1 — Asset purchase (installments)
- I set a total price and an initial installment plan (intended amounts + dates).
- I log each actual payment against the plan.
- The plan adapts via roll-forward: a short or surplus payment carries to the next installment; later ones untouched until I edit. Original plan preserved for comparison.
- Each payment records how money moved (cash / transfer / cheque), where it came from (savings / loan / borrowed / sold-asset / chit payout / other), a precise timestamp, and proof images (receipt / chat / screenshot).
- Borrowing to pay creates a Loan (direction = taken) with its own repayment ledger — so I see both "remaining on the asset" and "what I still owe people/banks."

### Type 3 — Loan (given or taken)
A single Loan entity with a direction covers both money I owe and money I'm owed:
- **Direction**: taken (I borrowed — a liability) · given (I lent out — a receivable).
- **Counterparty**: lender or borrower (free text, optional contact).
- **Interest type**: none · % per month · % per year.
- **Interest basis**: reducing balance (rate × current outstanding) OR flat (rate × original) — chosen per loan.
- **Compounding**: unpaid interest accrues as arrears OR capitalizes into principal — chosen per loan.
- **Tranches (top-ups)**: principal is a series of dated disbursements, each optionally its own rate. Outstanding principal = Σ tranches − Σ principal repaid. Example: lend ₹5,00,000, later add ₹2,00,000 → ₹7,00,000; interest then accrues on the new outstanding (reducing) or per original tranche, per config.
- **Ledger separates principal and interest**: disbursement, interest accrual (auto, monthly), interest received/paid, principal repaid. Always shows principal outstanding and interest due separately.
- **Repayment structure** (per loan): EMI (fixed monthly principal + interest, amortization schedule) OR bullet / interest-only (pay interest monthly, principal lump at maturity).
- **Schedule**: expected monthly interest or EMI; flags missed months.
- **Collateral (secured loans)**: a loan-taken can pledge security — type (gold / property / vehicle / fixed-deposit / other), valuation (gold: weight + purity + ₹/gram; property: market value), loan-to-value with lender cap, lender, where held, pledge status (pledged → released when principal hits zero). Collateral can reference a tracked asset OR be a standalone record.
- Loans-given roll into "Owed to me"; loans-taken into "I owe".

### Type 2 — Chit fund (chitti)
Per chit, I pick:
- My role: member · organizer · organizer+member.
  - Member — track only my position: contributions, the month I take the pot, dividends earned, my net.
  - Organizer — run the scheme: member roster, monthly collection, the auction/draw each round, commission, dividend split.
  - Organizer+member — both.
- Variant:
  - Pure rotating — pot = members × contribution; taker gets the full pot; equal, no commission, order by lottery/agreement. Net-zero over the cycle; value is liquidity timing + forced saving.
  - Auction (bidding) — each round members bid a discount to take the pot early; lowest taker wins; the forgone discount minus organizer commission is split back to all members as a dividend. Early taker effectively borrows at interest; late taker effectively saves at a return.
- Tracks, per chit: monthly contributions, who took the pot each round (and at what discount), commission, dividends, and my running net position (total paid − payout received + dividends earned = effective profit/loss).

## Holdings & net worth (what I own)
Beyond money *plans*, the app tracks what I already own, valued live — turning it into a net-worth picture.
- **Holdings**: gold, silver, cash, stocks (extensible to MF/crypto). Each with quantity (grams / shares / amount), cost basis, buy date. Gold carries weight + purity.
- **Live market prices**: gold/silver spot (₹/g, 22K/24K), stock quotes, FX. Sourced **auto** from a market-data API when online (public market data only — no personal data leaves), with **manual entry/override** always available so it runs fully offline. Current value = quantity × price; unrealized gain = value − cost basis.
- **Net worth** = holdings value + receivables (loans given) − loans taken − remaining asset commitments ± chit net. One rolled-up number.
- **Hold-vs-sell decision insight**: when a holding is pledged as loan collateral, compare *holding + borrowing* (keep the asset, pay interest, capture appreciation) against *selling instead* (cash now, no interest, no upside). Live verdict: which choice is ahead, by how much, with a gold-appreciation-vs-interest-paid crossover chart — so I know whether borrowing against the asset beat selling it, as the market moves.
- **Collateral ties to holdings**: a pledged holding is flagged encumbered; its live valuation feeds the loan's LTV.

## Multi-currency
- Primary being INR and USD; designed to add more later.
- Per-plan currency: each asset / chit / liability stores its own native currency.
- Primary display currency: I choose ₹ or $; the whole app and the net-position roll-up convert to it via a stored FX rate. Switching is instant.
- Ledger entries keep their original currency + original amount permanently — conversion is display-only, history is never rewritten (audit integrity).
- UI theme follows the primary currency (rupee palette for ₹, greenback for $).

### Type 4 — Retirement · 401(k) planner (US)
A US-specific planner for tax-advantaged retirement accounts.
- **Contribution maximizer**: given annual employee limit (e.g. $24,500), YTD contributed, pay-period schedule (biweekly/semimonthly/monthly), salary, and the employer match formula (tiered, e.g. "100% of first 3% + 50% of next 2%"), compute the per-paycheck % that fills the limit on the *last* paycheck — so the per-paycheck match is captured every period. Warns if the current rate hits the cap early and quantifies the match $ lost.
- **True-up toggle** (per account): if the employer trues-up missed match at year-end, front-loading is safe; if not, the spread guidance matters. Default OFF (stricter, more common).
- **401(k) loan offset**: model a loan from the account (payroll repayment, interest paid to self). Planner shows how to reduce the contribution rate to free cash for repayment while staying above the match threshold — repay the loan without losing match — and the tradeoff (lower year fill, payoff date).
- **Balance as holding**: the 401(k) balance counts in Holdings / net worth, tagged pre-tax · illiquid.

## Cross-links between plans
- A chit payout is a valid funding source for an asset payment — one plan's inflow can feed another's outflow.
- Everything rolls up into a single dashboard: across all plans, what I owe, what I'm owed, and net.

## Authentication & multi-user
- **Multi-user accounts** (not single-user): each person (e.g. husband, wife) has their own login.
- Two sign-in methods per user: local username + password, plus Google sign-in (OAuth). Privacy-first: local credentials work without any third party; self-hosted on family hardware.
- Sessions per user; passwords hashed; standard account lifecycle (register, login, reset).

## Collaboration & contributors
A plan (asset, chit, loan, etc.) can be **shared** among users who contribute to it.
- **Plan membership**: a plan has an owner + invited members. Invite by username/email.
- **Per-payment attribution**: every ledger entry records which user logged/made it. So a jointly-bought asset shows each contributor and their respective payments.
- **Ownership share**: each member's % share of the asset auto-computed from their cumulative contributions (e.g. husband 58% / wife 42%), updating as payments land. (Manual override possible later.)
- **Permissions (defaults, refinable)**: members add/edit their own payments and view the whole shared plan; others' entries are read-only to them; the owner manages membership and plan settings. Private (unshared) plans stay visible only to their owner.
- **Per-user net worth**: each user sees their own holdings + their share of joint assets and obligations.

## Landing page (public face)
A meaningful pre-login landing (public at /, app behind sign-in at /app) saying what generic finance apps don't: this models how money actually moves — installments and chit funds — privately, in your currency.
- Hero with live dashboard preview + currency toggle; problem section; two plan-type cards; single-source-of-truth ledger; 3-step how-it-works; net-position finale with Google + local sign-in.
- Aesthetic: editorial "ledger" look — warm paper + saffron + emerald for ₹, greenback green + gold for $. Fraunces serif + Hanken Grotesk + JetBrains Mono figures.

## Features & limitations tab (in-app)
A built-in **Features** tab that lists every feature with a plain description **and its honest limitations** — so users know what each does and where it stops. It is living documentation, kept in sync with what's actually built each phase.
Example limitations to surface candidly:
- Live prices need internet (manual entry works offline); rates are indicative, not tick-by-tick.
- OCR autofill (later phase) is best-effort — always verify the extracted amount/date.
- Ownership share reflects recorded *contributions*, not legal title.
- Chit auction math assumes the standard discount-minus-commission dividend model; unusual chit rules may need manual adjustment.
- FX uses a stored rate for display roll-up, not a real-time rate per transaction.
- 401(k) planner is guidance, not tax/financial advice; verify limits and match formula with your plan.
- Self-hosted, family-scale — not a multi-tenant/enterprise product.

## Key behaviors
- Single source of truth: every balance/position derived from ledger rows.
- Reusable & multi-plan: many assets and many chits, concurrently.
- Adaptation: asset plans roll forward; chit positions recompute as rounds resolve.
- Liabilities & receivables first-class: I always know net exposure.
- Proof + precise timestamps on transactions.
- Privacy-first: my financial data stays under my control by default.

## UI layout conventions (mockups)
These are **standard across every screen**; new screens must follow them. Full CSS in `docs/mockups/_SHARED_KIT.md`.
- **No blank space (hard rule):** every two-column section fills to a shared bottom. Columns are forced equal height (grid `align-items:stretch`, never `start`); the shorter column's slack-absorbing card gets `.fill` and its body `.fillrows` (lists → rows breathe) or `.fillmid` (charts → centered). See _SHARED_KIT §8 for the per-screen absorber (asset→Ledger, chit→chart, dashboard→Lent, loan→Loan-terms, 401k→Steps).
- **No purple anywhere:** data/light accents use petrol `--accent`; dark-surface emphasis (hero cards, finale, dark headers) uses honey-gold `--accent-dk`; bright-mint `--pos-dk` for green-on-dark. The currency toggle re-themes all of it.
- **Complete amounts where space allows:** show full grouped values (₹12,40,000 / $14,900) on cards, KPIs, tables, ledgers; abbreviate (₹12.4L) only in genuinely tight cards (e.g. the landing dashboard-preview).
- **Topbar:** greeting heading + mono date subtitle · refined ₹/$ toggle (serif glyphs) · saffron "Log payment" · green squircle avatar (click to upload a photo, persisted via localStorage) · "New plan" lives in the sidebar.

## Conceptual domain model (stack-neutral)
- MoneyPlan (abstract) → AssetPurchase | ChitFund | Loan | Retirement401k. Each carries a native currency.
- Retirement401k — annual limit, YTD, pay schedule, salary, employer match formula, true-up flag, optional 401(k) loan; produces per-paycheck contribution guidance + match-at-risk.
- ScheduleItem → asset Installment (planned amount/date) | chit Round (month, pot, taker, bid/discount, commission, dividend).
- LedgerEntry — actual money in/out: amount + original currency, datetime, method, source/dest, plan + schedule-item links, liability link, proof.
- Attachment — proof image bound to a ledger entry.
- Loan — direction (given/taken), counterparty, interest type/basis/compounding, repayment structure (EMI/bullet), with: LoanTranche (dated principal disbursements / top-ups) + LedgerEntry rows typed as disbursement / interest-accrual / interest-payment / principal-repayment. Subsumes borrowed liabilities and lent receivables.
- Collateral — pledged security on a loan-taken: type, valuation (gold weight/purity/rate or property value), LTV + lender cap, lender, location, pledge status. Optionally references an owned asset (MoneyPlan) or stands alone.
- ChitMember (organizer mode) — roster + per-member contribution/payout tracking.
- User + AuthIdentity — multiple users; each supports Google OAuth and/or local password credentials.
- PlanMembership — links Users to a shared MoneyPlan with a role (owner / contributor) and permissions.
- Contribution attribution — each LedgerEntry references the User who made/logged it.
- OwnershipShare — per-user % of a shared asset, auto-derived from contributions (manual override optional).
- Holding — type (gold/silver/cash/stocks/…), quantity, cost basis, buy date; gold has weight + purity. Optionally pledged as Collateral.
- PriceQuote — market price per instrument (auto-fetched or manual), timestamped; drives live valuation.
- FxRate — currency conversion rates for display roll-up.
- Position/Balance — always computed, per plan and rolled up to the primary currency.

## Delivery & route (decided)
- **Standalone app** (its own repo) named Khata — not a module inside LocalOCR.
- **Web-first**, self-hosted: browser UI + server + SQLite, responsive so it works in a phone browser. A native mobile app comes in a later phase.
- **Default stack** (adjustable at planning): Flask + SQLAlchemy + SQLite (WAL) + Alembic backend · vanilla-JS SPA frontend (the mockups are vanilla HTML/CSS/JS and map directly) · Docker.
- **Auth**: multi-user from Phase 1 — local username/password + Google OAuth, shared plans with contributor attribution.
- **Live prices**: the one external dependency (market-data API), with manual fallback — added in the holdings phase.

## Development process — learning loop
The build runs under a learning loop so the project gets smarter as it grows:
- An `AGENT_LEARNINGS.md` + project rules file: every bug, decision, deviation, and surprise becomes a recorded rule that informs later tasks/phases (the web-app-builder discipline — project rules, per-task done-gate, progress dashboard, learning capture).
- Per-phase learning extraction: at the end of each phase, decisions/lessons/patterns are distilled and carried forward.
- The in-app **Features & limitations tab** is updated each phase to match what actually shipped — limitations stay truthful, not aspirational.

## Build phasing (MVP-first)
- **Phase 1 — MVP / the spine**: Asset purchase + Loan (given/taken, unsecured). Ledger as single source of truth, proof image attach (no OCR), per-payment method + funding source, roll-forward installments, dashboard with net position. INR only. **Multi-user**: accounts (local + Google), shared plans, per-payment contributor attribution, auto ownership-share — so the husband/wife joint-asset case works in v1.
- **Phase 2**: Chit funds (pure rotating + auction, member/organizer). Multi-currency (₹/$) with primary toggle + theming.
- **Phase 3**: Holdings + live market prices + net worth + hold-vs-sell decision insight. Secured loans (collateral, LTV, EMI/bullet).
- **Phase 4**: 401(k) planner. OCR screenshot→amount autofill. Native mobile app.
- **Every phase** scaffolds/extends the in-app Features & limitations tab and appends to the learning log — both ship continuously, not at the end.
- Still flexible: exact stack confirmation, hosting specifics, backup/export format — settled when writing the Phase 1 plan.

## Success criteria
- Open the app → instantly see, per plan and overall: paid, remaining, next due, debt outstanding, and net position — in my chosen currency.
- Every transaction is traceable to a method, source, timestamp, original currency, and (where relevant) proof.
- Off-schedule / odd payments re-project sensibly without losing original intent.
- Chit math (pure and auction) reflects my true gain/loss including dividends and commission.
- Nothing leaves my control unless I deliberately choose cloud sync.

---
*Working name: Khata (खाता — ledger/account). Mockups: index.html (landing), app.html (dashboard).*
