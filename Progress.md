# Khata — Progress & Resume Point

> **Read this first when resuming.** It is the single starting point — you should
> not need any prior conversation to continue. Pair it with the design spec and
> the implementation plan (linked below).

**Last updated:** 2026-06-04
**Stage:** Design complete · Phase-1 / Plan-1 written · **implementation NOT started**
**Next action:** Execute Plan 1 (see *Resume in 30 seconds*).

---

## Resume in 30 seconds
1. Read this file.
2. Skim the spec: [`docs/specs/2026-06-04-khata-design.md`](docs/specs/2026-06-04-khata-design.md)
3. Open the plan: [`docs/superpowers/plans/2026-06-04-khata-phase1-foundation.md`](docs/superpowers/plans/2026-06-04-khata-phase1-foundation.md)
4. Execute it task-by-task (TDD). Recommended: superpowers **subagent-driven-development** (fresh subagent per task) or **executing-plans** (inline, batched with checkpoints).
5. Update `build_status.json` + append to `docs/AGENT_LEARNINGS.md` as you go.

---

## What Khata is
A privacy-first, self-hosted personal **money-plans & net-worth ledger** for patterns
generic budgeting apps don't model. One trustworthy ledger (single source of truth,
proof images, precise timestamps), multi-currency (₹/$), multi-user with shared plans.

**Plan types:**
- **Asset purchase** — irregular installments, roll-forward when you under/overpay, funding sources, joint contributors + ownership share.
- **Chit fund (chitti)** — pure rotating + auction; member/organizer; dividends, commission, net position.
- **Loan** — given or taken; unsecured or secured (collateral/LTV); EMI or bullet; interest tiers; tranches/top-ups.
- **401(k)** — contribution maximizer (fill limit without losing employer match) + loan-offset planner.
- **Holdings + net worth** — gold/silver/cash/stocks at live prices; unrealized gain; **hold-vs-sell** decision insight (gold appreciation vs loan interest).

## Decisions locked (don't re-litigate without reason)
- **Standalone app** named **Khata** (खाता = ledger). Not a module inside LocalOCR.
- **Web-first**, self-hosted, responsive (works in phone browser). Native mobile = later phase.
- **Stack:** Flask + SQLAlchemy 2.0 + SQLite (WAL) + Alembic backend · vanilla-JS SPA · Docker.
- **Multi-user from Phase 1**: accounts (local password + Google OAuth), shared plans, per-payment contributor attribution, auto ownership share. (User chose full multi-user in MVP.)
- **Multi-currency** ₹/$ with primary-currency theming (INR = saffron/paper, USD = greenback). Ledger keeps original currency+amount immutably; conversion is display-only.
- **Money = integer minor units; balances are always derived from ledger rows** (locked build rules).
- **Live prices**: auto-fetch (only external call) + manual fallback (offline-capable). Added in Phase 3.
- **In-app Features & limitations tab** + a **development learning loop** ship continuously, each phase.

## Build phases (MVP-first)
| Phase | Ships |
|---|---|
| **1 — MVP** | Asset + Loan (unsecured) · ledger + proof · roll-forward · dashboard · **multi-user + ownership share** · INR |
| 2 | Chit funds (pure/auction) · multi-currency ₹/$ |
| 3 | Holdings + live prices + net worth + hold-vs-sell · secured loans (collateral/LTV/EMI/bullet) |
| 4 | 401(k) · OCR screenshot→amount autofill · native mobile |

## Phase-1 plan series (each ships working software)
1. **Foundation & local auth** — WRITTEN, ready to execute (`docs/superpowers/plans/2026-06-04-khata-phase1-foundation.md`).
2. Plan + ledger core (integer money, derived balances) + Asset type + roll-forward + asset API. *(to write)*
3. Loan type (given/taken, unsecured): tranches, interest accrual, principal-vs-interest ledger. *(to write)*
4. Sharing & contributors: PlanMembership, per-payment attribution, ownership share, net-position dashboard. *(to write)*
5. Google OAuth + polished Features/limitations page wired to mockups. *(to write)*

## What exists right now
- `README.md` — project overview + run instructions.
- `docs/specs/2026-06-04-khata-design.md` — the full design spec (the brainstormed intent brief).
- `docs/mockups/` — **9 HTML mockups** (open in a browser) + PNG previews:
  `index.html` (landing, currency-themed) · `app.html` (dashboard) · `asset-detail.html` (incl. joint contributors) · `chit-detail.html` · `loan-detail.html` (secured/gold) · `holdings.html` (net worth + hold-vs-sell) · `retirement-401k.html` · `log-payment.html` (entry sheet) · `create-plan.html` (wizard).
- `docs/superpowers/plans/2026-06-04-khata-phase1-foundation.md` — Plan 1 (10 TDD tasks).
- **No source code yet.** `src/` is empty — Plan 1 creates `src/khata/...`.

## Git
```
99820c1 docs(plan): Phase 1 / Plan 1 — foundation & local auth (TDD)
a1f1fe0 chore(init): scaffold Khata project + design spec + mockups
```
Local repo only (no GitHub remote yet — push when ready).

## Still flexible (settle during execution)
- Exact dependency pins / Python patch version.
- Hosting/deploy specifics (Docker compose) — Phase 1 runs via `wsgi.py` on localhost:5050.
- Backup/export format.
- GitHub remote + CI.

## Open follow-ups captured but not yet planned
- Cross-plan links (chit payout funds an asset payment) — model supports it; UI/flow in later phases.
- Per-user net-worth views once sharing lands (Plan 4).
