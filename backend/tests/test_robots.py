from porsche_tracker.collectors.robots import is_allowed

UA = "porsche-tracker/0.1"

ROBOTS = """
User-agent: *
Disallow: /private/
Allow: /inventory/
"""


def test_disallowed_path_blocked():
    assert is_allowed(ROBOTS, UA, "https://dealer.example/private/secret") is False


def test_allowed_path_ok():
    assert is_allowed(ROBOTS, UA, "https://dealer.example/inventory/cayman") is True


def test_no_robots_defaults_allowed():
    assert is_allowed(None, UA, "https://dealer.example/anything") is True
