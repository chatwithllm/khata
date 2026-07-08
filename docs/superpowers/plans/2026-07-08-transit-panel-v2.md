# Transit Panel v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hop editing, real proof attachments on hops, and a professional restyle of the money-in-transit panel.

**Architecture:** `attachments.hop_id` becomes the 4th attachment parent (same pattern as entry/contact/asset). Hop edit reuses the shipped `PATCH/DELETE /hops/<id>` endpoints via a new slide-over. transfers.js re-renders rows in the ledger idiom using existing CSS classes.

**Tech Stack:** Flask/SQLAlchemy/Alembic, pytest, vanilla JS. Alembic head before this work: `th1hopchain01`.

**Spec:** `docs/specs/2026-07-08-transit-panel-v2-design.md`

## Global Constraints

- Run tests: `.venv/bin/python -m pytest -q` from repo root.
- Attachment parents stay mutually exclusive (exactly one of entry/contact/asset_plan/hop).
- Server permission model: upload/delete hop attachment = hop logger or plan owner; view/list = plan members (mirror entry attachments).

---

### Task 1: `attachments.hop_id` — model, migration, service ✅

**Files:**
- Modify: `src/khata/models/attachment.py`, `src/khata/models/transfer.py`
- Modify: `src/khata/services/attachments.py` (add_attachment hop parent, `list_for_hop`)
- Modify: `src/khata/services/transfers.py` (`plan_transfers` rows: `attachment_count`, `has_proof` includes attachments)
- Create: `alembic/versions/th2hopattach01_hop_attachments.py` (down_revision `th1hopchain01`)
- Test: `tests/test_hop_attachments.py`

**Interfaces:**
- Produces: `add_attachment(..., hop: TransferHop | None = None)`; `list_for_hop(session, hop_id) -> list[Attachment]`; `TransferHop.attachments` relationship; hop rows carry `attachment_count: int`.

Steps (TDD): failing test (attach to hop roundtrip, exactly-one-parent guard rejects hop+entry, plan_transfers has_proof/attachment_count) → run fail → implement (column + relationship + service branch + migration mirroring `dd7attach01` batch add-column style) → run pass → migration up/down check on scratch DB copy → full suite → commit `feat(chains): hop proof attachments — model, migration, service`.

### Task 2: hop attachments API

**Files:**
- Modify: `src/khata/api/attachments.py` — add `GET/POST /plans/<pid>/hops/<hid>/attachments` (mirror entry routes; `_can_modify` analog: hop logger or plan owner), extend download/delete parent dispatch with `att.hop_id` branch (view = plan member via `sharing.accessible`; delete = logger/owner).
- Test: `tests/test_hop_attachments_api.py`

Steps: failing API test (upload as logger 201, list as member 200, outsider 403, delete by owner 200, bad hop 404 — reuse register/login helpers from `tests/test_transfers_api.py`) → implement → full suite → commit `feat(chains): hop attachments API`.

### Task 3: UI — restyle panel + edit slide-over + proof

**Files:**
- Modify: `src/khata/static/assets/transfers.js` (restyled rows, pencil action, `proof` chip)
- Modify: `src/khata/static/asset-detail.html` (hop-edit slide-over markup + wiring; mounts `attach.js` via `mountAttachments({planId, hopId?…})` — check attach.js signature first; if entry-specific, add a hop mode or upload inline via fetch FormData)
- Test: headless verify (ephemeral instance): styled rows render, PATCH via slide-over changes amount, upload proof → chip appears, delete hop from slide-over.

Steps: read `attach.js` + ledger row markup/classes in asset-detail → implement restyle (panel header/eyebrow/KPI, ruled rows, chips, mono amounts, small-caps chain label, actions as links incl. Edit) → edit slide-over (amount/date/method/note + Delete + attachments mount) → headless verify → commit `feat(chains): transit panel v2 — edit slide-over, proof attachments, restyle`.

### Task 4: Docs

Update `docs/specs/khata-AS-BUILT.md` (attachments table gains hop parent; hops API section gains attachment routes; changelog entry). Full suite. Commit `docs: as-built — transit panel v2`.
