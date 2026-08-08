# Porsche 981 Cayman Market Tracker

Personal market-intelligence tool that discovers, normalizes, deduplicates, and
tracks **2014–2016 Cayman S** and **2015–2016 Cayman GTS** listings nationwide,
preserving full price/mileage history so good buying opportunities become visible
over time. Active *asking* data and verified *sold* data are kept strictly
separate. Frontend eventually at `cars.arthurnemeth.com`.

## Architecture

```
 collectors/*  ──►  RawIngestion (verbatim JSONB, idempotent)
   (per source)          │
                         ▼  versioned parser (re-runnable over old payloads)
                  NormalizedListing  ──►  dedup → Vehicle (VIN-keyed)
                                              │
                                              ▼
                        Listing ──► ListingObservation (append-only price/mileage history)
                                    Transaction (verified sold — never blended with asking)
                                              │
                                              ▼
                            analytics / scoring  ──►  FastAPI  ──►  React dashboard
```

**Data model** (`db/tables.py`): `Vehicle` (physical car, VIN-keyed) · `Listing`
(one car on one source) · `ListingObservation` (append-only snapshot) · `Seller` ·
`VehicleOption` (with confidence) · `Transaction` (verified sales) · `RawIngestion`
(retained payloads) · `Source` (with reliability weight).

**Design commitments:** idempotent ingestion · append-only history · raw retention
so parsers can be re-run · per-field confidence · VIN-first dedup with a
conservative fuzzy fallback · listing lineage across sources/time.

## Stack & hosting (all free tier)

| Layer      | Choice                                                          |
|------------|----------------------------------------------------------------|
| Collectors/ETL | Python (`httpx`, `pydantic`, `SQLAlchemy`)                 |
| Scheduler  | GitHub Actions (daily cron) — see `.github/workflows/collect.yml` |
| Database   | Neon serverless Postgres                                       |
| API        | FastAPI (Render/Fly free tier)                                |
| Frontend   | React + TS on Cloudflare Pages → `cars.arthurnemeth.com`, gated by Cloudflare Access |

## Sources (free / official only)

| Source | Method | Status |
|--------|--------|--------|
| eBay Motors | official Browse API (client-credentials) | ✅ implemented (awaiting API key) |
| NHTSA vPIC | free VIN decode, no key | ✅ wired (`enrich-vins` pass) |
| Dealer inventory | per-dealer adapters via robots-gated `HtmlCollector` | 🧱 framework ready, adapters next |
| Porsche Finder | internal JSON (CPO/approved-used) | ⛔ anti-bot (HTTP 429) + thin for 981; revisit locally |
| Google Programmable Search | dealer *discovery* (100/day free) | ⏳ next |
| BaT / Cars & Bids / PCARMARKET / classic.com (sold data) | — | 🅿️ deferred |

We respect source access constraints — no CAPTCHA/anti-bot bypass. Where direct
collection is inappropriate we use official APIs, feeds, or discovery instead.

## Local development

```bash
cd backend
python -m venv .venv && ./.venv/Scripts/activate      # Windows
pip install -e ".[dev]"
cp .env.example .env                                   # fill in DATABASE_URL + eBay creds

# spin up Postgres (or point DATABASE_URL at Neon)
docker run -d --name porsche-pg -e POSTGRES_USER=porsche \
  -e POSTGRES_PASSWORD=porsche -e POSTGRES_DB=porsche -p 5432:5432 postgres:16

porsche db-init            # apply alembic migrations to head (works on sqlite too)
porsche seed-demo          # optional: synthetic data to explore the UI without keys
porsche collect ebay       # run the eBay collector + ingest (needs eBay key)
porsche enrich-vins        # decode VINs via NHTSA vPIC, back-fill unknowns
uvicorn porsche_tracker.api.main:app --reload   # http://localhost:8000/api/stats

pytest                     # offline unit tests (no network/DB needed)

# zero-infra demo (no Postgres): use SQLite
#   set DATABASE_URL=sqlite:///demo.db  (PowerShell: $env:DATABASE_URL="sqlite:///demo.db")
```

### eBay API key (free)

Create a developer account at <https://developer.ebay.com>, make a **Production**
keyset, and put its Client ID / Secret in `.env`. The client-credentials grant
needs no user login.

## Roadmap

1. **Foundation** ✅ — data model, ingest/dedup, eBay collector, read API, scheduler.
2. **Migrations** ✅ — Alembic (`db-init` runs `upgrade head`); portable Postgres/SQLite.
3. **VIN enrichment** ✅ — vPIC decode pass; robots-gated `HtmlCollector` base for dealers.
4. **More sources** — dealer adapters (robots-gated), Google discovery; eBay live on key approval.
5. **Dashboard** ✅ (POC) — React in `web/`; deploy to Cloudflare Pages next.
6. **Analytics** — S-vs-GTS & PDK-vs-manual premiums, price-vs-mileage, days-on-market.
7. **Scoring** — Market Deal Score (vs market) + Personal Buy Score (my preferences).
8. **Transactions** — auction sold-data adapters (deferred).
