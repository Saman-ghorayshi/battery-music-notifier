# tests/test_routing.py
"""The routing decision table: every route x question, no surprises."""
from battery_notifier.routing import (
    normalize_route, wants_local, wants_relay, escalates, siren_due, ROUTES,
)


def test_normalize_known_and_unknown():
    assert normalize_route("both") == "both"
    assert normalize_route("PHONE") == "phone"
    assert normalize_route("garbage") == "both"
    assert normalize_route(None, "laptop") == "laptop"
    assert set(ROUTES) == {"both", "phone", "laptop", "phone_then_laptop"}


def test_both_rings_everywhere():
    assert wants_local("both") and wants_relay("both")


def test_phone_only_is_silent_on_the_laptop():
    assert not wants_local("phone")
    assert wants_relay("phone")


def test_laptop_only_never_crosses_the_relay():
    assert wants_local("laptop")
    assert not wants_relay("laptop")


def test_phone_then_laptop_esculates():
    assert wants_relay("phone_then_laptop")
    assert escalates("phone_then_laptop")
    # fresh alert: the laptop holds its siren while the phone gets its chance
    assert not siren_due(0, 2, "phone_then_laptop")
    assert not siren_due(60, 2, "phone_then_laptop")
    # 2 minutes in, still active -> the laptop joins
    assert siren_due(121, 2, "phone_then_laptop")
    # zero escalation = immediate
    assert siren_due(0, 0, "phone_then_laptop")


def test_non_escalating_routes_ring_immediately():
    for route in ("both", "laptop"):
        assert siren_due(0, 2, route)
    assert not siren_due(0, 2, "phone")
