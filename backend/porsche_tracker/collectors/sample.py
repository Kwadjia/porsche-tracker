"""Synthetic demo source — NOT real data.

Lets the whole pipeline (collect → ingest → dedup → API → dashboard) be exercised
end-to-end before any real API keys exist. It deliberately includes:

* the **same VIN on two sources** (dealer + marketplace) → must dedup to ONE vehicle
  with two listings (lineage);
* **prices that fall over simulated days** → proves append-only observation history;
* a **VIN-less private listing** → proves provisional-vehicle handling;
* a realistic spread of S/GTS, PDK/manual, options, colors, and geography.

``SampleCollector(as_of=...)`` returns that day's snapshot, so replaying a date
range through the normal ingest path produces genuine price history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from porsche_tracker.collectors.base import Collector, content_hash
from porsche_tracker.models import (
    CollectorResult,
    ListingStatus,
    NormalizedListing,
    OptionCode,
    SellerType,
    Transmission,
    Trim,
)

# demo history spans this many days ending "today"
DEMO_DAYS = 6


@dataclass
class _Spec:
    source: str
    source_listing_id: str
    vin: str | None
    year: int
    trim: Trim
    transmission: Transmission
    mileage: int
    base_price: int
    drops: list[tuple[int, int]]  # (day_index, new_price) — cumulative reductions
    ext: str
    intr: str
    city: str
    state: str
    seller: str
    seller_type: SellerType
    options: list[OptionCode] = field(default_factory=list)

    def price_on(self, day: int) -> Decimal:
        price = self.base_price
        for d, p in self.drops:
            if day >= d:
                price = p
        return Decimal(price)


# GTS #1 — SAME VIN listed on both a dealer site and a marketplace (dedup target)
_GTS1_VIN = "WP0AB2A88FK123456"
_SPECS: list[_Spec] = [
    _Spec("sample_dealer", "D-4471", _GTS1_VIN, 2015, Trim.CAYMAN_GTS, Transmission.PDK,
          28400, 62900, [(2, 60900), (4, 59900)], "GT Silver", "Black",
          "Austin", "TX", "Prestige Autohaus", SellerType.DEALER,
          [OptionCode.PSE, OptionCode.SPORT_CHRONO, OptionCode.PASM, OptionCode.BURMESTER]),
    _Spec("sample_marketplace", "M-99812", _GTS1_VIN, 2015, Trim.CAYMAN_GTS, Transmission.PDK,
          28400, 61500, [(3, 59900)], "GT Silver", "Black",
          "Austin", "TX", "Prestige Autohaus", SellerType.DEALER,
          [OptionCode.PSE, OptionCode.SPORT_CHRONO, OptionCode.PASM]),
    _Spec("sample_marketplace", "M-77341", "WP0AB2A85EK789012", 2014, Trim.CAYMAN_S,
          Transmission.MANUAL, 41200, 48500, [(3, 46900)], "White", "Black",
          "Denver", "CO", "private seller", SellerType.PRIVATE,
          [OptionCode.PSE, OptionCode.SPORT_CHRONO]),
    _Spec("sample_dealer", "D-5120", "WP0AB2A99GK111213", 2016, Trim.CAYMAN_GTS,
          Transmission.PDK, 19800, 68000, [], "Racing Yellow", "Black",
          "Miami", "FL", "Euro Motors Miami", SellerType.DEALER,
          [OptionCode.PSE, OptionCode.SPORT_CHRONO, OptionCode.PASM, OptionCode.PDLS,
           OptionCode.ADAPTIVE_SPORT_SEATS_PLUS]),
    _Spec("sample_dealer", "D-6033", "WP0AB2A84FK445566", 2015, Trim.CAYMAN_S,
          Transmission.PDK, 33600, 51900, [(2, 50500), (5, 48900)], "Guards Red", "Black",
          "Los Angeles", "CA", "Coast Euro", SellerType.DEALER,
          [OptionCode.SPORT_CHRONO, OptionCode.PASM]),
    # VIN-less private listing -> provisional vehicle
    _Spec("sample_marketplace", "M-10233", None, 2014, Trim.CAYMAN_S,
          Transmission.MANUAL, 52100, 46500, [(4, 44900)], "Black", "Black",
          "Portland", "OR", "enthusiast owner", SellerType.PRIVATE,
          [OptionCode.PSE]),
]


class SampleCollector(Collector):
    key = "sample"  # overridden per-listing via spec.source; used for dispatch only
    display_name = "Sample (synthetic demo data)"
    kind = "api"
    parser_version = "demo-1"

    def __init__(self, as_of: datetime | None = None, day_index: int = DEMO_DAYS - 1) -> None:
        self.as_of = as_of or datetime.now(timezone.utc)
        self.day_index = day_index

    def collect(self) -> CollectorResult:
        # a synthetic collector spanning multiple logical sources
        result = CollectorResult(source="sample")
        for spec in _SPECS:
            payload = {"spec_id": spec.source_listing_id, "day": self.day_index,
                       "price": int(spec.price_on(self.day_index))}
            raw_ref = content_hash(payload)
            result.raw_payloads[raw_ref] = payload
            result.listings.append(
                NormalizedListing(
                    source=spec.source,
                    source_listing_id=spec.source_listing_id,
                    listing_url=f"https://example.com/{spec.source}/{spec.source_listing_id}",
                    parser_version=self.parser_version,
                    observed_at=self.as_of,
                    vin=spec.vin,
                    year=spec.year,
                    trim=spec.trim,
                    transmission=spec.transmission,
                    mileage=spec.mileage,
                    price=spec.price_on(self.day_index),
                    exterior_color=spec.ext,
                    interior_color=spec.intr,
                    location_city=spec.city,
                    location_state=spec.state,
                    seller_name=spec.seller,
                    seller_type=spec.seller_type,
                    options=spec.options,
                    status=ListingStatus.ACTIVE,
                    field_confidence={"vin": 1.0 if spec.vin else 0.0, "trim": 1.0},
                    raw_ref=raw_ref,
                )
            )
        return result


def replay_days(days: int = DEMO_DAYS):
    """Yield (SampleCollector) snapshots for each day in an ending-today window."""
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    for i in range(days):
        as_of = today - timedelta(days=days - 1 - i)
        yield SampleCollector(as_of=as_of, day_index=i)
