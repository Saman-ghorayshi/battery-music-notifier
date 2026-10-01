# tests/test_redact.py
"""Redaction engine golden tests: real-world fa/en OTP formats, cards,
national IDs, token URLs. This module guards the promise 'bank codes never
leave the device -- even the AI sees holes'."""
import pytest
from battery_notifier.redact import redact


def test_otp_code_with_english_keyword():
    r = redact("Your verification code is 483921. Do not share it.")
    assert "483921" not in r["safe_text"]
    assert "•" in r["safe_text"]
    assert any(x["kind"] == "otp" for x in r["redactions"])


def test_otp_code_with_persian_keyword():
    r = redact("کد ورود شما: 55123")
    assert "55123" not in r["safe_text"]
    assert any(x["kind"] == "otp" for x in r["redactions"])


def test_bank_otp_tan_code():
    r = redact("TAN: 738291 for transfer 5,000,000 IRR")
    assert "738291" not in r["safe_text"]


def test_otp_without_keyword_is_kept():
    # "483921" with no keyword nearby is data, not an OTP -- must survive
    r = redact("Order 483921 shipped yesterday.")
    assert "483921" in r["safe_text"]
    assert not any(x["kind"] == "otp" for x in r["redactions"])


def test_bank_card_masked_to_last4():
    r = redact("Card 6037-9912-3456-7890 charged.")
    assert "6037" not in r["safe_text"].split("Card")[-1].split("charged")[0]
    assert "•••• •••• •••• 7890" in r["safe_text"]
    assert any(x["kind"] == "card" for x in r["redactions"])


def test_valid_national_id_masked():
    # 1234567891 passes the mod-11 checksum
    r = redact("National ID: 1234567891 registered.")
    assert "1234567891" not in r["safe_text"]
    assert any(x["kind"] == "national_id" for x in r["redactions"])


def test_random_10_digit_not_national_id_survives():
    # 1234567890 fails the mod-11 checksum -- must NOT be treated as an ID
    r = redact("Serial 1234567890 confirmed.")
    assert "1234567890" in r["safe_text"]


def test_otpauth_seed_removed_entirely():
    r = redact("scan this: otpauth://totp/Example?secret=JBSWY3DPEHPK3PXP")
    assert "JBSWY3DPEHPK3PXP" not in r["safe_text"]
    assert any(x["kind"] == "otpauth_seed" for x in r["redactions"])


def test_token_url_query_stripped():
    r = redact("Login: https://example.com/verify?token=abc123def&user=1")
    assert "abc123def" not in r["safe_text"]
    assert any(x["kind"] == "token_url" for x in r["redactions"])


def test_clean_message_untouched():
    msg = "سلام، فردا ساعت ۸ بیای دفتر. Bring the docs."
    r = redact(msg)
    assert r["safe_text"] == msg
    assert r["redactions"] == []


def test_empty_and_none_safe():
    assert redact("")["safe_text"] == ""
    assert redact(None)["safe_text"] is None
