import base64
import json

import pytest

import qr


def _b64url(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _make_dokume_url(payload: dict) -> str:
    token = f"{_b64url({'alg': 'none'})}.{_b64url(payload)}.sig"
    return f"https://qr.dokume.net?d=l&i=abc&s={token}"


def test_base64url_decode_roundtrip():
    txt = b"hello"
    enc = base64.urlsafe_b64encode(txt).decode("ascii").rstrip("=")
    assert qr.base64url_decode(enc) == txt


def test_is_dokume_url():
    assert qr.is_dokume_url("https://qr.dokume.net?x=1") is True
    assert qr.is_dokume_url("http://qr.dokume.net?x=1") is True
    assert qr.is_dokume_url("https://example.com") is False


def test_parse_dokume_qr_valid():
    url = _make_dokume_url({"FN": "Ada", "LN": "Lovelace", "DOB": "10.12.1815", "exp": 1700000000})
    out = qr.parse_dokume_qr(url)

    assert out["first_name"] == "Ada"
    assert out["last_name"] == "Lovelace"
    assert out["birth_date"] == "10.12.1815"
    assert out["exp_timestamp"] == 1700000000


def test_parse_dokume_qr_missing_s_raises():
    with pytest.raises(ValueError, match="s"):
        qr.parse_dokume_qr("https://qr.dokume.net?x=1")


def test_parse_dokume_qr_invalid_jwt_raises():
    with pytest.raises(ValueError, match="JWT"):
        qr.parse_dokume_qr("https://qr.dokume.net?s=abc.def")


def test_parse_dokume_qr_missing_exp_raises():
    url = _make_dokume_url({"FN": "Ada"})
    with pytest.raises(ValueError, match="exp"):
        qr.parse_dokume_qr(url)


def test_is_valid_boundary(monkeypatch):
    monkeypatch.setattr(qr.time, "time", lambda: 1000)
    assert qr.is_valid(1000) is True
    assert qr.is_valid(999) is False
