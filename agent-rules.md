# Agent Rules — Web-Stack Baseline
# Skill: web-app-builder · This is the BASELINE copied into each new project.
# Status: BINDING — every rule here was locked in by a real defect.
# An agent that violates a rule will reproduce the exact bug that created it.
#
# READ THIS FILE AT THE START OF EVERY TASK. Treat every applicable rule as a
# hard constraint, not a suggestion.
#
# APPLICABILITY TAGS — each rule is tagged. Apply only the rules that match your task:
#   [all]      every task
#   [server]   backend / API / Node / Fastify / Express tasks
#   [db]       schema, migrations, SQL, transactions
#   [client]   React / frontend tasks
#   [planning] writing or reviewing specs and plans
#
# The project-level copy of this file is authoritative. New rules append here as
# incidents occur (see learning-loop.md). The skill baseline is the starting point.

---

## RULE 0 — What "Done" Means  [all]

A passing build or `tsc` exit 0 is **compile proof only**. It is **not** done.
Done means every line of the done-gate checklist is true — see `done-gate.md`.

In one sentence: a green compile, a clean log, and "it renders" each prove a
different small thing; none of them prove the task. The done-gate proves the task.

If any gate line is not true → NOT done. Debug, fix, repeat. Do not report done.
**Never** hand the user a smoke-test checklist — that transfers verification to them.
Perform every check yourself. At most one or two explicit "could not auto-verify X
because Y" lines are acceptable; a numbered list of manual steps is not.

---

## RULE 1 — Pre-Flight Before Writing API or Client Code  [server] [client]

Before writing a route handler, a fetch call, a TypeScript request/response type, or
a client API function, confirm reality from the code — not from the plan.

```bash
# 1. Confirm the route exists and its HTTP method (read the actual router file)
grep -rnE "\.(get|post|put|patch|delete)\(" src/ | grep -i "<feature>"

# 2. Read the EXACT response shape the handler returns
grep -rn "reply.send\|res.json\|return {" src/ | grep -i "<feature>"
# then read the whole handler — note every key, exactly as spelled

# 3. Confirm what the existing frontend sends/expects for the SAME endpoint
grep -rn "fetch(\|api\.\|axios" src/ web/ | grep -i "<feature>"
```

**Why:** plans drift from code. The plan can name an endpoint that does not exist, or
a shape that was refactored. A handler invented from the plan returns 404 or decodes
into an empty screen. The build looks correct and ships broken.

If any check returns zero matches → STOP and ask. Do not guess the path or the shape.

---

## RULE 2 — Mirror the API Contract Verbatim  [server] [client]

The client type must match the server's actual JSON, key-for-key, envelope and all.

- Server returns `{ items: [...], next_before: "..." }` → the client decodes a wrapper
  type, then reads `.items`. Do **not** decode a bare array.
- Server returns flat fields (`short_name`, `is_admin`) → the client type is flat. Do
  **not** invent nesting because it would be "cleaner."
- A field the server may omit is `T | undefined` on the client, not `T`.

Reality beats opinion. Mirror the schema exactly, even when a tidier shape is tempting.
A shape mismatch is a silent empty-data bug, not a compile error.

---

## RULE 3 — Audit and Side-Effect Writes Share the Mutation's Transaction  [server] [db]

**Source: review of admin-role spec/plan** — a reject endpoint ran the row UPDATE and
its audit-log INSERT as two separate `pool.query` calls. A crash between them leaves the
mutation done and the audit row missing.

Any write that *records* another write — an audit row, an event log, an outbox row, a
counter — must run in the **same transaction** as the mutation it records. Either both
land or neither does.

```ts
// ❌ Wrong — two independent statements; a crash between them desyncs them
await pool.query(`UPDATE pending_users SET outcome='rejected' WHERE id=$1`, [id]);
await writeAudit(pool, { action: 'reject_user', target_pending_id: id });

// ✅ Correct — one transaction, both or neither
const client = await pool.connect();
try {
  await client.query('BEGIN');
  await client.query(`UPDATE pending_users SET outcome='rejected' WHERE id=$1`, [id]);
  await writeAudit(client, { action: 'reject_user', target_pending_id: id });
  await client.query('COMMIT');
} catch (e) { await client.query('ROLLBACK'); throw e; }
finally { client.release(); }
```

