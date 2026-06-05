# Khata — Delivery Roadmap (remaining work)

**As of 2026-06-04.** Phases 1–2 are complete and merged (PRs #1–#7). This roadmap sequences **all
remaining work** to a feature-complete product, in dependency order. Each numbered item is one
brainstorm → spec → plan → subagent-build → PR cycle (the rhythm used for Plans 1–2B).

## Operating mode (autonomous)
The user granted autonomy to execute this roadmap. Per-plan rhythm:
1. Decide the design (record assumptions in the spec instead of asking, unless a choice is genuinely
   product-defining or irreversible) → write `docs/superpowers/specs/…` and commit.
2. Write `docs/superpowers/plans/…` (TDD, bite-sized tasks) and commit.
3. Execute subagent-driven (implementer + spec-review + quality-review per task; final integration
   review).
4. Push + open a PR; merge it; sync `main`; update this roadmap's checkboxes.
**Surface to the user only:** genuine product forks, irreversible actions, or blockers. Otherwise keep
moving. Locked rules carry forward: money = integer minor units (no float) · quantities = integer
micro-units · rates = integer (bps / rate_micro) · balances/values **derived, never stored** · original
currency immutable · owner-scoped + auth-gated APIs · one honest ledger.

## Status snapshot
**Backend domains DONE:** auth (email/pw + Google) · sharing/membership · asset purchases + ledger ·
loans (given/taken, derived interest) · holdings (avg-cost, quotes) · net worth + cross-currency FX.
**Real pages DONE:** landing+login (`/`) · features (`/features`) · holdings net worth (`/holdings`).
**Everything else below is TODO.**

---

## Phase 3 — Authenticated App UI build-out
Turn the remaining mockups into real pages wired to the **already-built** APIs. Lowest ambiguity,
highest usability payoff; little new backend. Shared `ledger.css` + a real app shell.

- [x] **3.1 App shell + dashboard** (`app.html`). Real `/app`: sidebar nav, client-side auth guard
  (`GET /api/auth/me`, redirect to `/` on 401), overview from `GET /api/dashboard` + `GET /api/networth`,
  plan list from `GET /api/plans`, currency/base toggle, profile + logout. Foundation every other
  Phase-3 page mounts into.
- [x] **3.2 Create-plan flow** (`create-plan.html`). Wired form → `POST /api/plans` for asset | loan |
  holding (type switch, asset installments builder). Redirect to the new plan's detail.
- [x] **3.3 Asset detail + log-payment** (`asset-detail.html`, `log-payment.html`). Schedule,
  roll-forward, funding breakdown, contributors, payment log; wired to detail + `installments` +
  `payments`. Log-payment as a shared modal.
- [x] **3.4 Loan detail** (`loan-detail.html`). `loan_state` (principal/interest/schedule),
  disbursements + interest/principal entries; wired to the loan endpoints.
- [ ] **3.5 Holding detail + sharing panel.** Per-holding page (buy/sell/quote, position history) +
  a reusable members panel (add/remove via `POST/GET/DELETE /api/plans/<id>/members`) surfaced on every
  plan detail. Closes the loop on Plan-4 sharing in the UI.

**Phase 3 done when:** a user can sign in and fully operate every existing domain from the browser
(create, log, view, share) with no curl.

---

## Phase 4 — New domains (backend + UI per plan)
Each adds a new plan type / capability the same way Plans 2–3 were built. Higher ambiguity — specs will
record the chosen product model explicitly.

- [x] **4.1 Chit funds** (`chit-detail.html`). New `chit` plan type: members, monthly contributions,
  payout mechanism (default: monthly **auction**, lowest-bid-wins, dividend split among members — to be
  fixed in the spec), derived per-member ledger + pot/payout state. Reuses the plan/membership spine.
  Backend + UI.
- [x] **4.2 Secured loans / collateral.** Extend the loan domain: pledge a holding (or asset) as
  collateral, `secured` flag, derived LTV (collateral current value ÷ principal outstanding); surface
  in loan detail + net worth (collateral isn't double-counted). Backend + UI.
- [x] **4.3 Retirement / 401(k) planner** (`retirement-401k.html`). Contributions + employer match +
  a derived projection (corpus at retirement under assumed return/inflation, all integer/Decimal).
  Backend (a `retirement` plan type or a projection service) + UI.

**Phase 4 done when:** chit funds, secured loans, and the retirement planner are usable end-to-end.

---

## Phase 5 — Settings, hardening & advanced
- [x] **5.1 Account settings.** Google-created users set a password; edit display name + profile photo;
  base-currency & FX management UI; clears the deferred auth follow-ups.
- [x] **5.2 Hardening sweep.** Burn down the `AGENT_LEARNINGS.md` deferred follow-ups: `add_buy`/
  `add_sell` `None`-qty → `ValidationError` guard + holdings edge tests (sell-to-zero, multiple sells,
  quote=0); reconcile the unused `session` arg across `*_state`/`net_worth`; `fmtMicro` null guard;
  expose `loan_state` `as_of`; index `ledger_entries(plan_id, kind)`; type-filter `list_plans`; DB
  `CHECK`/unique constraints (`plans.type`, `installments(plan_id, seq)`); fold net worth into the main
  dashboard or unify the two rollups; `verify_google_credential` transport-error handling.
- [x] **5.3 Analysis tools** (`holdings.html` analysis section). Gold-loan-vs-selling decision
  calculator (hold-and-borrow vs sell: appreciation vs interest cost, net outcome) + any other what-if
  views. Pure derived calculators.
- [ ] **5.4 Live market feeds (optional, last).** Replace manual quotes + FX with an **optional**
  market-data integration (spot gold/silver, equity, FX), behind config, manual entry as fallback when
  unconfigured (same graceful-degradation pattern as Google sign-in).

**Phase 5 done when:** settings are complete, all logged follow-ups are cleared, the analysis tools
ship, and (optionally) live feeds are wired with manual fallback.

---

## Sequencing rationale
3 before 4: the UI makes the existing backend usable and surfaces real gaps before new domains pile on.
4 before 5: new domains should exist before settings/analysis/feeds polish them. 5.4 (external
integration) is deliberately last and optional. Hardening (5.2) items are also folded in opportunistically
whenever a relevant file is touched earlier.

## Definition of done (product)
Sign in (email/pw or Google) → create & operate every plan type (asset, loan, holding, chit, secured
loan, retirement) from the browser → share plans with attribution → see a correct, cross-currency net
worth → run the analysis tools → optionally pull live prices. Self-hosted, privacy-first, exact-to-the-
paise, no float, balances derived.
