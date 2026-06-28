# build-screen

Full build + verify protocol. Run this every time I ask you to build or fix any screen. No exceptions.

## Phase 1 — Read the mockup first
Fetch http://localhost:8888/MOCKUP_FILE
List every visible element: sections, panels, badges, colors, animations, interactions, empty states.
Do not write any code until this list is complete.

## Phase 2 — Diff against current dev
Fetch http://localhost:5056/ROUTE
Produce the same element list.
Write an explicit gap list — only build what is actually missing, never guess.

## Phase 3 — Build
- Implement only the gaps identified in Phase 2
- Scope all new CSS under the page class (e.g. .landing) — never leak into app shell
- Use real DB data only, graceful empty states, no hardcoded fiction
- Append to ledger.css, never replace it
- Prefix all new keyframes with land* and scope under .landing

## Phase 4 — Self-verify (run verify-screen)
Run all 6 steps from .claude/commands/verify-screen.md:
1. Raw HTML check — no unintended inline styles
2. Served CSS check — all keyframes present
3. Cache headers — HTML no-store, CSS versioned
4. Headless DOM render — zero JS throws, all panels present, animations firing
5. Mockup diff table — every row ✅ before declaring done
6. Tests — all green

If any step fails, fix in the same turn and re-run from Step 4.
Never report done until all 6 pass.

## Done output
Post this exact format and nothing else until it is true:

DONE ✅
Route: /ROUTE
Mockup: MOCKUP_FILE
Steps passed: HTML ✅ CSS ✅ Cache ✅ Headless ✅ Diff ✅ Tests ✅
Gaps found: N
Gaps fixed: N
Remaining: none
