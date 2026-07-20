"""Модульные тесты безопасности: пароли, токены, ротация, очистка журнала."""
import uuid
from datetime import UTC, datetime

import pytest

from app.observability.logging import redact
from app.security.passwords import hash_password, needs_rehash, validate_policy, verify_password
from app.security.rate_limit import check_and_count, reset
from app.security.tokens import (
    create_access_token,
    decode_access_token,
    hash_refresh_token,
    new_refresh_token,
)


def test_password_hash_is_argon2id_and_salted():
    first, second = hash_password("Sicher12345678"), hash_password("Sicher12345678")
    assert first.startswith("$argon2id$")
    assert first != second, "одинаковые пароли должны давать разные хеши (соль)"


def test_password_verification():
    stored = hash_password("Sicher12345678")
    assert verify_password(stored, "Sicher12345678") is True
    assert verify_password(stored, "Sicher12345679") is False
    assert verify_password(None, "любой") is False
    assert verify_password("не-хеш", "любой") is False


def test_password_needs_rehash_is_false_for_current_parameters():
    assert needs_rehash(hash_password("Sicher12345678")) is False


@pytest.mark.parametrize("password,expected_problems", [
    ("short1", 1), ("nodigitspassword", 1), ("123456789012", 1), ("Sicher12345678", 0)])
def test_password_policy(password, expected_problems):
    assert len(validate_policy(password)) == expected_problems


def test_access_token_roundtrip():
    user_id, company_id, session_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token, ttl = create_access_token(user_id, company_id, "admin", session_id)
    claims = decode_access_token(token)
    assert claims is not None
    assert claims.user_id == user_id and claims.company_id == company_id
    assert claims.role == "admin" and claims.session_id == session_id
    assert 0 < ttl <= 900
    assert claims.expires_at > datetime.now(UTC)


def test_tampered_token_rejected():
    token, _ = create_access_token(uuid.uuid4(), uuid.uuid4(), "worker", uuid.uuid4())
    head, payload, sig = token.split(".")
    assert decode_access_token(f"{head}.{payload}.{sig[:-2]}xy") is None
    assert decode_access_token("мусор") is None
    assert decode_access_token("") is None


def test_expired_token_rejected(monkeypatch):
    import app.security.tokens as tokens
    monkeypatch.setattr(tokens.settings, "access_ttl_seconds", -10)
    token, _ = tokens.create_access_token(uuid.uuid4(), uuid.uuid4(), "worker", uuid.uuid4())
    assert tokens.decode_access_token(token) is None


def test_refresh_token_stored_only_as_hash():
    raw, stored = new_refresh_token()
    assert raw != stored
    assert len(stored) == 64 and stored == hash_refresh_token(raw)
    assert raw not in stored


def test_refresh_rotation_produces_new_value():
    first_raw, first_hash = new_refresh_token()
    second_raw, second_hash = new_refresh_token()
    assert first_raw != second_raw and first_hash != second_hash


def test_audit_payload_sanitization():
    payload = {"email": "a@b.de", "password": "секрет", "refresh_token": "rt",
               "access_token": "at", "nested": {"pin": "1234", "role": "admin"}}
    cleaned = redact(payload)
    assert cleaned == {"email": "a@b.de", "nested": {"role": "admin"}}
    assert "секрет" not in str(cleaned)


def test_rate_limit_window():
    reset("тест")
    assert all(check_and_count("тест", limit=3, window_seconds=60) for _ in range(3))
    assert check_and_count("тест", limit=3, window_seconds=60) is False
    reset("тест")
    assert check_and_count("тест", limit=3, window_seconds=60) is True