A single CTE is also fine when it expresses the whole operation:
`WITH done AS (UPDATE ... RETURNING id) INSERT INTO audit SELECT id, ... FROM done`.

---

## RULE 4 — Postgres `FOR UPDATE` Is Rejected With Aggregates  [db]

**Source: review of admin-role spec** — a last-admin guard used
`SELECT COUNT(*) ... FOR UPDATE`. Postgres rejects it: `ERROR: FOR UPDATE is not
allowed with aggregate functions`. The query never runs.

To lock a set and act on its size, lock the rows, then count them in application code:

```sql
-- ❌ Wrong — throws at runtime
SELECT COUNT(*) FROM users WHERE is_admin AND id <> $1 FOR UPDATE;

-- ✅ Correct — lock the candidate rows, count the result in code
SELECT id FROM users WHERE is_admin AND id <> $1 FOR UPDATE;
-- if the returned row count is 0 → reject; the lock blocks a racing writer
```

`FOR UPDATE` is also rejected with `GROUP BY`, `DISTINCT`, `UNION`, and window
functions. When you need a locked count, lock the plain rowset.

---

## RULE 5 — `ON DELETE SET NULL` Requires a Nullable Column  [db]

**Source: review of admin-role spec** — an audit table declared
`actor_id UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL`. The two clauses
contradict: when the referenced user is deleted, Postgres tries to set the column NULL
and the `NOT NULL` constraint rejects it — the delete fails.

If a foreign key uses `ON DELETE SET NULL`, the column must be nullable. If the column
must be `NOT NULL`, use `ON DELETE RESTRICT`, `NO ACTION`, or `CASCADE` instead — pick
the one that matches the intended retention semantics. Self-contradictory DDL may even
fail at `CREATE TABLE` time depending on the Postgres version.

---

## RULE 6 — Verify Column Constraints Before Writing an INSERT  [db] [server]

**Source: review of admin-role plan** — code `INSERT`ed into `users(short_name, ...)`
with a derived value, without ever reading whether `short_name` had a `UNIQUE`
constraint. If it does, a collision raises an unhandled Postgres unique-violation that
surfaces as a 500 instead of a clean error.

Before writing any `INSERT` into an existing table, read that table's definition in
`schema.sql` (or the migrations). Note every `NOT NULL`, `UNIQUE`, `CHECK`, and default.
Then:

- A value that could collide with a `UNIQUE` column → catch Postgres error code `23505`
  and return a clean `409` (or auto-suffix / regenerate), never let it 500.
- A `NOT NULL` column with no default → the INSERT must supply it.
- A `CHECK` constraint → validate before the INSERT so the user gets a real message.

---

## RULE 7 — Cleanup Jobs Null FK References — Snapshot Identity Before Reaping  [db] [server]

**Source: review of admin-role plan** — a reaper deletes rows after a TTL; an audit
table referenced those rows via `ON DELETE SET NULL`. Minutes after the event, the
audit row's foreign key is NULL and the row no longer says *which* record it was about.

If a row may be deleted by a cleanup/reaper job, and other tables (audit, history,
analytics) reference it for the record, do not rely on the foreign key for identity.
**Snapshot the identifying fields** — email, name, a human label — into the referencing
row's own columns or its `metadata` JSON at write time. The FK is for joins while the
row lives; the snapshot is what survives the reaper.

---

## RULE 8 — Migrations Are Additive and Idempotent; Never Edit an Applied Migration  [db]

A migration that has run on any shared or production database is immutable. To change
schema, write a **new** migration.

- Use `ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS` so re-running is safe.
- New columns on a populated table are nullable or carry a default — a bare
  `NOT NULL` add on existing rows fails.
- Editing an already-applied migration desyncs every environment that ran the old
  version. The fix is always a forward migration, never an edit.

---

