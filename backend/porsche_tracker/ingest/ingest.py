"""Idempotent ingestion of a CollectorResult into the store.

Guarantees:
* **Raw retention** — every payload is stored once (idempotent by content hash)
  before parsing-derived rows, so parsers can be re-run later.
* **Append-only observations** — a new ``ListingObservation`` is written only when
  the mutable state (price/mileage/status/title) actually changed vs the latest
  one. Re-running an unchanged daily sweep is a no-op for history but still bumps
  ``last_seen_at`` (so we can distinguish "still listed" from "disappeared").
* **No blending** — sold listings emit a ``Transaction``; asking prices never do.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from porsche_tracker.db.tables import (
    Listing,
    ListingObservation,
    RawIngestion,
    Seller,
    Source,
    Transaction,
    Vehicle,
    VehicleOption,
)
from porsche_tracker.ingest.dedup import resolve_vehicle
from porsche_tracker.models import CollectorResult, ListingStatus, NormalizedListing


@dataclass
class IngestStats:
    listings_seen: int = 0
    new_listings: int = 0
    new_observations: int = 0
    new_vehicles: int = 0
    transactions: int = 0
    raw_stored: int = 0


def ingest(
    session: Session,
    result: CollectorResult,
    source_meta: dict[str, dict] | None = None,
) -> IngestStats:
    """Ingest a collector result. ``source_meta`` optionally maps a source key to
    display metadata (display_name/kind/reliability_weight); the ``Source`` row is
    resolved per-listing from ``nl.source`` so a single collector may span multiple
    logical sources (e.g. discovery adapters)."""
    stats = IngestStats()
    meta_by_key = source_meta or {}

    for nl in result.listings:
        stats.listings_seen += 1
        source = _ensure_source(session, nl.source, meta_by_key.get(nl.source, {}))
        raw_id = _store_raw(session, nl, result, stats)
        veh = resolve_vehicle(session, source.id, nl)
        if veh.id is None:
            session.flush()
        seller = _ensure_seller(session, nl)
        listing, is_new = _upsert_listing(session, source, veh, seller, nl)
        if is_new:
            stats.new_listings += 1
        _maybe_observe(session, listing, nl, raw_id, stats)
        _upsert_options(session, veh, nl)
        if nl.status == ListingStatus.SOLD and nl.sold_price is not None:
            _record_transaction(session, source, veh, listing, nl, raw_id, stats)

    session.flush()
    return stats


# --------------------------------------------------------------------------- #
def _ensure_source(session: Session, key: str, meta: dict) -> Source:
    src = session.scalar(select(Source).where(Source.key == key))
    if src is None:
        src = Source(
            key=key,
            display_name=meta.get("display_name", key),
            kind=meta.get("kind", "api"),
            reliability_weight=Decimal(str(meta.get("reliability_weight", 0.5))),
        )
        session.add(src)
        session.flush()
    return src


def _store_raw(
    session: Session, nl: NormalizedListing, result: CollectorResult, stats: IngestStats
) -> int | None:
    if not nl.raw_ref:
        return None
    existing = session.scalar(
        select(RawIngestion).where(
            RawIngestion.source_key == nl.source,
            RawIngestion.content_hash == nl.raw_ref,
        )
    )
    if existing:
        return existing.id
    raw = RawIngestion(
        source_key=nl.source,
        source_listing_id=nl.source_listing_id,
        parser_version=nl.parser_version,
        content_hash=nl.raw_ref,
        payload=result.raw_payloads.get(nl.raw_ref, {}),
    )
    session.add(raw)
    session.flush()
    stats.raw_stored += 1
    return raw.id


def _ensure_seller(session: Session, nl: NormalizedListing) -> Seller | None:
    if not nl.seller_name:
        return None
    seller = session.scalar(
        select(Seller).where(Seller.name == nl.seller_name, Seller.state == nl.location_state)
    )
    if seller is None:
        seller = Seller(
            name=nl.seller_name,
            seller_type=nl.seller_type.value,
            city=nl.location_city,
            state=nl.location_state,
            zip=nl.location_zip,
        )
        session.add(seller)
        session.flush()
    return seller


def _upsert_listing(
    session: Session, source: Source, veh: Vehicle, seller: Seller | None, nl: NormalizedListing
) -> tuple[Listing, bool]:
    listing = session.scalar(
        select(Listing).where(
            Listing.source_id == source.id,
            Listing.source_listing_id == nl.source_listing_id,
        )
    )
    if listing is None:
        listing = Listing(
            source_id=source.id,
            vehicle_id=veh.id,
            seller_id=seller.id if seller else None,
            source_listing_id=nl.source_listing_id,
            url=nl.listing_url,
            stock_number=nl.stock_number,
            status=nl.status.value,
            first_seen_at=nl.observed_at,
            last_seen_at=nl.observed_at,
        )
        session.add(listing)
        session.flush()
        return listing, True

    listing.last_seen_at = nl.observed_at
    listing.status = nl.status.value
    if seller and not listing.seller_id:
        listing.seller_id = seller.id
    return listing, False


def _maybe_observe(
    session: Session, listing: Listing, nl: NormalizedListing, raw_id: int | None, stats: IngestStats
) -> None:
    latest = session.scalar(
        select(ListingObservation)
        .where(ListingObservation.listing_id == listing.id)
        .order_by(ListingObservation.observed_at.desc())
    )
    changed = (
        latest is None
        or latest.price != nl.price
        or latest.mileage != nl.mileage
        or latest.status != nl.status.value
        or latest.title_status != nl.title_status.value
    )
    if not changed:
        return  # idempotent: identical state, preserve history without spamming rows
    obs = ListingObservation(
        listing_id=listing.id,
        observed_at=nl.observed_at,
        price=nl.price,
        currency=nl.currency,
        mileage=nl.mileage,
        status=nl.status.value,
        title_status=nl.title_status.value,
        accident_reported=nl.accident_reported,
        options_raw=nl.options_raw or None,
        field_confidence=nl.field_confidence or None,
        raw_ingestion_id=raw_id,
    )
    session.add(obs)
    stats.new_observations += 1


def _upsert_options(session: Session, veh: Vehicle, nl: NormalizedListing) -> None:
    # query from the DB (not the relationship) so options added by a sibling listing
    # of the same vehicle earlier in this run are visible and not re-inserted
    existing = {
        o.code: o
        for o in session.scalars(
            select(VehicleOption).where(VehicleOption.vehicle_id == veh.id)
        ).all()
    }
    for code in nl.options:
        conf = nl.field_confidence.get(f"option:{code.value}", 0.6)
        if code.value in existing:
            existing[code.value].confidence = max(float(existing[code.value].confidence), conf)
        else:
            opt = VehicleOption(
                vehicle_id=veh.id, code=code.value, confidence=conf, source_key=nl.source
            )
            session.add(opt)
            existing[code.value] = opt
    session.flush()


def _record_transaction(
    session: Session,
    source: Source,
    veh: Vehicle,
    listing: Listing,
    nl: NormalizedListing,
    raw_id: int | None,
    stats: IngestStats,
) -> None:
    session.add(
        Transaction(
            vehicle_id=veh.id,
            source_id=source.id,
            listing_id=listing.id,
            sold_price=nl.sold_price,
            currency=nl.currency,
            sold_at=nl.observed_at,
            mileage=nl.mileage,
            venue=nl.source,
            raw_ingestion_id=raw_id,
        )
    )
    stats.transactions += 1
