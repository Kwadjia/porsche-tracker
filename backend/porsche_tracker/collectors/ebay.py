"""eBay Motors collector via the official Browse API (free developer account).

Auth: OAuth2 client-credentials. Search: Browse ``item_summary/search`` scoped to
the Motors marketplace. Item summaries are shallow (title/price/location/seller);
year/trim/transmission/mileage/VIN are parsed from the title and — for promising
candidates — the item detail's ``localizedAspects``. This respects eBay ToS: it's
the sanctioned API, no scraping.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from porsche_tracker.collectors import parse
from porsche_tracker.collectors.base import Collector, content_hash
from porsche_tracker.config import settings
from porsche_tracker.models import (
    CollectorResult,
    ListingStatus,
    NormalizedListing,
    SellerType,
    Trim,
)

_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_SCOPE = "https://api.ebay.com/oauth/api_scope"
_MOTORS_CARS_CATEGORY = "6001"  # Cars & Trucks


class EbayCollector(Collector):
    key = "ebay"
    display_name = "eBay Motors"
    kind = "api"
    parser_version = "1"

    # queries we sweep; kept broad, trim-filtered after parsing
    QUERIES = ["Porsche Cayman S 981", "Porsche Cayman GTS 981", "Porsche 981 Cayman"]
    TARGET_TRIMS = {Trim.CAYMAN_S, Trim.CAYMAN_GTS}

    def __init__(self, fetch_detail: bool = True, limit_per_query: int = 100) -> None:
        self.fetch_detail = fetch_detail
        self.limit_per_query = limit_per_query

    # ------------------------------------------------------------------ auth
    def _token(self, client: httpx.Client) -> str:
        if not (settings.ebay_client_id and settings.ebay_client_secret):
            raise RuntimeError("EBAY_CLIENT_ID/SECRET not configured")
        basic = base64.b64encode(
            f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
        ).decode()
        resp = client.post(
            _OAUTH_URL,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": _SCOPE},
            timeout=settings.request_timeout_s,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    # --------------------------------------------------------------- collect
    def collect(self) -> CollectorResult:
        result = CollectorResult(source=self.key)
        with self._client() as client:
            try:
                token = self._token(client)
            except Exception as exc:  # noqa: BLE001 — surface, don't crash the run
                result.errors.append(f"auth failed: {exc}")
                return result

            headers = {
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": settings.ebay_marketplace,
            }
            seen: set[str] = set()
            for q in self.QUERIES:
                try:
                    self._sweep_query(client, headers, q, seen, result)
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(f"query {q!r}: {exc}")
        return result

    def _sweep_query(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        q: str,
        seen: set[str],
        result: CollectorResult,
    ) -> None:
        offset = 0
        while offset < self.limit_per_query:
            resp = self._get(
                client,
                _SEARCH_URL,
                headers=headers,
                params={
                    "q": q,
                    "category_ids": _MOTORS_CARS_CATEGORY,
                    "limit": 50,
                    "offset": offset,
                },
            )
            data = resp.json()
            items = data.get("itemSummaries") or []
            if not items:
                break
            for item in items:
                iid = str(item.get("itemId", ""))
                if not iid or iid in seen:
                    continue
                seen.add(iid)
                listing = self._map_item(client, headers, item)
                if listing and listing.trim in self.TARGET_TRIMS:
                    result.raw_payloads[listing.raw_ref] = item
                    result.listings.append(listing)
            offset += 50
            if offset >= (data.get("total") or 0):
                break

    # ----------------------------------------------------------------- map
    def _map_item(
        self, client: httpx.Client, headers: dict[str, str], item: dict[str, Any]
    ) -> NormalizedListing | None:
        title = item.get("title") or ""
        detail_text = ""
        aspects: dict[str, str] = {}
        raw: dict[str, Any] = {"summary": item}

        if self.fetch_detail and item.get("itemId"):
            aspects, detail = self._detail_aspects(client, headers, item["itemId"])
            if detail is not None:
                raw["detail"] = detail
                detail_text = " ".join(f"{k} {v}" for k, v in aspects.items())

        text = f"{title}\n{detail_text}"
        vin = parse.parse_vin(text) or aspects.get("VIN") or aspects.get("Vehicle Identification Number")

        price = self._price(item)
        loc = item.get("itemLocation") or {}
        seller = item.get("seller") or {}

        raw_ref = content_hash(raw)
        return NormalizedListing(
            source=self.key,
            source_listing_id=str(item["itemId"]),
            listing_url=item.get("itemWebUrl") or item.get("itemHref") or "",
            parser_version=self.parser_version,
            observed_at=datetime.now(timezone.utc),
            vin=vin,
            year=parse.parse_year(text) or self._int(aspects.get("Year")),
            trim=parse.parse_trim(text),
            transmission=parse.parse_transmission(text or aspects.get("Transmission", "")),
            mileage=parse.parse_mileage(text) or self._int(aspects.get("Mileage")),
            price=price,
            exterior_color=aspects.get("Exterior Color"),
            interior_color=aspects.get("Interior Color"),
            location_city=loc.get("city"),
            location_state=loc.get("stateOrProvince"),
            location_zip=loc.get("postalCode"),
            seller_name=seller.get("username"),
            seller_type=SellerType.UNKNOWN,
            options=parse.detect_options(text),
            options_raw=list(aspects.values()) if aspects else [],
            status=ListingStatus.ACTIVE,
            field_confidence={
                "vin": 1.0 if vin else 0.0,
                "trim": 0.8 if "cayman" in title.lower() else 0.5,
                "price": 1.0 if price is not None else 0.0,
            },
            raw_ref=raw_ref,
        )

    def _detail_aspects(
        self, client: httpx.Client, headers: dict[str, str], item_id: str
    ) -> tuple[dict[str, str], dict[str, Any] | None]:
        try:
            resp = self._get(
                client,
                f"https://api.ebay.com/buy/browse/v1/item/{item_id}",
                headers=headers,
            )
        except Exception:  # noqa: BLE001 — detail is best-effort enrichment
            return {}, None
        detail = resp.json()
        aspects = {
            a["name"]: a["value"]
            for a in detail.get("localizedAspects", [])
            if a.get("name") and a.get("value")
        }
        return aspects, detail

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _price(item: dict[str, Any]) -> Decimal | None:
        p = item.get("price") or {}
        try:
            return Decimal(str(p["value"])) if "value" in p else None
        except (InvalidOperation, KeyError):
            return None

    @staticmethod
    def _int(val: Any) -> int | None:
        if val is None:
            return None
        digits = "".join(ch for ch in str(val) if ch.isdigit())
        return int(digits) if digits else None
