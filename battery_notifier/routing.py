# battery_notifier/routing.py
"""Alert routing: where does an alarm actually make noise?

Routes (per event type, stored in config):
  "both"               -- ring on this laptop AND notify the relay (phone)
  "phone"              -- notify the relay only; this laptop stays silent
  "laptop"             -- ring here only; nothing crosses the relay
  "phone_then_laptop"  -- the phone rings now; this laptop escalates after
                          escalate_minutes if the alert is still active

The phone is always the first responder for its own events (it rings
locally and sends) -- routing governs the LAPTOP side and what crosses
the relay. Pure functions so the tests can drive every decision.
"""
from __future__ import annotations

ROUTES = ("both", "phone", "laptop", "phone_then_laptop")


def normalize_route(route: str | None, default: str = "both") -> str:
    r = (route or "").strip().lower()
    return r if r in ROUTES else default


def wants_local(route: str | None, default: str = "both") -> bool:
    """Should THIS laptop play the sound? phone_then_laptop counts: it rings
    after escalate_minutes (siren_due gates the timing)."""
    r = normalize_route(route, default)
    return r in ("both", "laptop", "phone_then_laptop")


def wants_relay(route: str | None, default: str = "both") -> bool:
    """Should this event cross the relay (reach the phone)?"""
    r = normalize_route(route, default)
    return r in ("both", "phone", "phone_then_laptop")


def escalates(route: str | None, default: str = "both") -> bool:
    """Phone-first mode: the laptop holds its siren for escalate_minutes."""
    return normalize_route(route, default) == "phone_then_laptop"


def siren_due(elapsed_seconds: float, escalate_minutes: int, route: str | None,
              default: str = "both") -> bool:
    """Episode logic for the laptop's relay listener: with escalation, the
    siren only starts after escalate_minutes of a STILL-ACTIVE alert."""
    if not wants_local(route, default):
        return False
    if not escalates(route, default):
        return True
    return elapsed_seconds >= max(0, int(escalate_minutes)) * 60
