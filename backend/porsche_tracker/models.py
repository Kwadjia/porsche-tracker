"""Normalized internal representation.

Every collector, regardless of source, emits a ``NormalizedListing``. The rest of
the system (dedup, ingest, analytics) only ever deals with this contract, never
with source-specific shapes. Source-specific parsing lives in ``collectors/``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Controlled vocabularies                                                      #
# --------------------------------------------------------------------------- #
class Trim(str, Enum):
    """981 Cayman trims we track. ``CAYMAN`` (base) is kept for context/dedup even
    though it is not a buy target."""

    CAYMAN_S = "cayman_s"
    CAYMAN_GTS = "cayman_gts"
    CAYMAN = "cayman"  # base 2.7 — tracked but not a target
    OTHER = "other"  # e.g. GT4, Boxster, or a non-981
    UNKNOWN = "unknown"


class Transmission(str, Enum):
    PDK = "pdk"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class SellerType(str, Enum):
    DEALER = "dealer"
    PRIVATE = "private"
    AUCTION = "auction"
    UNKNOWN = "unknown"


class ListingStatus(str, Enum):
    """State of a *listing* at observation time.

    We deliberately separate ``ENDED`` (listing disappeared, outcome unknown) from
    ``SOLD`` (verified transaction). Never blend asking prices with sale prices.
    """

    ACTIVE = "active"
    ENDED = "ended"  # vanished from source; outcome unknown
    SOLD = "sold"  # verified sold (transaction data)
    UNKNOWN = "unknown"


class TitleStatus(str, Enum):
    CLEAN = "clean"
    SALVAGE = "salvage"
    REBUILT = "rebuilt"
    UNKNOWN = "unknown"


class OptionCode(str, Enum):
    """Normalized, source-independent option identifiers.

    Collectors map noisy source text (option lists, descriptions) onto these. The
    raw source text is always retained on the observation so mappings can be
    re-derived later if we improve detection.
    """

    PSE = "pse"  # Porsche Sport Exhaust — highly desirable
    SPORT_CHRONO = "sport_chrono"
    PASM = "pasm"  # adaptive suspension
    SPORT_SEATS = "sport_seats"
    ADAPTIVE_SPORT_SEATS_PLUS = "adaptive_sport_seats_plus"
    BOSE = "bose"
    BURMESTER = "burmester"
    PCM_NAV = "pcm_nav"
    SPORT_DESIGN_WHEELS = "sport_design_wheels"
    CARRERA_S_WHEELS = "carrera_s_wheels"
    PDLS = "pdls"  # dynamic light system
    PSD = "psd"  # limited-slip / torque vectoring (PTV)
    HEATED_SEATS = "heated_seats"
    VENTILATED_SEATS = "ventilated_seats"


# --------------------------------------------------------------------------- #
# The normalized listing contract                                             #
# --------------------------------------------------------------------------- #
class NormalizedListing(BaseModel):
    """A single observation of a single listing on a single source.

    One collector run produces many of these. ``observed_at`` + the identity keys
    let ingest decide whether this is a new listing, a new observation of a known
    listing, or a no-op.
    """

    model_config = ConfigDict(use_enum_values=False)

    # --- provenance / identity ------------------------------------------------
    source: str = Field(..., description="Source key, e.g. 'ebay', 'porsche_finder'")
    source_listing_id: str = Field(..., description="Stable id within the source")
    listing_url: str
    parser_version: str = Field(..., description="Version of the parser that produced this")
    observed_at: datetime

    # --- vehicle identity -----------------------------------------------------
    vin: str | None = None
    stock_number: str | None = None

    # --- core attributes (POC success criteria) ------------------------------
    year: int | None = None
    trim: Trim = Trim.UNKNOWN
    transmission: Transmission = Transmission.UNKNOWN
    mileage: int | None = None
    price: Decimal | None = None
    currency: str = "USD"

    exterior_color: str | None = None
    interior_color: str | None = None

    # --- location -------------------------------------------------------------
    location_city: str | None = None
    location_state: str | None = None
    location_zip: str | None = None

    # --- seller ---------------------------------------------------------------
    seller_name: str | None = None
    seller_type: SellerType = SellerType.UNKNOWN

    # --- options / condition --------------------------------------------------
    options: list[OptionCode] = Field(default_factory=list)
    options_raw: list[str] = Field(default_factory=list, description="Unmapped source option text")
    title_status: TitleStatus = TitleStatus.UNKNOWN
    accident_reported: bool | None = None

    # --- listing state --------------------------------------------------------
    status: ListingStatus = ListingStatus.ACTIVE
    sold_price: Decimal | None = None  # only set when status == SOLD

    # --- quality / lineage ----------------------------------------------------
    field_confidence: dict[str, float] = Field(
        default_factory=dict,
        description="Per-field confidence 0..1, e.g. {'vin': 1.0, 'trim': 0.7}",
    )
    raw_ref: str | None = Field(
        default=None, description="Hash/id linking to the retained raw payload row"
    )

    def identity_key(self) -> tuple[str, str]:
        """The listing's stable identity within its source."""
        return (self.source, self.source_listing_id)


class CollectorResult(BaseModel):
    """What a collector run returns: the listings plus the raw payloads to retain."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str
    listings: list[NormalizedListing] = Field(default_factory=list)
    # raw payloads keyed by the raw_ref referenced on listings, retained verbatim
    raw_payloads: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
