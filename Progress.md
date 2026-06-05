# Khata — Progress & Resume Point

> **Read this first when resuming.** Single starting point — you should not need prior
> conversation to continue. The authoritative technical record is
> [`docs/specs/khata-AS-BUILT.md`](docs/specs/khata-AS-BUILT.md) (the from-scratch rebuild
> blueprint, updated in the same commit as every change). This file is the orientation layer.

**Last updated:** 2026-06-05
**Stage:** App fully built, deployed, and in active real-use iteration. 206 tests passing.
**Next action:** pick the next user-driven enhancement, or build the parked chit win-projection.

---

## Resume in 60 seconds
1. Read this file, then skim [`docs/specs/khata-AS-BUILT.md`](docs/specs/khata-AS-BUILT.md) (§9 = enhancement log, bottom = change log).
2. Code lives in this worktree: `/tmp/khata-landing` (branch `feat/landing-page`).
3. Run tests: `cd /tmp/khata-landing && PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q`
4. App is (or was) live on **:5057** — restart with `/Users/assistant/dev/active/khata/run-app.sh`.
5. Working habits (see *Process* below) are mandatory: update AS-BUILT doc + change log in the same commit; headless-verify UI before "done".

## What Khata is
Privacy-first, self-hosted personal **money-plans & net-worth ledger**. One trustworthy ledger
(single source of truth, proof images, precise timestamps), multi-currency (₹/$), multi-user with
shared plans. Plan types: asset purchase, chit fund, loan (given/taken, secured), 401(k)/retirement,
holdings + net worth.

## Architecture (locked)
- Flask 3.1 app-factory `create_app(cfg)` · SQLAlchemy 2.0 (typed) · Alembic (batch mode) · SQLite · pytest.
- **Static HTML pages + JSON APIs** — NO Jinja/render_template. Vanilla-JS client render (`createElement`+`textContent`, never innerHTML on API data = "K4").
- **Money = integer minor units (×100) / micro (×10⁶); balances DERIVED, never stored** — every `*_state()` recomputes from `ledger_entries`. No float.
- Layout: `src/khata/` = `models/ services/ api/ web.py static/ money.py config.py db.py`. CSS: `ledger.css` (landing, `.landing`-scoped) + `app.css` (app shell + detail panels).

## Deploy / run (canonical local instance)
- Port **5057** serves this worktree's code; **real user data** in `~/dev/active/khata/khata_app.db`; secret in `.env.app`; restart via `~/dev/active/khata/run-app.sh` (runs `alembic upgrade head` then boots).
- HTML served `Cache-Control: no-store` (always fresh). Static edits live on reload; **Python edits need run-app.sh restart**.
- venv: `/Users/assistant/dev/active/khata/.venv`. Demo seed DB `khata_live.db` (throwaway; `demo@khata.local` / `khata1234`).
- **Never wipe `khata_app.db`** (real data). Stage files explicitly — never `git add -A` (the live server rewrites `build_status.json`; `.env.*` and `khata_*.db*` stay untracked).

## Verification harness (use before any "done")
- **Headless jsdom** render at `/tmp/jsdomtest` (has `jsdom`): fetch-shim forwards to a temp server with the login cookie + stubs (`IntersectionObserver`, `requestAnimationFrame`, `confirm`, `scrollIntoView`, `mountSharing`). Catches silent JS throws. Cookie file is `#HttpOnly_`-prefixed — strip that prefix when parsing.
- Temp verify servers on ports **5058 / 5059** (kill after). Real screenshots via headless Chrome on a script-stripped DOM snapshot (`<base href>` + remove `<script>`).

## What's built (all shipped, tested, committed, pushed)
Full app to mockup fidelity (9 screens) + the real-use enhancements layered on while using it. Highlights this session:
- **Tag who paid** each ledger entry (`paid_by` → contributor shares + audit).
- **Two-party sharing consent — Phase 1**: invitations. Add a user → `invited` membership; plan hidden until they Accept (dashboard banner) / Decline (re-invitable). `plan_memberships.status`, `GET /api/invitations`.
- **Two-party — Phase 2**: per-entry amount agreement, counter-propose loop. `ledger_entries.amount_status`/`counter_amount_minor`; confirm/counter/accept until both agree; interim counts, flagged unconfirmed. `GET /api/confirmations`, `POST /api/plans/<id>/entries/<eid>/amount`.
- **Chit monthly schedule** + next-due reminder (derived; chit-detail month grid + overdue banner).
- **Whole-instance backup & restore** — in-app JSON (`GET /api/backup`, `POST /api/restore` merge) + CLI `scripts/backup.sh|restore.sh` (raw SQLite, replace). **Operator-gated** (first user or `KHATA_OPERATOR_EMAILS`); pre-restore snapshot `0o600`. (Security review addressed; `password_hash` intentionally kept in backup so restored logins work — documented in `services/backup.py:_row`.)

Migrations: `b7a1m3status1` (membership.status), `b8a2confirm1` (entry amount_status+counter). Batch mode, `server_default` for existing rows, round-trips verified.

## Parked / next
- **Chit win/return projection** — DESIGN LOCKED, not built. Inputs: win-month K, your bid B, assumed avg bid A. Outputs: prize pocketed (`V−B`), dividends earned (`(n−1)·(A−commission)/n`), net (`dividends−B`), **effective annual return via monthly IRR**, + early-vs-late context. Endpoint `GET /api/plans/<id>/chit/projection?win_month=&bid=&avg_bid=`; a "Win projection" card on chit-detail (assumptions clearly labeled). No schema change.
- Standing: build win-projection on request, then push.

## Git
- Branch `feat/landing-page`, pushed, level with `origin`. **PR #14** open: "App build: mockup-fidelity UI + real-use enhancements". 48 commits.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. PR footer: 🤖 Generated with Claude Code. No direct main push, no force-push.

## Process (mandatory habits)
1. **Every change updates `docs/specs/khata-AS-BUILT.md`** (relevant section + bottom change log) in the **same commit** — a rebuild reads the doc, not the app.
2. **Headless-verify UI** (jsdom render = 0 JS throws; screenshot for visual) before calling anything done.
3. TDD-ish: add/adjust tests; full suite green before commit.
4. **CAVEMAN MODE** is active (terse responses; code/commits/security written normally). Persists until user says "stop caveman".
5. Decisions are gathered via `AskUserQuestion`, design surfaced + approved before building (brainstorming gate).