## RULE 9 — React Effects That Subscribe or Poll Must Clean Up  [client]

**Source: admin-role approval-queue polling** — an "awaiting approval" view polls an
endpoint every few seconds. An effect that starts a `setInterval`, a WebSocket, or an
event listener and does not return a cleanup function leaks: the timer keeps firing
after the component unmounts, and on every dependency change a new one stacks on top.

```tsx
// ✅ Every subscribe/poll effect returns its teardown
useEffect(() => {
  const id = setInterval(poll, 5000);
  return () => clearInterval(id);   // runs on unmount and before re-run
}, [pendingId]);
```

Also: do not fetch in render; give list items stable keys (never the array index for a
reorderable or filterable list); never read or write `localStorage`/`sessionStorage`
inside a Claude artifact (use in-memory state there).

---

## RULE 10 — Every Touched File Gets a Rule Re-Grep Before Commit  [all]

**Source: native-app-builder I-14, generalized** — a fix agent edited the named lines
of a file and committed, leaving a pre-existing rule violation elsewhere in the same
file untouched. Because no future task will ever name those lines, the violation
becomes permanent.

Before `git commit` on any file you touched (via edit or write):

1. Re-grep the **whole file** for active banned patterns relevant to its kind —
   `[server]`/`[db]` file → check for split-transaction audit writes, `FOR UPDATE` with
   aggregates, un-handled unique violations; `[client]` file → check for cleanup-less
   effects, index keys.
2. Any live match (not in a comment) → fix it in the **same commit**. Do not defer
   with a TODO.
3. Note the cleanup in the commit message.

Every file you touch is your responsibility end-to-end. A pre-existing violation in a
touched file is a regression in disguise.

---

## RULE 11 — A Fact Stated in More Than One Place Is a Contradiction Risk  [planning]

**Source: review of admin-role spec** — the approve operation was described as
"DELETE the row" in three sections and "UPDATE the row" in the authoritative endpoint
spec. A build agent could implement either reading.

When writing or reviewing a spec or plan: each fact has one authoritative home. Other
places point to it; they do not restate it. If a fact is restated, the copies drift.
When reviewing, treat any fact stated in multiple places as a contradiction risk —
diff the statements and reconcile every copy to the authoritative one before the plan
is executed. The build agent should never have to guess which version is correct.

---

## RULE 12 — Empty-State Bootstrap Tests Must Run Against the Empty State  [server] [db] [all]

**Source: KanbanClaude admin-role build, QA Step 1** — a "first user auto-admin"
branch was silently broken because every test that touched the admin endpoints
seeded users directly into the DB and flipped `is_admin` by hand. The branch's
only trigger — registering against a genuinely empty `users` table — was never
exercised.

If a feature has a code path that fires only when a table or state is empty
(first-user setup, first-message bootstrap, first-run config init, install
hooks), the test for it MUST:

- Clear the relevant table at the top of the test (or run in a dedicated empty
  fixture).
- Verify the empty precondition with an explicit assertion before the action.
- Use only the public path (HTTP route, command, real init flow) — NOT seed data
  + a hand-flipped flag.

A test that seeds the trigger state never proves the empty-state branch is even
wired in. A compile/typecheck does not catch this — the dead branch compiles fine.

---

## RULE 13 — Client Parity for Auth + Config-Gated Features  [client] [all]

**Source: KanbanClaude macOS Google sign-in, QA Step 9** — the backend correctly
returned `google_enabled: true` via `/api/auth/config`, the web LoginView correctly
fetched that config and showed a Google button, but the macOS LoginView didn't
fetch the config at all and had no Google button. The Google button was scoped
only to a post-login Account tab — useless for users who couldn't sign in yet.

If a feature is reachable on ONE client (web/native/mobile), it must be reachable
on EVERY client that has a comparable entry point — particularly auth methods,
which by definition are pre-login. Before declaring such a feature shipped:

- List every client's entry-point view (login, register, settings, etc.).
- For each: confirm the feature has a UI surface there OR an explicit "not on
  this client v1" note in the spec.
