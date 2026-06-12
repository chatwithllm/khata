# Per-Entry FX Rate Snapshots (Live Currency Conversion) — Design

**Date:** 2026-06-11
**Status:** Approved
**Goal:** Every ledger entry stores the FX rate as of the day it happened, editable afterward,
so the exact counter-currency (USD↔INR) value of every transaction is known forever. Live rates
come from frankfurter.app; the current rate refreshes daily.

## Why

Today Khata holds ONE manual FX rate per pair (`fx_rates`, set in Settings). Net worth and
dashboard convert historical amounts at *today's* rate — a ₹50,000 contribution from 2024
shows at the 2026 rate. Users want the dollar value the money actually had, and the ability
to correct the rate to what their bank actually gave them.

## Decisions (user-confirmed)

| Question | Decision |
|---|---|
| Rate source | frankfurter.app (free, no key, ECB daily, historical lookups) |
| Snapshot date | `occurred_at` date (backdated entries get the historically correct rate) |
| Backfill existing entries | Yes — one-time, all entries |
| Conversion policy | Per-entry rates everywhere a figure is a sum of ledger entries; spot/market values (holding qty × today's price, collateral market value) use the current rate — no entry exists to snapshot from |
| UI | Ledger rows + totals; edit-entry form gets an editable rate field |

## 1. Data model

`ledger_entries` gains two nullable columns (additive migration, no backfill in the migration
itself):

- `fx_rate_micro: BigInteger | None` — **counter-currency units per 1 entry-currency unit, ×1e6**.
  - INR entry → USD-per-INR, e.g. `11_364` (≈ $0.011364 per ₹1, i.e. ₹88 = $1)
  - USD entry → INR-per-USD, e.g. `88_000_000` (₹88.00 per $1)
- `fx_counter_currency: String(3) | None` — the other supported currency (`USD` for INR
  entries, `INR` for USD entries).

`NULL` = no rate known (created offline with no fallback available). `amount_minor` and
`currency` remain immutable; the rate is metadata about the entry, never a second amount.

Counter value is always **derived**: `counter_value_minor = convert(amount_minor, rate_micro=fx_rate_micro)`
(existing `services/fx.convert`, Decimal, ROUND_HALF_UP). It is serialized but never stored.

Why a pair rate and not entry→USD only: a USD entry viewed by an INR-base user needs the same
number. One field, both directions: divide or multiply depending on which side you stand on —
in practice the stored direction is always entry→counter, so it's always `convert()` forward.

## 2. Live-rate client — `services/fx_live.py` (new module)

Isolated from `services/fx.py` (which stays pure DB/math). stdlib `urllib.request` only — no
new dependency.

- `fetch_rate(d: date, base: str, quote: str) -> int | None`
  `GET https://api.frankfurter.dev/v1/{d.isoformat()}?base={base}&symbols={quote}` →
  `rates[quote]` × 1e6 as int. 4-second timeout. ANY failure (network, non-200, parse, missing
  key) → `None`. Never raises into a request flow.
- `fetch_latest(base, quote) -> int | None` — same against `/v1/latest`.
- `fetch_range(start: date, end: date, base, quote) -> dict[date, int]`
  `GET /v1/{start}..{end}?base=&symbols=` — one call for backfill. frankfurter omits
  weekends/holidays in ranges; callers map a missing date to the nearest prior business day.
  Single-date lookups already auto-return the last business day.
- frankfurter quotes whole-unit rates (INR per USD); minor-unit math is unaffected because the
  rate is unit-per-unit and amounts are minor in both currencies (both ×100).

## 3. Snapshot on create — `services/fx.snapshot_entry_rate(session, entry, explicit_rate_micro=None)`

Called by every entry-create path (asset/holding contributions via `assets.add_ledger_entry`,
loan entries, chit entries) after the entry is constructed, before flush returns. Fallback
chain:

1. `explicit_rate_micro` from the client (validated int > 0) — wins.
2. `fx_live.fetch_rate(entry.occurred_at.date(), base=entry.currency, quote=counter)`.
3. Stored manual rate: `fx.get_rate(session, base=counter, quote=entry.currency)` → already
   handles inversion (note: `get_rate`'s return is quote-per-base in its own convention; the
   helper normalizes to entry→counter direction).
4. `None` — entry saves fine without a rate.

`counter` = the other member of `SUPPORTED_CURRENCIES` (`{INR, USD}`). If support grows beyond
two currencies, counter becomes the **user's base currency at log time** — out of scope now.

## 4. Edit

- `PATCH /api/plans/<plan_id>/entries/<entry_id>` (existing endpoint/permissions) accepts
  `fx_rate_micro` (int > 0; 422 otherwise). Editing the rate does NOT touch `amount_minor`,
  `amount_status`, or confirmations.
- Entry serialization (ledger arrays in every `*_state`) gains:
  `fx_rate_micro`, `fx_counter_currency`, `counter_value_minor` (derived, null when rate null).

## 5. Conversion policy changes

- `services/networth.py` and `services/dashboard.py`: wherever a converted figure is a **sum of
  ledger entries** (paid-to-date, contributions, i-owe / owed-to-me, asset value = money in),
  sum `convert(entry.amount_minor, entry.fx_rate_micro)` per entry when the entry's currency ≠
  target and a snapshot exists; entries with `NULL` rate fall back to the current stored rate
  (exactly today's behavior — no regression, no double conversion).
  When entry currency == target currency, the amount passes through untouched (snapshot ignored).
- **Spot values keep the current rate:** holding market value (qty × today's price) and
  collateral market value are *today's* figures; converting them at historical rates would be
  wrong, and there is no entry to take a rate from.

## 6. Daily refresh — scheduler

`scheduler.py` `_tick` gains an FX job next to the backup job, same `KHATA_ENABLE_SCHEDULER=1`
gate: once per UTC day (tracked via the existing tick; claim guard mirrors backups' atomic
claim so two gunicorn workers don't double-fetch), `fetch_latest(USD, INR)` → on success,
upsert via existing `fx.set_rate(base=USD, quote=INR, rate_micro, as_of=now)`.
Settings' manual rate entry still works; the next daily refresh overwrites it (Settings hint
text says so).

## 7. Backfill — `POST /api/admin/fx-backfill` (admin-only)

- Collect distinct `occurred_at` dates of entries with `fx_rate_micro IS NULL`.
- One `fetch_range(min_date, max_date, USD, INR)` call; missing dates (weekends) map to nearest
  prior business day in the result.
- Fill `fx_rate_micro` + `fx_counter_currency` per entry (deriving direction from each entry's
  currency). Skip entries that already have a rate → idempotent, safe to re-run.
- Returns `{filled: n, skipped: n, no_rate: n}`.
- **Prod DB write — run once, manually, after deploy, with explicit user authorization.**

## 8. UI

- **Ledger rows** (asset/loan/holding/chit/retirement detail + dashboard ledgers): when an
  entry has a snapshot, a small mono line under the amount: `$568.18 @ ₹88.00/$` (counter value
  + rate in natural direction — the side that is ≥1). No snapshot → no second line.
- **Edit-entry form**: rate field, prefilled from the snapshot, shown in natural direction
  ("1 USD = ₹88.00"); saving converts back to entry→counter micro. Clearing the field leaves
  the snapshot unchanged (explicit value required to change it).
- **Settings**: existing FX box gains hint: "Refreshes daily from ECB (frankfurter.app); manual
  entries are overwritten at the next refresh."

## 9. Error handling

- frankfurter unreachable/slow → fallback chain (§3); entry creation NEVER blocks on FX.
- Backfill with frankfurter down → `no_rate` count, nothing written for those, re-run later.
- `fx_rate_micro <= 0` or non-int on create/PATCH → 422 with detail.
- Scheduler fetch failure → log, keep previous stored rate.

## 10. Testing

- `fx_live`: mocked `urlopen` — success, timeout, non-200, malformed JSON, range with weekend gaps.
- Snapshot chain: explicit wins; live wins over stored; stored fallback; all-fail → NULL.
- PATCH: valid rate persists; 0/negative/garbage → 422; rate edit leaves amount/status alone.
- Conversions: mixed ledger (some snapshots, some NULL) sums correctly per policy; same-currency
  passthrough; spot values still use current rate.
- Backfill: fills only NULLs, idempotent re-run, weekend-dated entries get prior business day.
- Scheduler: claim guard prevents double-fetch; failure keeps old rate.
- Serialization: ledger rows expose the three new fields; null-rate rows expose nulls.

## Out of scope (YAGNI)

- Currencies beyond INR/USD (schema is generic; counter selection logic is the only 2-currency
  assumption, marked in §3).
- FX rate history table (per-entry snapshots ARE the history).
- Gain/loss reporting on FX movements.
- Mobile app (separate WIP branch).
