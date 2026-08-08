"""robots.txt compliance for any source we fetch directly.

The project's stated principle: respect source access constraints — never bypass
anti-bot/technical restrictions. This gate is the enforcement point every HTML /
dealer adapter routes through, so "we don't fetch what a site disallows" is a
property of the framework, not each adapter's good intentions.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from porsche_tracker.config import settings


def is_allowed(robots_txt: str | None, user_agent: str, url: str) -> bool:
    """Pure policy check: given robots.txt content, may ``user_agent`` fetch ``url``?

    No robots.txt (None) -> allowed (standard convention). Fully offline/testable.
    """
    if robots_txt is None:
        return True
    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    return rp.can_fetch(user_agent, url)


class RobotsGate:
    """Fetches and caches robots.txt per host, then authorizes URLs. On network
    failure fetching robots.txt we fail-open (treat as allowed) — same as browsers
    and standard crawlers — but a disallow rule is always honored."""

    def __init__(self, client: httpx.Client, user_agent: str | None = None) -> None:
        self._client = client
        self._ua = user_agent or settings.user_agent
        self._cache: dict[str, str | None] = {}

    def _robots_for(self, url: str) -> str | None:
        p = urlparse(url)
        host = f"{p.scheme}://{p.netloc}"
        if host not in self._cache:
            try:
                resp = self._client.get(urljoin(host, "/robots.txt"), timeout=10.0)
                self._cache[host] = resp.text if resp.status_code == 200 else None
            except Exception:  # noqa: BLE001 — fail-open on fetch error
                self._cache[host] = None
        return self._cache[host]

    def allowed(self, url: str) -> bool:
        return is_allowed(self._robots_for(url), self._ua, url)