- Config-gated features must fetch the same config endpoint on every client and
  hide UI consistently when disabled. Hardcoded gating (always-show, always-hide)
  is a bug.

A feature that only works in the web client because no one wired the native path
is a half-ship. The done-gate must include a parity check.

---

## RULE 14 — Decode Cross-Client Codable Models Against Real Captured Payloads  [client]

**Source: KanbanClaude macOS admin users decoding failure** — `AdminUserRow.swift`
looked correct field-for-field by reading the route handler, but failed against the
actual JSON because a DB-nullable column (`short_name`) mapped to a non-optional
Swift `String` field and Swift's `JSONDecoder` rejected `null`. The web client
and the native client used different decoders — web's `JSON.parse` is permissive
with nulls and missing keys; Swift's `JSONDecoder` (and other strict typed
decoders — Kotlin's kotlinx.serialization, Go's encoding/json with required tags,
Rust's serde) are strict on types and required keys. The mismatch surfaced only
at runtime.

Before declaring any cross-client Codable / decodable model "done":

- Curl the real endpoint, capture the JSON to a file.
- Write a tiny standalone decode test that loads that file and decodes the model.
  Decode MUST succeed.
- Include regression cases for every nullable DB column that maps to a non-optional
  client field: test with `null` and with the key absent entirely.
- Commit the captured sample alongside the test so future schema drifts surface
  at decode-test time rather than at runtime.

Static reading of "the server returns X" lies about TIMESTAMPTZ → Date → string
coercion, about pg COUNT(*) coming back as int vs string, about COALESCE(…, '[]')
vs null, about UUID case quirks, and about DB-nullable columns the server code
usually fills. The decode-against-real-payload test is the only thing that's
truthful.

---

## RULE 15 — Capped Exponential Backoff on Every Reconnect/Retry Loop  [client] [all]

**Source: KanbanClaude macOS WebSocket reconnect storm** — the WebSocket client
looked like it had backoff (500ms→10s) but its backoff reset on every `hello`
message. A flaky auth state caused brief connects + immediate drops; backoff
reset every iteration and the client hammered the server every ~1s.

Any client-side reconnect or retry loop (WebSocket, polling, retry-after-failure
fetch, queue consumer) MUST:

1. Start at a floor ≥1 second. A 500ms or 100ms floor will overwhelm a service in
   trouble.
2. Double after each failure, capped at ≥10 seconds (30s for a long-lived
   connection is reasonable).
3. Reset to the floor ONLY after a sustained successful interval — receipt of a
   handshake/hello/ack alone is not enough. A successful connect that immediately
   drops should count as a failure, not a success.
4. Log the next-attempt delay so operators can spot a storm at a glance.

A retry loop without an explicit cap + sustained-success reset is a footgun
waiting for an outage to reveal it.

---

## RULE 16 — A Retry-Loop Fix Is Verified, Not Assumed  [client] [all]

**Source: KanbanClaude macOS WS storm recurrence** — RULE 15 was correctly
applied to `scheduleReconnect`, but the storm continued. The root cause was a
different caller (cached-user bootstrap) starting the reconnect loop while the
user was unauthenticated. The backoff math was on the right code; the wrong
code was calling it. A second recurrence after a defensive fix turned out to be
a stale binary running — the install pipeline put an older `.app` in `/Applications`
than what was built. The source was correct; the running artifact was not.

When fixing any retry/reconnect loop, BEFORE declaring the fix done:

1. Grep for every caller of `connect()` / `retry()` / `reconnect()`. List them.
2. For each: verify it can ONLY fire under a precondition that makes the retry
   meaningful (authenticated, target reachable, prerequisites met). A caller
   that can fire pre-condition is a hidden loop driver.
3. Gate the operation INSIDE the function being called, not only at the call
   site. Defense in depth — a future caller can't bypass the gate.
4. Reproduce the failure end-to-end after the fix, using the freshly-built and
   freshly-installed binary. Watching the backoff numbers in unit tests doesn't
   prove the storm stopped if a different caller triggers it — or if the user
   is testing yesterday's `.app`.
