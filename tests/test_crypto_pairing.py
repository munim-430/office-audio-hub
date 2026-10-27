"""
Unit Tests for Cryptographic Pairing, Hashing, and Tokens
"""

from common.crypto import (
    generate_pairing_code,
    generate_device_token,
    hash_password,
    verify_password,
    generate_session_token
)

def test_pairing_code_format():
    for _ in range(50):
        code = generate_pairing_code()
        assert len(code) == 6
        assert code.isdigit()

def test_device_token_entropy():
    tokens = {generate_device_token() for _ in range(100)}
    assert len(tokens) == 100
    for tok in tokens:
        assert len(tok) == 64  # 32 bytes hex

def test_password_hashing_and_verification():
    password = "SuperSecretManagerPassword2026!"
    salt, hashed = hash_password(password)

    assert verify_password(password, salt, hashed) is True
    assert verify_password("WrongPassword", salt, hashed) is False
    assert verify_password("", salt, hashed) is False

def test_session_token_entropy():
    s1 = generate_session_token()
    s2 = generate_session_token()
    assert s1 != s2
    assert len(s1) > 20
