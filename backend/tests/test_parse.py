from decimal import Decimal

from porsche_tracker.collectors import parse
from porsche_tracker.models import OptionCode, Transmission, Trim


def test_parse_trim():
    assert parse.parse_trim("2015 Porsche Cayman GTS") is Trim.CAYMAN_GTS
    assert parse.parse_trim("2014 Porsche Cayman S PDK") is Trim.CAYMAN_S
    assert parse.parse_trim("2013 Porsche Cayman 2.7") is Trim.CAYMAN
    assert parse.parse_trim("2016 Cayman GT4") is Trim.OTHER
    assert parse.parse_trim("2015 BMW M4") is Trim.UNKNOWN


def test_parse_transmission():
    assert parse.parse_transmission("Cayman S PDK") is Transmission.PDK
    assert parse.parse_transmission("Cayman S 6-speed manual") is Transmission.MANUAL
    assert parse.parse_transmission("Cayman S") is Transmission.UNKNOWN


def test_parse_year_mileage():
    assert parse.parse_year("2015 Porsche Cayman GTS") == 2015
    assert parse.parse_year("2011 Cayman") is None  # out of 981 range
    assert parse.parse_mileage("28,400 miles") == 28400
    assert parse.parse_mileage("42k miles") == 42000


def test_parse_vin():
    assert parse.parse_vin("VIN: WP0AB2A88FK123456 clean") == "WP0AB2A88FK123456"
    assert parse.parse_vin("no vin here") is None


def test_detect_options():
    opts = parse.detect_options("Sport Chrono Package, Porsche Sport Exhaust, BOSE audio")
    assert OptionCode.SPORT_CHRONO in opts
    assert OptionCode.PSE in opts
    assert OptionCode.BOSE in opts
