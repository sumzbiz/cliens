# Docs

| Document | What it covers |
| --- | --- |
| [VERIFICATION.md](VERIFICATION.md) | What was tested before the hackathon submission, what passed, and what could not be verified |
| [../deploy/README.md](../deploy/README.md) | The AWS deployment: what runs where, secrets, cost, and what the setup deliberately does not do |
| [../CLAUDE.md](../CLAUDE.md) | Engineering conventions: layering, units, errors, testing |
| [hackathon/](hackathon/) | The Tech For Good hackathon's proposal template and milestone checklist, kept for the record |

## Diagrams

| Image | Shows |
| --- | --- |
| [architecture-system.jpeg](images/architecture-system.jpeg) | The system as built: React client, Caddy, FastAPI, PostGIS, the offline GRIB → model pipeline, and the third-party services it calls |
| [architecture-aws.jpeg](images/architecture-aws.jpeg) | The AWS deployment in ap-south-1 |
| [architecture-target.png](images/architecture-target.png) | The **target** architecture. It includes integrations that are **not implemented yet** — Google Earth Engine (CMIP6), Gemini report generation and the IMD API — so it must not be read as a description of the current system |