5. **Multi-client apps: audit EVERY client implementation of the protocol** —
   not just the one the bug initially appeared in. (KanbanClaude I-9: a web WS
   storm was misattributed to the macOS client through three fix rounds because
   no one grepped `new WebSocket` in the web frontend. The web ws.ts had the
   same Rule 15 defect — reset backoff on first onopen — that the macOS client
   already had. Server logs don't distinguish clients by default; tag /ws log
   lines with the client identity, e.g. User-Agent or a custom header, so the
   real culprit surfaces immediately.)

A retry-loop fix that hasn't been verified end-to-end with a fresh build of the
actual binary on the actual platform is not a fix — it's a hypothesis.

---

## RULE 17 — Init Script Is the Complete Source of Truth for a Fresh DB  [db] [server]

**Source: KanbanClaude — notifications table missing from schema.sql.** The
notifications feature's tables lived in `server/migrations/2026-05-03-notifications.sql`
ONLY. The project's init flow is `psql ... -f schema.sql`, which doesn't run
migrations. Fresh databases (CI test runs, QA setups, new contributor onboarding)
silently had no `notifications` table. Notification tests failed for "infra"
reasons and were dismissed.

The principle generalizes to any project whose init flow is a single command
(`npm run db:init`, `flask db init`, `make db.reset`, `prisma migrate reset`,
`alembic upgrade head` against a baseline, etc.):

- Every CREATE TABLE / CREATE INDEX / ALTER TABLE / column-add that any feature
  depends on MUST be reachable by that init command from an empty DB.
- New schema lands as: (a) the dated migration file, AND (b) wired into whatever
  the init command consumes — either appended to `schema.sql` (with idempotent
  IF NOT EXISTS guards) or registered with the migration runner. The two stay
  in lockstep.
- Before declaring any feature done, run the init command against a FRESH
  database (drop + create) and exercise the feature's test suite. Existing tests
  passing on the dev DB prove nothing if the dev DB was incrementally migrated
  rather than init'd from scratch.
- "Pre-existing failure, unrelated" is not a status — it's a triage step. Each
  pre-existing failure has a real cause; classify it before dismissing.

---

## RULE 18 — Service-Worker Cache Name Bumps on Every Frontend Fix  [client]

**Source: KanbanClaude — web WS storm "fix" that wouldn't reach users.** The web
client had a real backoff bug. The fix was committed. The storm persisted in
production because every open tab had cached the OLD bundle via the service
worker (`CACHE = 'kanban-v1'`) and there was no activate-handler cleanup of old
caches. Tabs kept serving the buggy bundle indefinitely.

For any project with a service worker that caches the frontend bundle:

1. The cache name (`CACHE = 'foo-vN'`) MUST bump on every frontend change that
   alters compiled assets. Tie it to a build hash, a version constant, or a
   manually-incremented N — anything that changes when the bundle does.
2. The `activate` handler MUST delete every cache whose name doesn't match the
   current `CACHE`. Without this, old caches accumulate and old tabs serve old
   code:
   ```js
   self.addEventListener('activate', (e) => {
     e.waitUntil((async () => {
       const names = await caches.keys();
       await Promise.all(
         names.filter((n) => n !== CACHE).map((n) => caches.delete(n)),
       );
       await self.clients.claim();
     })());
   });
   ```
3. Verify the fix on a tab that was OPEN against the old code: hard-reload OR
   re-register the worker OR clear site data — match how a real user's tab
   would land on the new bundle.

A frontend fix that doesn't ship to already-open tabs is a hypothesis, not a
fix. Treat the service worker's cache lifecycle as part of the deployment
contract.

---

## RULE 19 — Pin Dependency Installs to a Framework-Compatible Version  [server] [client] [all]

**Source: KanbanClaude I-10 — admin-role build cutover crash.** Task 10
ran `npm install google-auth-library @fastify/rate-limit` with no version
constraint. npm grabbed `@fastify/rate-limit@10.3.0`, which targets
Fastify 5. The project runs on Fastify ^4.28.1. The mismatch surfaced only
at production cutover when the server crash-looped — `npm install`, `tsc`,
`docker build`, and 228 passing tests all looked green because none of them
booted a real Fastify app with the plugin loaded.

