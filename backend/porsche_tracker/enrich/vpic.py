"""VIN enrichment via NHTSA vPIC — free, no API key.

Given a VIN we get authoritative model-year and often model/series/transmission,
used to validate and back-fill collector-parsed fields. The full decode is retained
on ``vehicles.vin_decoded`` so attributes can be re-derived later.

Runs as a **separate idempotent pass** (``porsche enrich-vins``) rather than inside
ingest: it's network-bound, retryable, and should never block or fail a collection
run. Only vehicles with a VIN and no prior decode are processed.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from porsche_tracker.config import settings
from porsche_tracker.db.tables import Vehicle
from porsche_tracker.models import Transmission, Trim

_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"


def decode_vin(vin: str, client: httpx.Client | None = None) -> dict[str, Any] | None:
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": settings.user_agent})
    try:
        resp = client.get(_URL.format(vin=vin), timeout=settings.request_timeout_s)
        resp.raise_for_status()
        results = resp.json().get("Results") or []
        return results[0] if results else None
    except Exception:  # noqa: BLE001 — enrichment is best-effort
        return None
    finally:
        if own:
            client.close()


def map_decode(decoded: dict[str, Any]) -> dict[str, Any]:
    """Pure mapping: vPIC decode -> normalized hints. No DB, fully unit-testable."""
    hints: dict[str, Any] = {}

    year = _int(decoded.get("ModelYear"))
    if year:
        hints["year"] = year

    tx = (decoded.get("TransmissionStyle") or "").lower()
    if "manual" in tx and "automated" not in tx:
        hints["transmission"] = Transmission.MANUAL
    elif any(k in tx for k in ("dual-clutch", "dual clutch", "dct", "automated", "automatic")):
        hints["transmission"] = Transmission.PDK

    # trim/series text -> S vs GTS (conservative; only strengthens UNKNOWN)
    text = " ".join(
        str(decoded.get(k) or "") for k in ("Trim", "Trim2", "Series", "Series2", "Model")
    ).lower()
    if "gts" in text:
        hints["trim"] = Trim.CAYMAN_GTS
    elif "cayman" in text and (" s" in f" {text}" or text.endswith(" s")):
        hints["trim"] = Trim.CAYMAN_S

    return hints


def enrich_vehicles(session: Session, limit: int = 200, client: httpx.Client | None = None) -> int:
    """Decode VINs for vehicles missing a decode; back-fill only UNKNOWN/empty fields
    so collector-provided values are never clobbered. Returns count enriched."""
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": settings.user_agent})
    enriched = 0
    try:
        todo = session.scalars(
            select(Vehicle)
            .where(Vehicle.vin.is_not(None), Vehicle.vin_decoded.is_(None))
            .limit(limit)
        ).all()
        for veh in todo:
            decoded = decode_vin(veh.vin, client=client)
            if not decoded:
                continue
            veh.vin_decoded = decoded
            hints = map_decode(decoded)
            if veh.year is None and "year" in hints:
                veh.year = hints["year"]
            if veh.transmission == Transmission.UNKNOWN.value and "transmission" in hints:
                veh.transmission = hints["transmission"].value
            if veh.trim == Trim.UNKNOWN.value and "trim" in hints:
                veh.trim = hints["trim"].value
            enriched += 1
    finally:
        if own:
            client.close()
    return enriched


def _int(val: Any) -> int | None:
    if val in (None, ""):
        return None
    digits = "".join(ch for ch in str(val) if ch.isdigit())
    return int(digits) if digits else None
