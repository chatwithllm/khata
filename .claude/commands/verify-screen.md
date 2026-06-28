# verify-screen

Self-verification protocol. Run this on every screen before reporting done.
Arguments: $ROUTE (e.g. /app) and $MOCKUP (e.g. app.html)

## Step 1 — Raw HTML check
```bash
curl -s http://localhost:5056$ROUTE | grep -E "(class=|data-w|data-d|style=)" | head -40
```
Confirm: no unintended inline styles, correct data attributes, no server error HTML.

## Step 2 — Served CSS check
```bash
curl -s "http://localhost:5056/static/assets/ledger.css?bust=$(date +%s)" \
  | grep -E "@keyframes|animation:|transition:|width:\s*0"
```
Confirm: every keyframe referenced in HTML exists in served CSS.

## Step 3 — Cache headers
```bash
curl -sI http://localhost:5056$ROUTE | grep -i cache
curl -sI http://localhost:5056/static/assets/ledger.css | grep -i cache
```
Confirm: HTML = `no-store`, CSS = versioned (`max-age` or `304`).

## Step 4 — Headless DOM render
```bash
node /tmp/dbg.mjs $ROUTE 2>&1 | tail -40
```
If `/tmp/dbg.mjs` doesn't exist, create it fresh (jsdom harness with fetch shim).
Confirm: no JS throws, every expected panel/element present, animations firing.

## Step 5 — Mockup diff table
Open http://localhost:8888/$MOCKUP and http://localhost:5056$ROUTE.
Produce this table — fill every row before declaring PASS:

| Section | Mockup has | Dev has | Match |
|---------|-----------|---------|-------|
| (fill one row per visible section, badge, animation, color) |

## Step 6 — Tests
```bash
cd /Users/assistant/dev/active/khata && python tests/test_web.py 2>&1 | tail -5
```
All must stay green.

## Done condition
Only report "DONE" after ALL 6 steps pass with zero open rows in the diff table.
If any row shows a gap, fix it in the same turn and re-run from Step 4.