For any dependency install (npm, pnpm, yarn, cargo, pip, gem, go get):

1. **Always specify a version constraint compatible with the project's
   framework major.** `npm install <plugin>` → `npm install <plugin>@^X`
   where X is the latest release that supports the project's framework. For
   plugins of any framework (Fastify, Express, Vue, Rails, Django…), check
   the plugin's release notes / peerDeps BEFORE installing.

2. **Pre-flight grep the project's framework major** before picking a version:
   ```bash
   grep '"<framework>":' package.json   # e.g. "fastify": "^4.28.1"
   ```
   Then on the registry page (or in CHANGELOG), find the highest plugin
   major that lists the project's framework major as a peer / supported range.

3. **Adding a plugin to an existing app must include a boot-time smoke test**
   — start the server (or a minimal harness that does the actual
   `app.register`) and confirm it boots. Unit tests don't catch peerDep
   mismatches because they typically stub the plugin or don't load the full
   plugin chain.

A plugin installed without checking framework compatibility is a production
outage waiting for the next deploy.

---

## RULE 20 — A Fix Is Not "Done" Until Committed — Stash Is Not a Deliverable  [all]

**Source: KanbanClaude I-10.** The `@fastify/rate-limit` v10→v9 downgrade
was identified locally during the macos-build push. The fix was applied to
`package.json` + `package-lock.json` in the working tree, then **stashed**
instead of committed. The stash held the correct version for hours while
the broken `^10.3.0` stayed in source. Production cut over to the broken
version. After the prod crash, the local stash was popped, committed, and
PR-merged — but the outage had already happened.

The per-task done-gate MUST verify:

1. **The fix is committed.** `git status` is clean (no uncommitted/stashed
   changes related to the fix). `git log` shows the commit. The fix exists
   in a branch, not just a working tree or stash.
2. **The fix is pushed and merged into the deploy source** (main, or
   whatever branch the deploy reads from). `git log origin/main --grep="<fix description>"`
   finds it. A fix on a local branch that hasn't been pushed is still not
   shipped.
3. **`git stash list` is empty at end-of-task.** Stashes accumulate fixes
   that were tested-then-deferred. A stash that survives the task is a bug
   carrier — either commit it, drop it, or document it as deferred work
   (with a tracking issue).

Working code in a working tree is not a fix. A fix that doesn't reach the
deploy artifact is a hypothesis. The done-gate must distinguish "the change
behaves correctly here" from "the change ships."

---

## RULE 21 — Production Is Deploy-Only — Boot the Artifact on Dev First  [all] [server]

**Source: KanbanClaude I-10 — workflow principle behind the rate-limit crash.**
The broken image (`@fastify/rate-limit@10.x` against Fastify 4) was never
booted anywhere before prod. `npm install`, `tsc`, 228 tests, and `docker
compose build` all passed — none of them actually started the container.
The first place that image ran was the prod cutover. It crashed in <1 second.

Then the fix was hand-applied directly on the prod VM (sed pin → delete
lock → rebuild on prod → restart) under incident pressure. Source control
caught up afterwards via PR #41. For the window between hot-patch and PR
merge, prod and main were divergent — any unrelated rebuild from main
would have re-introduced the crash.

The principle (two clauses, both binding):

1. **Prod is deploy-only.** Never commit, edit, or run code changes
   directly on a production host. Every change flows: dev edit → commit →
   push → deploy script reads the artifact built from that commit.
   Emergency incident fixes are NOT an exception — they still flow through
   the repo (commit → CI build → deploy), even when the incident is hot. A
   hand-edit on the box exists outside source control, drifts from main,
   and re-emerges on the next clean rebuild.

2. **"Verified on dev" means the deploy artifact booted.** Building the
   artifact is not verifying it. The exact Docker image (or RPM, or
   `.app`, or whatever ships) MUST be booted on dev or staging before it
   touches prod. Boot means: container starts, `app.listen` succeeds,
   `/health` responds 200, key startup logs match expectations. Running
   `npm run dev` instead does NOT exercise plugin registration the same
   way — `npm install` may resolve different deps than the Docker image,
   bind-mounted source bypasses the COPY layer, dev server may skip the
   plugin chain that boot-loads at production cold-start.

