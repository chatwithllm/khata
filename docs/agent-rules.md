# Khata — Build Rules (incident-locked)

Rules here are derived from real bugs/decisions. Add a rule whenever a mistake
costs time, with a one-line "why". Never delete a rule without a superseding one.

## Locked rules
1. **TDD always** — write the failing test before implementation. No exceptions.
2. **Money is integer minor units** — store amounts as integer paise/cents in a
   given currency; never float. (Why: float rounding corrupts ledgers.)
3. **Balances are derived, never stored** — compute from ledger rows. (Why: stored
   balances drift out of sync — core product promise is a single source of truth.)
4. **Original currency + amount are immutable on a ledger entry** — conversions are
   display-only. (Why: rewriting history breaks audit trust.)
5. **Every external call (e.g. price API) must have a manual fallback.** (Why:
   privacy-first + offline-capable is a product promise.)
