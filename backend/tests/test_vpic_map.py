from porsche_tracker.enrich.vpic import map_decode
from porsche_tracker.models import Transmission, Trim


def test_map_decode_gts_pdk():
    decoded = {
        "ModelYear": "2015",
        "Model": "Cayman",
        "Series": "981",
        "Trim": "GTS",
        "TransmissionStyle": "Dual-Clutch Transmission (DCT)",
    }
    hints = map_decode(decoded)
    assert hints["year"] == 2015
    assert hints["trim"] is Trim.CAYMAN_GTS
    assert hints["transmission"] is Transmission.PDK


def test_map_decode_s_manual():
    decoded = {
        "ModelYear": "2014",
        "Model": "Cayman S",
        "TransmissionStyle": "Manual/Standard",
    }
    hints = map_decode(decoded)
    assert hints["year"] == 2014
    assert hints["trim"] is Trim.CAYMAN_S
    assert hints["transmission"] is Transmission.MANUAL


def test_map_decode_sparse():
    # missing fields -> no false hints
    assert map_decode({"ModelYear": ""}) == {}
