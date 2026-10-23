# Verification report

Phase 9 deliverable. Records what was tested, what passed, and — as importantly —
what could not be verified and why.

**Date:** 8 August 2026
**Commit base:** `4632a5d`
**Environment:** Windows 11, Python 3.12.10, Node 24.15.0, PostgreSQL 16 + PostGIS 3.4.3 (Docker)

---

## 1. Automated results

```
backend    274 passed
frontend     1 passed
mypy --strict   Success: no issues found in 56 source files
ruff            All checks passed
black           formatted
vite build      built in 1.08s
```

### Test coverage by area

| Area | File | Tests | What it pins down |
| --- | --- | --- | --- |
| GRIB gap-filling | `tests/test_grib_pipeline.py` | 20 | Interpolation only from real neighbours; every fill flagged; ungroundable gaps **fail** rather than being invented |
| CSV schema | same | (included) | Nulls, duplicate district-days, uneven coverage all rejected |
| Bundled profiles | same | (included) | Priority districts present, Chennai absent, values physically plausible |
| Rules engine | `tests/services/test_rules_engine.py` | 49 | IS 456 Table 5 transcription row by row; exposure escalation; signed compliance margins |
| Scoring + report API | `tests/routes/test_scoring.py` | 21 | Both modes, determinism, validation, PDF is a real file |
| Materials catalogue | `tests/routes/test_materials.py` | 30 | Seed integrity, sourced ratings, idempotent seeding |
| Core calculations | `tests/core/` | ~100 | Unit conversions, constants consistency, rate limiting, config |
| HTTP policy | `tests/external/test_http.py` | 14 | Retries only on transient failures, no payload leakage |

**No test makes a real network call.** An autouse fixture guards both
`socket.create_connection` *and* `socket.socket.connect` — the second was added
after a test was caught reaching Google.

---

## 2. Manual walkthrough

Backend on `127.0.0.1:8010`, frontend on `localhost:5173`, both freshly restarted.

| # | Step | Expected | Observed | Result |
| --- | --- | --- | --- | --- |
| 1 | `GET /api/health/ready` | All dependencies ready | database, postgis 3.4.3, material_catalogue 14, ml_models quality_score | **Pass** |
| 2 | `GET /api/score/districts` | 37 districts, Chennai absent | 37 returned; Chennai absent; period 2016-01-01→2026-08-03 | **Pass** |
| 3 | Frontend loads | Form renders, districts populated | HTTP 200, districts populated via Vite proxy | **Pass** |
| 4 | Evaluate mode, Coimbatore, weak spec | Low score, both sides returned | proposed 35.7 (poor) → recommended 77.6 (good), +41.9 | **Pass** |
| 5 | Evaluate mode, Salem | Comparable behaviour | 33.7 → 78.1, +44.4 | **Pass** |
| 6 | Evaluate mode, Erode | Comparable behaviour | 34.9 → 78.6, +43.7 | **Pass** |
| 7 | Recommend mode, Salem (no materials) | Baseline vs advice | 41.1 → 78.1, +37.0 | **Pass** |
| 8 | Exposure reasoning | Explains itself | "Severe" with humidity 81% cited as the escalation | **Pass** |
| 9 | Compliance table | Shows shortfalls | 4 unmet: grade, cement, w/c, walling | **Pass** |
| 10 | Unknown district | Typed error listing alternatives | 503 `CLIMATE_PROFILE_UNAVAILABLE`, lists valid districts | **Pass** |
| 11 | Malformed grade (`"DROP TABLE"`) | Rejected at the boundary | 422 `VALIDATION_ERROR` | **Pass** |
| 12 | PDF download via proxy | Real attachment | `application/pdf`, `attachment; filename="…coimbatore.pdf"`, 3,568 bytes, `%PDF-1.4`, 1 page | **Pass** |
| 13 | PDF in recommend-only mode | Renders without a user spec | 200, valid PDF | **Pass** |
| 14 | Determinism | Identical request, identical score | Byte-identical scores across repeat calls | **Pass** |
| 15 | Pipeline re-run | Reproducible | 112,172 messages, 143,116 rows, 0 gaps, ~3 min | **Pass** |

---

## 3. Not verified, and why

Listed rather than glossed over.

| Item | Why not verified |
| --- | --- |
| **PDF visual layout** | Structure verified programmatically (magic bytes, page count, embedded title). Nobody opened it in a PDF reader, so column alignment and page breaks under long content are unconfirmed. |
| **Frontend interaction** | Only a mount smoke test exists. Form submission, mode toggling and the download click were exercised through the API, not through the rendered DOM. |
| **Responsive + keyboard behaviour** | CSS is written for it (focus rings, `prefers-reduced-motion`, responsive grid) but was not tested at breakpoints or with a screen reader. |
| **Districts beyond the priority three** | 34 other districts return profiles, but only Coimbatore, Salem and Erode were walked end to end. |
| **Coastal districts** | Nagapattinam and Cuddalore should classify Very Severe. The logic is unit-tested with synthetic climate, but no coastal district was scored through the API. |
| **Model retraining reproducibility** | Trained once. The seed is fixed and the pipeline is deterministic, but a second run was not compared byte-for-byte. |

---

## 4. Defects found and fixed during this work

1. **Precipitation mislabelled** — GRIB step `5-6` is a *one-hour* accumulation, not a daily total. Would have under-reported rainfall ~20×. Columns renamed; the rules engine now uses a wetness index because an annual depth cannot honestly be derived from this file.
2. **Walling materials unassessed** — `concrete_solid_block` and `engineering_brick` were skipped because the check required both reference tables, and Table 4 lists only four materials. 40% of the catalogue was silently unevaluated.
3. **Logging crashed outside HTTP requests** — `structlog.stdlib.add_logger_name` reads `logger.name`, absent on `PrintLogger`.
4. **A test called Google for real** — the socket guard missed `socket.socket.connect`, which `googleapiclient` uses.
5. **Tests read the ambient `.env`** — adding real credentials broke six unrelated tests.
6. **`create_app(settings)` was not authoritative** — dependencies resolved their own cached settings, so a test could believe it was unconfigured while a service used live credentials.
7. **Pipeline runtime 60 min → 3 min** — cfgrib materialises a hypercube per message; replaced with a single sequential ecCodes pass.
8. **`pandas.interpolate` on object dtype** — a `None` among floats made gap-filling a silent no-op, and would raise in a future pandas.

---

## 5. Known limitations of the product itself

- **The 0–100 score is our own scale**, defined by weights in `core/constants.py`. It is not a published metric.
- **The ML model learned a rule set, not building outcomes.** No dataset of real building survival was used, and none is implied. R² 0.886 measures how well it interpolates the rules engine.
- **Exposure thresholds are judgements.** IS 456 Table 3 is prose; turning "exposed to severe rain" into a number is ours.
- **Climate is historical, not projected.** ERA5 covers 2016–2026. The product describes conditions as measured, and makes no forward claim.
- **Chennai and anywhere east of 80°E cannot be scored** — outside the bundled grid.
- **Rainfall is a relative index**, not millimetres per year.

---

## 6. Reproducing this

```bash
npm run db:up
npm run db:migrate && npm run db:seed
node scripts/py.mjs ../ml/grib_to_csv.py            # ~3 min
node scripts/py.mjs ../ml/build_district_profiles.py
node scripts/py.mjs ../ml/train_quality_score.py
npm run test:all
npm run dev:backend    # terminal 1
npm run dev:frontend   # terminal 2 → http://localhost:5173
```
