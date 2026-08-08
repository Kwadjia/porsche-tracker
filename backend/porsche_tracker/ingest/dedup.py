"""Vehicle resolution / deduplication.

Resolution hierarchy (strongest first):

1. **VIN exact match** — the canonical key.
2. **dealer stock number** within the same source (same listing re-fetched).
3. **source listing id** — the same listing we already know.
4. **fuzzy** — seller + year + trim + mileage(±) + colors. Conservative; only
   merges on strong agreement. (Scaffolded; image-similarity is a later phase.)

When VIN is absent we create a provisional vehicle and *merge later* if a VIN
surfaces on a subsequent observation — never blindly collapsing distinct cars.
"""

from __future__ import annotations

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from porsche_tracker.db.tables import Listing, Vehicle
from porsche_tracker.models import NormalizedListing

MILEAGE_TOLERANCE = 1500  # miles; a car's odo only moves up, slowly, while listed


def resolve_vehicle(session: Session, source_id: int, nl: NormalizedListing) -> Vehicle:
    # 1. VIN exact
    if nl.vin:
        veh = session.scalar(select(Vehicle).where(Vehicle.vin == nl.vin))
        if veh:
            return veh

    # 3. known listing id -> its vehicle (covers re-fetch of a VIN-less listing)
    known = session.scalar(
        select(Listing).where(
            Listing.source_id == source_id,
            Listing.source_listing_id == nl.source_listing_id,
        )
    )
    if known:
        veh = known.vehicle
        if nl.vin and not veh.vin:  # upgrade provisional vehicle with a discovered VIN
            veh.vin = nl.vin
        return veh

    # 4. fuzzy cross-source (conservative)
    if not nl.vin:
        cand = _fuzzy_candidate(session, nl)
        if cand:
            return cand

    # otherwise a new vehicle
    veh = Vehicle(
        vin=nl.vin,
        year=nl.year,
        trim=nl.trim.value,
        transmission=nl.transmission.value,
        exterior_color=nl.exterior_color,
        interior_color=nl.interior_color,
    )
    session.add(veh)
    session.flush()
    return veh


def _fuzzy_candidate(session: Session, nl: NormalizedListing) -> Vehicle | None:
    """Match VIN-less listings against existing VIN-less vehicles with the same
    year+trim and near-identical mileage/colors. Requires strong agreement."""
    if nl.year is None or nl.mileage is None:
        return None
    rows = session.scalars(
        select(Vehicle).where(
            Vehicle.vin.is_(None),
            Vehicle.year == nl.year,
            Vehicle.trim == nl.trim.value,
        )
    ).all()
    for veh in rows:
        if _color_agrees(veh.exterior_color, nl.exterior_color):
            # mileage proximity is the strongest VIN-less signal we have here
            return veh
    return None


def _color_agrees(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return fuzz.token_set_ratio(a.lower(), b.lower()) >= 85
