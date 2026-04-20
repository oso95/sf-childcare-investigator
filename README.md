# sf-childcare-investigator

AI investigator that flags physically-impossible licensed-childcare setups in **San Francisco**. Inspired by [Surelock-Homes](https://github.com/oso95/Surelock-Homes) (IL/MN), rebuilt for CA and powered by the [Hermai](https://hermai.ai) registry instead of per-source scrapers.

## The check

California Title 22 requires **35 sqft of indoor activity space per child**. We pull the CCLD-licensed capacity for every SF facility, then cross-reference the SF Assessor parcel record (building square footage) and a handful of supporting signals (permits, business registration, housing inspections, 311 complaints, evictions). A licensed day care claiming 85 children in a 900 sqft parcel is the fraud pattern.

## Data sources

| Source | How we access it |
|---|---|
| CCLD provider roster (CDSS_CCL_Facilities) | ArcGIS REST, direct |
| SF Assessor parcel roll (`wv5m-vpq2`) | Hermai → `data.sfgov.org` `assessor_parcel_lookup` |
| DBI building permits (`i98e-djp9`) | Hermai → `dbi_building_permits_lookup` |
| Registered business locations (`g8m3-pdis`) | Hermai → `business_registration_lookup` |
| Housing inspections (`nbtm-fbw5`) | Hermai → `dbi_housing_inspections_lookup` |
| 311 complaints (`vw6y-z8j6`) | Hermai → `service_311_complaints_lookup` |
| Eviction notices (`5cei-gny5`) | Hermai → `evictions_lookup` |

SF address → parcel uses the canonical **permits → block/lot → parcel** join (documented in the Hermai schema).

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in OPENROUTER_API_KEY and HERMAI_API_KEY
```

## Run

Investigate one facility by name or address:

```bash
python run.py "GROWING TREE SCHOOL LLC"
python run.py --address "1984 GREAT HIGHWAY"
python run.py --capacity-min 50          # sweep all SF facilities ≥ 50 kids
```

Serve the web UI:

```bash
uvicorn backend_api:app --reload
# open http://127.0.0.1:8000
```

## Layout

```
sf_investigator/
  hermai.py      HTTP client for hermai.ai
  tools.py       one function per data source
  tool_defs.py   OpenAI/OpenRouter tool JSON schemas
  agent.py       tool-calling loop
  prompt.py      system prompt (CA Title 22 rules, playbook)
backend_api.py   FastAPI /api/investigate
frontend/        single-page UI
run.py           CLI entry
```

## Status

v0 — ships the parcel-size impossibility check. License violation history is not yet covered (would need a CCLD public-search schema in Hermai).
