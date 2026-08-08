"""Read-only FastAPI for the dashboard.

Thin HTTP layer over the same SQLAlchemy models the ETL uses — one source of
truth. Deeper metrics belong in ``analytics/``; this exposes the POC dashboard
essentials: summary stats + the active-listings table + per-vehicle price history.
"""

from __future__ import annotations

from statistics import median

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from porsche_tracker.db.base import session_scope
from porsche_tracker.db.tables import Listing, ListingObservation, Source, Vehicle

app = FastAPI(title="Porsche 981 Tracker", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tightened to cars.arthurnemeth.com once deployed behind Access
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/stats")
def stats() -> dict:
    """Dashboard summary: unique active vehicles, active listings, VIN rate, and
    median asking price by trim."""
    with session_scope() as s:
        active_listings = s.scalars(
            select(Listing).where(Listing.status == "active")
        ).all()
        vehicle_ids = {l.vehicle_id for l in active_listings}
        vins = s.scalar(
            select(func.count()).select_from(Vehicle).where(Vehicle.vin.is_not(None))
        )
        total_vehicles = s.scalar(select(func.count()).select_from(Vehicle)) or 0

        # latest price per active listing, grouped by trim
        by_trim: dict[str, list[float]] = {}
        for listing in active_listings:
            obs = s.scalar(
                select(ListingObservation)
                .where(ListingObservation.listing_id == listing.id)
                .order_by(ListingObservation.observed_at.desc())
            )
            if obs and obs.price is not None:
                by_trim.setdefault(listing.vehicle.trim, []).append(float(obs.price))

        return {
            "active_vehicles": len(vehicle_ids),
            "active_listings": len(active_listings),
            "vin_identification_rate": round((vins or 0) / total_vehicles, 3)
            if total_vehicles
            else 0.0,
            "median_asking_by_trim": {
                trim: round(median(prices)) for trim, prices in by_trim.items() if prices
            },
        }


@app.get("/api/listings")
def listings() -> list[dict]:
    """Active listings with their latest observed price/mileage + source."""
    out: list[dict] = []
    with session_scope() as s:
        rows = s.scalars(select(Listing).where(Listing.status == "active")).all()
        for listing in rows:
            obs = s.scalar(
                select(ListingObservation)
                .where(ListingObservation.listing_id == listing.id)
                .order_by(ListingObservation.observed_at.desc())
            )
            v = listing.vehicle
            src = s.get(Source, listing.source_id)
            out.append(
                {
                    "listing_id": listing.id,
                    "vehicle_id": v.id,
                    "vin": v.vin,
                    "year": v.year,
                    "trim": v.trim,
                    "transmission": v.transmission,
                    "price": float(obs.price) if obs and obs.price else None,
                    "mileage": obs.mileage if obs else None,
                    "source": src.key if src else None,
                    "url": listing.url,
                    "first_seen": listing.first_seen_at.isoformat(),
                    "last_seen": listing.last_seen_at.isoformat(),
                }
            )
    return out


@app.get("/api/vehicles/{vehicle_id}/history")
def price_history(vehicle_id: int) -> dict:
    """Full observation history across all of a vehicle's listings (lineage)."""
    with session_scope() as s:
        listings_ = s.scalars(select(Listing).where(Listing.vehicle_id == vehicle_id)).all()
        history = []
        for listing in listings_:
            obs = s.scalars(
                select(ListingObservation)
                .where(ListingObservation.listing_id == listing.id)
                .order_by(ListingObservation.observed_at.asc())
            ).all()
            for o in obs:
                history.append(
                    {
                        "listing_id": listing.id,
                        "source_id": listing.source_id,
                        "observed_at": o.observed_at.isoformat(),
                        "price": float(o.price) if o.price else None,
                        "mileage": o.mileage,
                        "status": o.status,
                    }
                )
        history.sort(key=lambda h: h["observed_at"])
        return {"vehicle_id": vehicle_id, "observations": history}