If your deploy pipeline doesn't yet boot the built artifact on a
dev/staging environment, that's a gap to close before the next deploy —
not an excuse to skip the verification. At minimum: build the image
locally + `docker run` it against a local DB + verify the health endpoint
responds 200 before pushing the deploy.

---

## ANTI-PATTERNS — Never Do These  [all]

| Anti-pattern | Why it fails | Correct pattern |
|---|---|---|
| Mutation and its audit/log write as separate statements | Crash between them desyncs them | Rule 3 — one transaction or one CTE |
| `SELECT COUNT(*) ... FOR UPDATE` | Postgres rejects FOR UPDATE with aggregates | Rule 4 — lock rows, count in code |
| `NOT NULL` column with `ON DELETE SET NULL` FK | Contradictory DDL — delete (or DDL) fails | Rule 5 — nullable column, or RESTRICT |
| `INSERT` without checking the table's constraints | Unique/NOT NULL/CHECK violation → 500 | Rule 6 — read schema, handle `23505` |
| Trust FK for identity of a reapable row | Reaper nulls the FK; record is lost | Rule 7 — snapshot identity into metadata |
| Edit an already-applied migration | Desyncs every environment | Rule 8 — write a forward migration |
| `useEffect` poll/subscribe with no cleanup | Timer/listener leaks past unmount | Rule 9 — return a teardown function |
| Build endpoint/type from the plan's wording | Plan drifts from code | Rule 1 — grep the real route + shape |
| Decode a bare `[]` when server wraps it | Empty screens, no compile error | Rule 2 — decode the envelope wrapper |
| Edit named lines, ignore rest of the file | Pre-existing violations survive | Rule 10 — re-grep whole file before commit |
| `tsc` exit 0 reported as "done" | Compile ≠ correct | Rule 0 — pass the full done-gate |
| Hand the user a smoke-test checklist | Transfers verification to the user | Rule 0 — do every check yourself |
| Seed users + flip a flag to test admin path | Skips the empty-state branch entirely | Rule 12 — clear table, hit the real registration path |
| Wire an auth method only on one client | Other clients can't use it; partial ship | Rule 13 — parity across clients, gate on config |
| Write a Codable from reading the route handler alone | Hidden type/format mismatches break decode at runtime | Rule 14 — decode against captured real JSON |
| Hardcode smoke test payload instead of curl-capturing it | Payload diverges from live API; drift goes undetected | Rule 14 — load from a committed curl-captured file |
| Reset retry backoff on first ack | Brief-connect-then-drop loops at the floor | Rule 15 — reset only on sustained success (>5s) |
| Hardcoded ≤500ms retry floor | One client can outpace a struggling service | Rule 15 — floor ≥1s |
| Fix retry-loop math without auditing every caller | Wrong code path drives the storm | Rule 16 — grep all callers, gate inside the function |
| Verify a fix on a stale binary in /Applications | Source is correct, running .app isn't | Rule 16 — rebuild AND reinstall before retest |
| Schema in migration only, not in init script | Fresh init missing tables; tests fail for "infra" | Rule 17 — init script is the source of truth |
| Dismiss "pre-existing test failure" without diagnosing | Hides real defects (e.g. missing tables) | Rule 17 — classify every failure, don't ignore |
| Ship frontend fix without bumping service-worker cache | Old tabs keep serving the buggy bundle forever | Rule 18 — bump CACHE name + activate-handler delete |
| Diagnose a multi-client network bug on one client only | Wrong client gets "fixed" while the real bug sits untouched | Rule 13 + Rule 16 — audit every client implementation |
| `npm install <plugin>` without version pin | npm grabs latest, may target newer framework major → crash at boot | Rule 19 — pin to framework-compatible version, check peerDeps first |
| Leave a verified fix in `git stash` instead of committing | Stash never ships; broken version goes to prod | Rule 20 — fix not done until committed + pushed + merged to deploy branch |
| Edit / commit / hot-patch code directly on a production host | Change exists outside source control; reverts on next rebuild | Rule 21 — every change flows commit → deploy, even emergencies |
| Skip booting the exact deploy artifact on dev/staging before prod | Boot-time crashes only surface in prod | Rule 21 — build the image AND `docker run` it AND verify health before prod |

