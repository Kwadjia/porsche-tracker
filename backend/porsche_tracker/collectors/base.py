"""Collector protocol + shared HTTP helpers.

Each source lives in its own module and subclasses ``Collector``. A collector's
only job: retrieve from its source and emit ``NormalizedListing`` objects plus the
raw payloads to retain. It must not touch the database — ingest handles that. This
keeps adapters independently testable against recorded fixtures.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from porsche_tracker.config import settings
from porsche_tracker.models import CollectorResult


def content_hash(payload: Any) -> str:
    """Stable hash of a raw payload for idempotency + raw-retention dedup."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


class Collector(ABC):
    #: unique, stable source key (matches ``sources.key``)
    key: str
    #: human-facing name
    display_name: str
    #: api | dealer | aggregator | auction
    kind: str = "api"
    #: bump when parsing logic changes so re-parses are traceable
    parser_version: str = "1"

    @abstractmethod
    def collect(self) -> CollectorResult:
        """Retrieve and normalize. Pure w.r.t. the DB; safe to run in tests."""
        ...

    # -- shared, polite HTTP ------------------------------------------------- #
    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=20))
    def _get(self, client: httpx.Client, url: str, **kw: Any) -> httpx.Response:
        resp = client.get(url, timeout=settings.request_timeout_s, **kw)
        resp.raise_for_status()
        return resp

    def _client(self, **kw: Any) -> httpx.Client:
        headers = {"User-Agent": settings.user_agent, **kw.pop("headers", {})}
        return httpx.Client(headers=headers, **kw)


class HtmlCollector(Collector):
    """Base for adapters that fetch HTML/JSON directly from a site (dealers, feeds).

    All fetches go through a robots.txt gate: a disallowed URL is skipped (returns
    ``None``), never fetched. Adapters must not bypass this. API-backed collectors
    (eBay etc.) subclass ``Collector`` directly and don't need robots gating.
    """

    kind = "dealer"

    def fetch(self, client: httpx.Client, url: str, gate: "RobotsGate | None" = None) -> httpx.Response | None:
        from porsche_tracker.collectors.robots import RobotsGate

        gate = gate or RobotsGate(client)
        if not gate.allowed(url):
            return None  # respect access constraints — do not fetch disallowed URLs
        return self._get(client, url)
