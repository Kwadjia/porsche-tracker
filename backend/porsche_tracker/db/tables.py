"""Database schema.

Design goals baked into this schema:

* **Vehicle vs Listing vs Observation** are distinct. A ``Vehicle`` is the physical
  car (ideally VIN-keyed). A ``Listing`` is that car for-sale on one source. A
  ``ListingObservation`` is the state of that listing at one point in time — so
  price/mileage history is append-only and never overwritten.
* **Active vs transaction data** never blend: asking prices live on observations;
  verified sales live in ``transactions``.
* **Raw payloads are retained** (``raw_ingestions``) so parsers can be re-run later.
* **Lineage**: many listings (across sources and across time) can point at one
  vehicle, letting us reconstruct "listed private → failed at auction → dealer
  relist → price cuts".
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from porsche_tracker.db.base import Base

# JSONB in Postgres (prod), plain JSON on SQLite (zero-infra local dev + fast tests).
JSONB_ = JSONB().with_variant(JSON(), "sqlite")


def _utcnow() -> datetime:
    """Timezone-aware UTC now - a portable, ORM-side default (no DB now())."""
    return datetime.now(timezone.utc)


class Source(Base):
    """A data source (ebay, porsche_finder, a specific dealer, ...) plus a
    reliability weight used later when fields conflict across sources."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))  # api | dealer | aggregator | auction
    reliability_weight: Mapped[float] = mapped_column(Numeric(3, 2), default=Decimal("0.5"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(256))
    seller_type: Mapped[str] = mapped_column(String(16), default="unknown")
    city: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str | None] = mapped_column(String(32))
    zip: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("ix_sellers_name_state", "name", "state"),)


class Vehicle(Base):
    """The canonical physical car. Deduplicated primarily by VIN; when VIN is
    unknown a synthetic identity is used and later merged if a VIN appears."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str | None] = mapped_column(String(17), unique=True, index=True)

    year: Mapped[int | None] = mapped_column(Integer)
    trim: Mapped[str] = mapped_column(String(16), default="unknown")
    transmission: Mapped[str] = mapped_column(String(16), default="unknown")
    exterior_color: Mapped[str | None] = mapped_column(String(64))
    interior_color: Mapped[str | None] = mapped_column(String(64))

    # vPIC / VIN-decode enrichment, retained verbatim
    vin_decoded: Mapped[dict | None] = mapped_column(JSONB_)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    listings: Mapped[list["Listing"]] = relationship(back_populates="vehicle")
    options: Mapped[list["VehicleOption"]] = relationship(back_populates="vehicle")


class VehicleOption(Base):
    """An option/spec attributed to a vehicle, with confidence and provenance so a
    weak detection can be upgraded when a stronger source confirms it."""

    __tablename__ = "vehicle_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    code: Mapped[str] = mapped_column(String(48))
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), default=Decimal("0.5"))
    source_key: Mapped[str | None] = mapped_column(String(64))

    vehicle: Mapped[Vehicle] = relationship(back_populates="options")

    __table_args__ = (UniqueConstraint("vehicle_id", "code", name="uq_vehicle_option"),)


class Listing(Base):
    """A specific listing of a vehicle on a specific source. Stable across the
    listing's life; its changing state lives in observations."""

    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    seller_id: Mapped[int | None] = mapped_column(ForeignKey("sellers.id"), index=True)

    source_listing_id: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text)
    stock_number: Mapped[str | None] = mapped_column(String(64), index=True)

    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    vehicle: Mapped[Vehicle] = relationship(back_populates="listings")
    observations: Mapped[list["ListingObservation"]] = relationship(back_populates="listing")

    __table_args__ = (
        UniqueConstraint("source_id", "source_listing_id", name="uq_source_listing"),
    )


class ListingObservation(Base):
    """Append-only snapshot of a listing's mutable state at ``observed_at``.
    This is where price and mileage history is preserved — rows are never updated."""

    __tablename__ = "listing_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    mileage: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="active")

    title_status: Mapped[str] = mapped_column(String(16), default="unknown")
    accident_reported: Mapped[bool | None] = mapped_column(Boolean)

    options_raw: Mapped[list | None] = mapped_column(JSONB_)
    field_confidence: Mapped[dict | None] = mapped_column(JSONB_)
    raw_ingestion_id: Mapped[int | None] = mapped_column(ForeignKey("raw_ingestions.id"))

    listing: Mapped[Listing] = relationship(back_populates="observations")

    __table_args__ = (
        # dedup identical consecutive snapshots at ingest time
        Index("ix_obs_listing_time", "listing_id", "observed_at"),
    )


class Transaction(Base):
    """A *verified* completed sale. Kept strictly separate from asking-price
    observations so market (asking) and transaction (sold) analytics never blend."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id"))

    sold_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mileage: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String(64))  # e.g. BaT, dealer, private
    raw_ingestion_id: Mapped[int | None] = mapped_column(ForeignKey("raw_ingestions.id"))


class RawIngestion(Base):
    """Verbatim retained source payload. Parsers read from here, so a fixed/improved
    parser can be re-run over historical payloads without re-fetching."""

    __tablename__ = "raw_ingestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), index=True)
    source_listing_id: Mapped[str | None] = mapped_column(String(128), index=True)
    parser_version: Mapped[str] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # idempotency
    payload: Mapped[dict] = mapped_column(JSONB_)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("source_key", "content_hash", name="uq_raw_source_hash"),
    )
