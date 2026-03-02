import base64
import json

import pytest

import real_scanner


def _payload_token(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{encoded}.ignored.signature"


def test_base64url_decode_roundtrip():
    encoded = base64.urlsafe_b64encode(b"hello").decode("ascii").rstrip("=")

    assert real_scanner.base64url_decode(encoded) == b"hello"


def test_extract_payload_b64_returns_first_segment():
    assert real_scanner.extract_payload_b64("  payload.header.signature ") == "payload"


def test_parse_dokume_qr_valid():
    token = _payload_token(
        {"FN": "Ada", "LN": "Lovelace", "DOB": "1815-12-10", "exp": 1700000000}
    )

    assert real_scanner.parse_dokume_qr(token) == {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "birth_year": 1815,
        "exp_timestamp": 1700000000,
    }


def test_parse_dokume_qr_missing_fields_raises():
    token = _payload_token({"FN": "Ada", "DOB": "1815-12-10", "exp": 1700000000})

    with pytest.raises(ValueError, match="missing fields"):
        real_scanner.parse_dokume_qr(token)
