# battery_notifier/redact.py
"""OTP/PII redaction engine -- the innermost filter.

Runs BEFORE anything leaves the device: before the AI digest, before any
relay transit, before logging. The user's own screen still shows the real
text -- redaction governs what is transmitted or summarized.

Selling line that depends on this module: "Bank codes never leave your
device -- even the AI sees holes."
"""
from __future__ import annotations
import re

# keyword triggers within a window around a candidate numeric token
_CODE_KEYWORDS = re.compile(
    r"(?:code|otp|verify|verification|pin|passcode|token|tan|"
    r"کد|رمز|تایید|اعتبارسنجی|ورود)",
    re.I,
)
_CODE_TOKEN = re.compile(r"\b\d{4,8}\b")

# structured PII
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_NATIONAL_ID = re.compile(r"\b\d{10}\b")
_TOKEN_URL = re.compile(r"(https?://\S+?(?:token|auth|key|sess)[^=\s]*=)[^\s&]+", re.I)
_OTPAUTH = re.compile(r"otpauth://\S+")

# keyword window: chars before/after a candidate token to look for a keyword
_WINDOW = 48


def _is_national_id(candidate: str) -> bool:
    """Iranian national ID checksum (mod-11, standard algorithm)."""
    if len(candidate) != 10:
        return False
    digits = [int(c) for c in candidate]
    check = digits[9]
    total = sum((10 - i) * d for i, d in enumerate(digits[:9]) if i < 9) - sum(
        (10 - i) * d for i, d in list(enumerate(digits[:9]))[9:]
    )
    # standard: sum_{i=0..8} (10-i)*d_i, then r = sum % 11
    s = sum((10 - i) * d for i, d in enumerate(digits[:9]))
    r = s % 11
    return (r < 2 and check == r) or (r >= 2 and check == 11 - r)


def _masked_card(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    return "•••• •••• •••• " + digits[-4:] if len(digits) >= 4 else "••••"


def redact(text: str) -> dict:
    """Return {"safe_text": str, "redactions": [{"kind","at"}]}.

    safe_text is the input with sensitive tokens replaced. Redactions list
    the kinds and offsets (in safe_text) so the AI layer can cite holes.
    """
    if not text:
        return {"safe_text": text, "redactions": []}
    out = text
    redactions: list[dict] = []

    # 1) otpauth:// seeds: remove whole lines entirely
    def _strip_otpauth(m: re.Match) -> str:
        redactions.append({"kind": "otpauth_seed", "at": m.start()})
        return "[redacted seed]"
    out = _OTPAUTH.sub(_strip_otpauth, out)

    # 2) URLs carrying tokens/auth params: strip the query value
    def _strip_token_url(m: re.Match) -> str:
        redactions.append({"kind": "token_url", "at": m.start()})
        return m.group(1) + "[redacted]"
    out = _TOKEN_URL.sub(_strip_token_url, out)

    # 3) bank card numbers (13-19 digits with separators) -> last 4
    def _mask_card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if not (13 <= len(digits) <= 19):
            return m.group(0)
        redactions.append({"kind": "card", "at": m.start()})
        return "•••• •••• •••• " + digits[-4:]
    out = _CARD.sub(_mask_card, out)

    # 4) OTP/verification codes: a numeric token NEAR a keyword
    def _mask_code(m: re.Match) -> str:
        start, end = m.span()
        window = out[max(0, start - _WINDOW): min(len(out), end + _WINDOW)]
        if _CODE_KEYWORDS.search(window):
            redactions.append({"kind": "otp", "at": start})
            return "•" * len(m.group(0))
        return m.group(0)
    out = _CODE_TOKEN.sub(_mask_code, out)

    # 5) national IDs (checksum-validated) -> first 3 visible
    def _mask_nid(m: re.Match) -> str:
        cand = m.group(0)
        if _is_national_id(cand):
            redactions.append({"kind": "national_id", "at": m.start()})
            return cand[:3] + "•••••••"
        return cand
    out = _NATIONAL_ID.sub(_mask_nid, out)

    return {"safe_text": out, "redactions": redactions}
