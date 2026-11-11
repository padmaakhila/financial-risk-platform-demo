import time

import jwt
import pytest

from backend.core.config import get_settings
from backend.core.security import (TokenError, create_access_token, decode_access_token, hash_password,
                                   verify_password)


def test_password_hash_and_verify():
    h = hash_password("Correct#Horse1")
    assert h.startswith("scrypt$") and "Correct" not in h
    assert verify_password("Correct#Horse1", h)
    assert not verify_password("wrong-password", h)
    assert hash_password("Correct#Horse1") != h  # unique salt


def test_short_password_rejected_and_garbage_hash_safe():
    with pytest.raises(ValueError):
        hash_password("short")
    assert verify_password("anything", "not-a-hash") is False


def test_token_roundtrip():
    claims = decode_access_token(create_access_token(7, "alice", "reviewer"))
    assert claims["sub"] == "7" and claims["role"] == "reviewer" and claims["username"] == "alice"


def test_expired_token_rejected():
    token = create_access_token(1, "a", "admin", minutes=-1)
    with pytest.raises(TokenError):
        decode_access_token(token)


def test_tampered_and_wrongly_signed_tokens_rejected():
    s = get_settings()
    forged = jwt.encode({"sub": "1", "role": "admin", "exp": time.time() + 600}, "another-secret-another-secret-12345", algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(forged)
    good = create_access_token(2, "b", "ap_clerk")
    with pytest.raises(TokenError):
        decode_access_token(good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB"))
    none_alg = jwt.encode({"sub": "1", "role": "admin", "exp": time.time() + 600}, key="", algorithm="none")
    with pytest.raises(TokenError):
        decode_access_token(none_alg)
    assert s.jwt_algorithm == "HS256"
