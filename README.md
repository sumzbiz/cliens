<div align="center">

# 🏗️ CLIENS

**Score a building's material specification against measured climate,
check it against IS 456:2000, and estimate how long it will last.**

**KSRCE AI Innovation Hub & QUANTIX Association present**
### 🚀 QUANTIX2K26 (24 hours // hackathon)

Developed by **Suman N** (Solo Participation)

🌐 **Live:** http://13.203.248.62

</div>

---

## Architecture

### Overall Architecture

![CLIENS — Overall Architecture](https://github.com/Build-with-AI-Code-for-Communities/cities-team-263-zenovators/blob/d9568be7a601ff8ac2262ac369a9db5dbadfd279/ChatGPT%20Image%20Aug%209%2C%202026%2C%2002_52_33%20PM.png)

### Cloud Architecture

![CLIENS — Cloud Architecture](https://github.com/Build-with-AI-Code-for-Communities/cities-team-263-zenovators/blob/bcf6c3bd9f5c70bde76b71b7c9d23185c7c81187/bf6c3464-b8a6-4093-9861-884f3f90e3f0.jpeg)


---

## Participant

**Participant:** Suman N (Solo Participation, no other)
**Hackathon:** KSRCE AI Innovation Hub & QUANTIX Association present QUANTIX2K26 (24 hours // hackathon)

| Name | Role |
| --- | --- |
| **Suman N** | Full-Stack & ML Engineering / Cloud Architecture |

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [What CLIENS Does](#2-what-cliens-does)
3. [Tech Stack](#3-tech-stack)
4. [The Data](#4-the-data)
5. [The Scoring Engine](#5-the-scoring-engine)
6. [Service Life Estimate](#6-service-life-estimate)
7. [Tamil Voice Narration](#7-tamil-voice-narration)
8. [Running Locally](#8-running-locally)
9. [Deployment](#9-deployment)
10. [Testing](#10-testing)
11. [Honesty & Known Limitations](#11-honesty--known-limitations)
12. [Proof of Work](#12-proof-of-work)

---

## 1. The Problem

Buildings in India are routinely specified with a generic concrete mix, regardless
of where they are built. A mix that lasts fifty years inland can corrode in fifteen
near the coast, because humidity, salt and wet–dry cycling drive reinforcement
corrosion at completely different rates.

**IS 456:2000** already accounts for this — it sorts structures into *exposure
classes* and sets a different minimum grade, cement content and water/cement ratio
for each. But applying it correctly means knowing your site's actual climate, and
most small builders don't have that.

CLIENS closes that gap: **draw your plot, and it tells you what the code requires
there and what your specification is actually worth.**

---

## 2. What CLIENS Does

A five-step flow:

| Step | What happens |
| --- | --- |
| **1 · Location** | Plot your site on a 3D satellite globe or a flat satellite map. Click each corner to outline the plot; the area is computed by PostGIS and saved. |
| **2 · Exposure** | Say how the concrete sits — enclosed, sheltered, exposed, buried or tidal. |
| **3 · Approach** | Score *your* specification, or ask for a recommended one. |
| **4 · Materials** | Concrete grade, cement content and type, water/cement ratio, walling material. |
| **5 · Score** | A 0–100 score, every compliance check, an estimated service life, and the specification we'd recommend instead. |

Also included:

- **Tamil voice narration** of every question and option, and of the final result
- **Downloadable PDF report** to hand to a contractor, with the code clause behind each item
- **Address / PIN-code search** to find your site quickly

---

## 3. Tech Stack

### Frontend
`React 19` · `TypeScript (strict)` · `Vite` · `Tailwind CSS v4` · `React Router` ·
`Motion` · `Three.js / react-globe.gl` (3D globe) · `Leaflet` (flat satellite map)

### Backend
`Python 3.12` · `FastAPI` · `Pydantic v2` · `SQLAlchemy 2.0 (async)` · `Alembic` ·
`Shapely` · `Pillow` · `structlog` · `httpx`

### Data & ML
`PostgreSQL 16` + `PostGIS 3.4` · `scikit-learn 1.6` · `pandas` · `NumPy` ·
`ecCodes` (GRIB decoding) · `ReportLab` (PDF)

### Infrastructure
`Docker` + `Docker Compose` · `Caddy` (TLS + reverse proxy) · `Terraform` ·
`AWS EC2 / S3 / SSM / IAM`

### Third-party services
`Esri ArcGIS` (satellite imagery) · `OpenStreetMap Nominatim` (geocoding) ·
`Sarvam AI` (Tamil text-to-speech)

---

## 4. The Data

Every climate figure in CLIENS traces back to a single **ECMWF ERA5 reanalysis
GRIB file** — real measured atmospheric data, not a forecast and not a model output.

| | |
| --- | --- |
| **Source** | ECMWF ERA5 reanalysis (`data.grib`, 129 MB) |
| **Period** | 2016-01-01 → 2026-08-03 |
| **Grid** | 0.25° ≈ **27 km cells** |
| **Districts** | **37** with a measured profile |

### Offline pipeline

```
data.grib (129 MB)
   └─> grib_to_csv.py            decode 112,172 GRIB messages via ecCodes
        └─> climate CSV           143,116 rows
             └─> build_district_profiles.py
                  └─> district_climate_profiles.json   ← 37 districts, ships with the app
                       └─> train_quality_score.py
                            └─> quality_score_*.pkl    ← the model
```

The GRIB file itself is **not deployed** — only the small derived JSON and the
model artifact ship with the application.

Per district we derive: mean relative humidity, wet-hours fraction, wet/dry cycles
per year, mean and peak temperature, peak wind gust, soil moisture, and distance
to coast (computed from the land/sea mask in the sea-surface-temperature field).

---

## 5. The Scoring Engine

A **hybrid**: a deterministic rules engine plus a model that smooths it.

**1. Rules engine — `services/rules_engine.py`**
Classifies the IS 456 exposure class from the district's measured humidity, wet
hours and distance to coast, combined with how the element sits. Then checks the
proposed mix against **IS 456 Table 5** minimums: concrete grade, cement content,
maximum water/cement ratio, and walling suitability. Every finding cites its
standard.

**2. ML model — `GradientBoostingRegressor`**

| Metric | Value |
| --- | --- |
| R² | **0.886** |
| MAE | **4.34** (on a 0–100 score) |
| Training samples | 8,702 |
| Test samples | 2,176 |
| Seed | 20231204 (fixed — scoring is deterministic) |

Top feature importances: `grade_mpa` 0.585 · `water_cement_ratio` 0.252 ·
`cement_content_kg_m3` 0.094 · `walling_absorption_percent` 0.042

> **What this model is.** It is trained on **scenarios labelled by the rules
> engine**, not on observed building outcomes. No dataset exists that records
> "this building was specified like that and lasted N years." The model is a
> smooth interpolator over a deterministic rule set — it is **not evidence about
> real building survival**, and we don't present it as such.

---

## 6. Service Life Estimate

The results page shows an estimated service life for both the proposed and the
recommended specification.

**How it's derived** — anchored on the **50-year design life** the IS 456
durability provisions are written to deliver. A mix sitting exactly on its
exposure class's limits returns exactly 50 years. From there:

- **Water/cement ratio** dominates. Reinforcement corrosion is diffusion-
  controlled and the diffusion coefficient rises roughly exponentially with w/c,
  so life scales as `exp(k × (required − provided))`. The exponent used is at the
  conservative end of the published range *(fib Bulletin 34; Papadakis, Vayenas &
  Fardis, ACI Materials Journal 88(2), 1991)*.
- **Falling short** of the minimum grade or cement content applies a further
  reduction, because the 50-year target's assumptions no longer hold.

Reported as a **range**, never a single year — two structures built to identical
specifications diverge by decades on workmanship and cover accuracy alone.

> This answers *"how does this specification compare to one the code says lasts
> 50 years"* — **not** *"when will this building fall down."*

---

## 7. Tamil Voice Narration

Every question and **every option** is read aloud in Tamil, so a user can listen
instead of read and then choose for themselves. The voice explains; it never
selects.

- **Sarvam AI**, model `bulbul:v3`, speaker `kavitha` (verified against the live
  API — the model's speaker list differs from the general docs list)
- **Dual API keys with automatic failover.** On the first response indicating a
  spent key (HTTP 429/402/403) it switches immediately and stays switched, so the
  user hears no gap. A 400 is *not* retried on the second key — that's our bug,
  and retrying would burn a second quota for the same error.
- Long narrations are split on sentence boundaries (the API caps at 2,500
  characters) and joined server-side into one audio file, so playback is continuous.
- **Fully optional.** With no keys configured the Listen buttons simply don't
  appear and every question stays usable as text.

---

## 8. Running Locally

**Prerequisites:** Node 20+, Python 3.12, Docker

```bash
# 1. Database
npm run db:up

# 2. Configuration
cp .env.example .env        # Sarvam keys optional

# 3. Backend
npm run db:migrate
npm run db:seed
npm run dev:backend         # http://localhost:8010

# 4. Frontend (new terminal)
npm run dev:frontend        # http://localhost:5173
```

---

## 9. Deployment

Fully automated with **Terraform** — nothing is created by hand in the AWS console,
and there is no SSH key to manage.

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars   # fill in secrets
terraform -chdir=infra init
terraform -chdir=infra apply      # creates 19 AWS resources
bash deploy/deploy.sh             # builds, uploads, starts — prints the URL
```

**What runs:** a single **EC2 t3.small** in `ap-south-1` running Docker Compose —
Caddy (TLS + static SPA + reverse proxy), the FastAPI backend, and
PostgreSQL/PostGIS on a private bridge network with no published port.

**Secrets** live in **SSM Parameter Store** as SecureString and are pulled at boot
by the instance's IAM role — never baked into an image or passed through user data.
**Deploy artifacts** go via a private **S3** bucket; the instance pulls them using
its own role, so no credentials travel with them. Shell access is **SSM Session
Manager** — no open port 22.

**Cost:** ≈ **$18–22/month**

Full detail, including what this setup deliberately does *not* do, is in
[`deploy/README.md`](deploy/README.md).

---

## 10. Testing

```bash
npm run test:all      # lint + typecheck + backend + frontend
```

| | |
| --- | --- |
| Backend tests | **350** |
| Frontend tests | **4** |
| Type checking | `mypy --strict` clean · `tsc --strict` clean |
| Linting | `ruff` + `black` clean · `eslint` clean |

Tests never make real network calls — every external client is mocked with
`respx`. Integration tests run against a real PostGIS database, so a broken
extension or schema drift fails the suite rather than only failing in production.

---

## 11. Honesty & Known Limitations

We would rather state these plainly than have them found.

**The climate grid is 27 km.** A boundary drawn around one building and one drawn
around the whole block resolve to the same reading. Deep satellite zoom helps you
*find* your plot; it does not make the score more precise.

**Interpolated readings are labelled as such.** If your outline contains no
measured grid cell, the climate is inverse-distance weighted from up to four real
neighbours within 85 km, and the result says so and names the cells. **Beyond that
radius the request is refused** — there is no neighbouring evidence, so any number
would be invention rather than interpolation.

**The score is code compliance, not a failure prediction.** It measures how a
specification compares to IS 456 for the measured climate. It is not a structural
analysis and does not consider foundations, seismic design, or workmanship.

**The ML model learned a rule set, not reality.** See §5.

**Coverage is Tamil Nadu only** — 37 districts, bounded by the source GRIB extent
(8.25–13.0°N, 76.75–80.0°E). Anywhere outside is refused, not guessed.

**Deployment is single-instance.** No horizontal scaling (caches are per-process),
no automated database backups, and the instance is a single point of failure.
Acceptable for a demo; documented rather than hidden.

**CLIENS is not a substitute for a licensed engineer.** It is a decision-support tool.

---

## 12. Proof of Work

This repository is the documentation and the proof of work for our submission.

| Evidence | Where |
| --- | --- |
| Live deployment | http://13.203.248.62 |
| Infrastructure as code | [`infra/`](infra/) — 19 AWS resources, zero console clicks |
| Deployment pipeline | [`deploy/`](deploy/) |
| Offline data pipeline | [`ml/`](ml/) — GRIB → CSV → district profiles → model |
| Backend | [`backend/app/`](backend/app/) — strict `routes → services → repositories → core` layering |
| Frontend | [`frontend/src/`](frontend/src/) |
| Test suite | 350 backend + 4 frontend, all passing |
| Engineering conventions | [`CLAUDE.md`](CLAUDE.md) |
| Commit history | Every architectural decision and bug fix is recorded in the log |

**Verified live in production:** PostGIS 3.4.3 · 14 materials seeded · model loaded ·
scoring · polygon persistence · map tiles · PDF report generation.

---

<div align="center">

**CLIENS** · **Suman N** (Solo Participation) · **QUANTIX2K26** (KSRCE AI Innovation Hub & QUANTIX Association)

</div>