---

## OPEN SCARS — Watch These; Next Occurrence Locks a Rule  [all]

Things that have happened once but are not yet ruled. When one recurs, promote it to a
numbered rule via the learning loop.

*(none yet — the baseline starts clean here; projects add their own)*

---

## LEARNING LOOP

Every incident updates this file. See `learning-loop.md` for the exact procedure:
append the incident to `AGENT_LEARNINGS.md`, add a numbered `RULE N` here, add an
anti-pattern row, update the done-gate if a new check is introduced, commit together.

---

# ── KHATA PROJECT RULES (appended; project-authoritative) ──
# Stack: Python 3.12 · Flask 3.1 · SQLAlchemy 2.0 · Alembic · pytest · vanilla-JS static pages.
# Run tests with `.venv/bin/python -m pytest -q`. Never switch git branches in a task.
# Never touch the untracked `OD_khata_mockup/` directory.

## K1 — Money/quantity/rate are NEVER float  [server][db][all]
Money = integer minor units (×100). Quantities = integer micro-units (×10⁶). Rates = integer basis
points or `rate_micro` (×10⁶). All arithmetic uses `Decimal` with ROUND_HALF_UP. Parse human input only
through `money.to_minor`/`to_micro`/`pct_to_bps` (they raise `TypeError` on float) — and the API `except`
tuple MUST include `TypeError` so a JSON float yields 400, not 500.

## K2 — Balances/values are DERIVED, never stored  [server][db]
Paid-to-date, outstanding, interest, holding value, net worth, contributor shares, payouts — all computed
from the ledger + terms on each read. The only stored "inputs" are immutable facts (amounts, the manual
quote, the FX rate, the user's base currency). Never persist a derived total.

## K3 — Original currency + amount on a ledger entry are immutable  [server][db]
One honest ledger: movements are `ledger_entries` rows distinguished by `kind`; never a parallel table.

## K4 — Frontend: NEVER innerHTML user/API data  [client]
Build every dynamic row/cell with `createElement` + `textContent`. `innerHTML` is allowed ONLY for a
static empty-string clear. (Stored-XSS was shipped once via innerHTML on a holding name — never again.)
Set error text via `textContent`. Static-page auth guard: `GET /api/auth/me`, 401 → redirect `/`.

## K5 — Pre-flight every API/page wiring against the REAL contract  [client][server]
Before wiring a fetch, confirm the route + method + exact JSON keys from the actual handler in
`src/khata/api/*.py` and the service return dict — not from the plan. Field names drift (e.g.
`net_worth_minor`, `paid_to_date_minor`, `qty_held_micro`). Grep the route; read the `_summary`/`*_state`
return.

## K6 — Owner-scoped + auth-gated  [server]
Every plan-scoped endpoint: 401 if unauthenticated, then `_owned_plan` (owner-only) for mutations or
`_accessible_plan` (owner-or-member) for reads/asset-payments. Commit on success only; rollback on every
error path; set the session only after a fully successful mutate+commit.

## K7 — Migrations: one linear head, only the intended tables  [db]
`render_as_batch=True` (SQLite). After autogenerate, confirm `down_revision` is the prior head and ONLY
the intended table(s) appear — no drift. NOT NULL columns added to existing tables need a `server_default`.
Verify the round-trip (upgrade → downgrade → upgrade) before committing. Commit only `alembic/versions/`.

## K8 — TDD + dual review  [all]
Write the failing test, see it fail, implement, see it pass, run the FULL suite, commit. Each task gets a
spec-compliance review and a code-quality review (combined for trivial tasks; split for money logic).
Every plan ends with a final integration review before the PR.
