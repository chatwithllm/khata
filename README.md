# Khata — personal money-plans & net-worth ledger

A privacy-first, self-hosted app for the money patterns generic budgeting tools don't model: buying assets in irregular installments, running/joining **chit funds**, lending & borrowing (secured and unsecured), tracking **holdings** (gold/silver/cash/stocks) at live prices, and a **401(k)** contribution planner — all as one trustworthy ledger with proof, multi-currency, and multi-user contribution sharing.

> Working name: **Khata** (खाता — ledger/account).

## Status
**Phase 1 · Plan 1 complete** — Flask + SQLite (WAL) + Alembic foundation with local
multi-user auth (register / login / logout / session / current-user). Test-first; 11 tests green.
Next: Plan 2 (Plan + ledger core, Asset type with roll-forward installments).

## Stack (default, web-first)
Flask + SQLAlchemy + SQLite (WAL) + Alembic · vanilla-JS SPA · Docker. Responsive web first; native mobile later.

## Run locally
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=src KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
PYTHONPATH=src .venv/bin/python wsgi.py   # http://localhost:5050
.venv/bin/python -m pytest -v             # run tests
```

## Plan types
- **Asset purchase** — installments, roll-forward, proof, funding sources, joint contributors + ownership share.
- **Chit fund** — pure rotating + auction, member/organizer, dividends/commission, net position.
- **Loan** — given or taken, unsecured or secured (collateral/LTV), EMI or bullet, interest tiers, tranches.
- **401(k)** — contribution maximizer (keep full match), loan-offset planner.
- **Holdings + net worth** — live prices, unrealized gain, hold-vs-sell decision insight.

## Cross-cutting
Multi-user accounts (local + Google) with shared plans & contributor attribution · multi-currency (₹/$) with primary-currency theming · in-app **Features & limitations** tab · development **learning loop**.

## Build phases
1. **MVP** — Asset + Loan (unsecured) · ledger + proof · roll-forward · dashboard · multi-user + ownership share · INR.
2. Chit funds (pure/auction) · multi-currency.
3. Holdings + live prices + net worth + hold-vs-sell · secured loans.
4. 401(k) · OCR autofill · native mobile.

## Docs
- Design spec: [`docs/specs/2026-06-04-khata-design.md`](docs/specs/2026-06-04-khata-design.md)
- Mockups (open the `.html` in a browser; `.png` previews): [`docs/mockups/`](docs/mockups/)
  - `index.html` landing · `app.html` dashboard · `asset-detail.html` · `chit-detail.html` · `loan-detail.html` · `holdings.html` · `retirement-401k.html` · `log-payment.html` · `create-plan.html`

## Planning
GSD/superpowers artifacts in `.planning/`.

## Rebuild blueprint
The authoritative as-built spec (data model, APIs, state contracts, deviations, deploy) lives in [`docs/specs/khata-AS-BUILT.md`](docs/specs/khata-AS-BUILT.md) — read it to rebuild from scratch without hunting the app.
