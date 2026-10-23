# CLAUDE.md — Climate Lien Score conventions

Conventions for this repository. These are enforced by tooling (ruff, mypy, ESLint,
pre-commit) wherever enforcement is possible; the rest are review criteria.

## Architectural decisions already made

Recorded here so they are not re-litigated. Anything **not** listed here that changes
the architecture must be raised before implementing.

| Decision | Choice | Rationale |
| --- | --- | --- |
| Python runtime | 3.12 (`requires-python = ">=3.11"`) | Brief specifies 3.11+; 3.12 is current stable. |
| Database | PostgreSQL 16 + PostGIS 3.4 via Docker Compose | No local Postgres; container is reproducible and matches CI. |
| Map library | Leaflet + Leaflet.draw + OpenStreetMap tiles | Needs no access token, so the app runs on a clean clone with zero third-party signup. Mapbox GL Draw was the alternative but requires a token. |
| Auth | None; per-IP rate limiting + locked CORS | v1 is anonymous. Auth is a tracked Known Limitation in the README. |
| Frontend types | Generated from the FastAPI OpenAPI spec via `openapi-typescript` | The brief prefers generation over hand-mirroring. Never hand-edit generated files. |
| Task runner | `npm run <task>` from the repo root | `make` is not available on Windows; root `package.json` proxies to both workspaces. |

## Layering — the rule that matters most

Dependencies flow in exactly one direction. A module may import from layers **below**
it and never from layers above or sideways at the same level.

```
routes  ->  services  ->  repositories  ->  database
              |                 |
              +--> external ----+
              +--> ml
              +--> core (importable by everything)
```

- `routes/` parse the request, call exactly one service, return the response. No
  branching on business rules, no arithmetic, no DB access.
- `services/` hold all business logic. They call repositories, external clients and ML
  wrappers. They never touch a `Session` or write SQL.
- `repositories/` are the only place a `Session`/SQL/PostGIS function appears.
- `external/` are thin, typed clients (Earth Engine, IMD, Gemini) with timeouts,
  retries and typed errors. Business code never imports `httpx` directly.
- `ml/` loads model artifacts once at startup (singleton) and wraps inference.
  Training code lives in `/ml` at the repo root and is never imported at request time.
- `core/` is leaf-level: config, logging, exceptions, and every shared calculation.
  It imports nothing from the layers above.

SQLAlchemy ORM models live in `repositories/models.py` rather than a top-level
`models/` package. The repository layer is the only layer permitted to touch the
database, so the table definitions belong to it; putting them anywhere else would
invite services to import them and query directly.

## DRY

- A calculation used in more than one place lives in exactly **one** function in
  `backend/app/core/` and is imported. Area conversion, resistance-weighted scoring
  and threshold comparison are already there — use them, do not re-derive them.
- No copy-pasted fetch boilerplate in React components. Every request goes through
  `frontend/src/lib/api-client.ts`.
- Repeated Tailwind class strings become a component in `components/ui/`.

## No magic numbers

Every threshold, weight, hyperparameter and physical constant lives in a named
constant in `backend/app/core/constants.py` (or a documented config file) with a
comment giving its source or reasoning. A bare numeric literal in a service or a
model is a review failure. Exceptions: `0`, `1`, and array indices.

## Errors

- Every external call has explicit error handling and raises a typed exception from
  `backend/app/core/exceptions.py`. Never `except: pass`, never a bare `except:`.
- Exceptions carry a machine-readable `code` and a human-readable message; the global
  handler maps them to a consistent JSON error envelope. No unhandled 500s.
- Missing credentials or unavailable upstreams produce an explicit typed error. They
  never produce fabricated or placeholder data — a wrong number is worse than an
  error in a permit-approval context.

## Types

- Python: full annotations on every function, `mypy --strict` clean. No bare `Any`.
- TypeScript: `strict: true`. No `any`. No `@ts-ignore`/`@ts-expect-error` without a
  comment on the line above explaining why it is unavoidable.

## Validation

Every request body, query and path parameter is a Pydantic v2 model using constrained
types (`Annotated[float, Field(ge=..., le=...)]`) and field validators. Validation
happens at the boundary, before business logic. Polygon geometry and material IDs are
untrusted input and are validated structurally and semantically.

## Determinism

`/score` is a pure function of its inputs. External responses (Earth Engine, IMD) are
cached with the request's spatial + temporal key so a re-score cannot drift because an
upstream changed. Anything non-deterministic (model randomness) is seeded from
`core/constants.py`.

## Observability

Structured JSON logging via `core/logging.py`. Never `print`. Every request gets a
correlation ID (`X-Request-ID`, generated if absent) that is bound to a context var and
appears on every log line for that request, including inside services and external
clients. Log at each service boundary: the call, the external calls made, the result.

## Testing

- `backend/app/tests/` mirrors `backend/app/` 1:1.
- Tests never make real network calls. Every external client is mocked.
- Score engine math is tested at its edges: minimum risk, maximum risk, missing data,
  and both boundary years (2025, 2055).
- `npm run test:all` from the repo root runs everything.

## Units

Every unit conversion is annotated inline at the point of conversion, naming the source
unit and the target unit. Canonical internal units:

| Quantity | Internal unit |
| --- | --- |
| Area | square feet (`sq_ft`) — the user-facing input unit |
| Wind speed | metres per second (m/s) |
| Rainfall | millimetres (mm) |
| Temperature | degrees Celsius (°C) |
| Coordinates | WGS84 / EPSG:4326, `(longitude, latitude)` order |

GeoJSON is always `(lon, lat)`. Leaflet is always `(lat, lon)`. Convert at the
boundary in `frontend/src/lib/`, never ad hoc in a component.

## Commits

No commented-out code, no dead code, no unresolved `TODO` in committed state. Work
that is deliberately deferred goes in the README's "Known limitations" section instead.
