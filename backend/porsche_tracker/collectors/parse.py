"""Shared, source-independent text parsing.

Every text/HTML source reuses these so trim/transmission/option detection is
consistent and testable in one place. Each returns a value plus is designed to be
paired with a confidence score by the caller.
"""

from __future__ import annotations

import re

from porsche_tracker.models import OptionCode, Transmission, Trim

# 981 Cayman VIN: WP0 + ... ; we validate loosely (17 chars, no I/O/Q).
_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
_YEAR_RE = re.compile(r"\b(20(1[3-6]))\b")  # 981 Cayman model years 2013–2016
_MILEAGE_RE = re.compile(r"([\d,]{2,7})\s*(?:mi|mile|miles|k\s*miles)\b", re.I)


def parse_vin(text: str | None) -> str | None:
    if not text:
        return None
    m = _VIN_RE.search(text.upper())
    if not m:
        return None
    vin = m.group(1)
    # Porsche WMI prefixes for 981 (WP0 US-built market codes)
    return vin if vin.startswith("WP0") else None


def parse_year(text: str | None) -> int | None:
    if not text:
        return None
    m = _YEAR_RE.search(text)
    return int(m.group(1)) if m else None


def parse_mileage(text: str | None) -> int | None:
    if not text:
        return None
    m = _MILEAGE_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    val = int(raw)
    if "k" in m.group(0).lower() and val < 1000:  # "42k miles"
        val *= 1000
    return val if 0 < val < 300_000 else None


def parse_trim(text: str | None) -> Trim:
    if not text:
        return Trim.UNKNOWN
    t = text.lower()
    if "cayman" not in t and "981" not in t:
        return Trim.UNKNOWN
    if "gt4" in t:
        return Trim.OTHER
    if "gts" in t:
        return Trim.CAYMAN_GTS
    # "S" is tricky — require word-boundary "cayman s" or " s " near cayman
    if re.search(r"cayman\s+s\b", t) or re.search(r"\b981\s+s\b", t):
        return Trim.CAYMAN_S
    if "cayman" in t:
        return Trim.CAYMAN
    return Trim.UNKNOWN


def parse_transmission(text: str | None) -> Transmission:
    if not text:
        return Transmission.UNKNOWN
    t = text.lower()
    if "pdk" in t or "automatic" in t or "dual clutch" in t or "dual-clutch" in t:
        return Transmission.PDK
    if re.search(r"\b6[\s-]*speed\b", t) or "manual" in t or " mt " in f" {t} ":
        return Transmission.MANUAL
    return Transmission.UNKNOWN


# option text -> normalized code; first hit wins per code
_OPTION_PATTERNS: list[tuple[OptionCode, re.Pattern[str]]] = [
    (OptionCode.PSE, re.compile(r"sport exhaust|\bpse\b", re.I)),
    (OptionCode.SPORT_CHRONO, re.compile(r"sport chrono|chrono package", re.I)),
    (OptionCode.PASM, re.compile(r"\bpasm\b|active suspension", re.I)),
    (OptionCode.ADAPTIVE_SPORT_SEATS_PLUS, re.compile(r"adaptive sport seats plus", re.I)),
    (OptionCode.SPORT_SEATS, re.compile(r"sport seats", re.I)),
    (OptionCode.BURMESTER, re.compile(r"burmester", re.I)),
    (OptionCode.BOSE, re.compile(r"\bbose\b", re.I)),
    (OptionCode.PCM_NAV, re.compile(r"\bpcm\b|navigation", re.I)),
    (OptionCode.PDLS, re.compile(r"\bpdls\b|dynamic light", re.I)),
    (OptionCode.PSD, re.compile(r"torque vectoring|\bptv\b|limited slip|limited-slip", re.I)),
    (OptionCode.SPORT_DESIGN_WHEELS, re.compile(r"sportdesign|sport design wheel", re.I)),
    (OptionCode.VENTILATED_SEATS, re.compile(r"ventilated seats", re.I)),
    (OptionCode.HEATED_SEATS, re.compile(r"heated seats", re.I)),
]


def detect_options(*texts: str | None) -> list[OptionCode]:
    blob = " \n ".join(t for t in texts if t)
    found: list[OptionCode] = []
    for code, pat in _OPTION_PATTERNS:
        if pat.search(blob) and code not in found:
            found.append(code)
    return found
