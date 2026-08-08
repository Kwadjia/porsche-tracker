import json
from decimal import Decimal
from pathlib import Path

from porsche_tracker.collectors.ebay import EbayCollector
from porsche_tracker.models import OptionCode, Transmission, Trim

FIXTURE = Path(__file__).parent / "fixtures" / "ebay_item_summary.json"


def test_map_item_from_summary():
    item = json.loads(FIXTURE.read_text())
    # fetch_detail=False keeps this a pure, offline unit test
    collector = EbayCollector(fetch_detail=False)
    nl = collector._map_item(client=None, headers={}, item=item)

    assert nl is not None
    assert nl.source == "ebay"
    assert nl.source_listing_id == "v1|1234567890|0"
    assert nl.year == 2015
    assert nl.trim is Trim.CAYMAN_GTS
    assert nl.transmission is Transmission.PDK
    assert nl.mileage == 28400
    assert nl.price == Decimal("58995.00")
    assert nl.location_state == "TX"
    assert nl.seller_name == "premier_autohaus"
    assert OptionCode.SPORT_CHRONO in nl.options
    assert OptionCode.PSE in nl.options
    assert nl.raw_ref  # raw payload is referenced for retention
