"""
Cryptographic Utilities: 6-Digit Pairing, Auth Tokens, and Dashboard Passwords
Uses Python's standard library (hashlib, hmac, secrets) for zero-dependency security.
"""

import hashlib
import hmac
import secrets
import time
from typing import Optional, Tuple

def generate_pairing_code() -> str:
    """Generates a random 6-digit numeric pairing code (e.g. '048291')."""
    return f"{secrets.randbelow(1000000):06d}"

def generate_device_token() -> str:
    """Generates a cryptographically secure 256-bit hexadecimal authentication token."""
    return secrets.token_hex(32)

def hash_password(password: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
    """
    Hashes a password using PBKDF2-HMAC-SHA256 (100,000 iterations).
    Returns (salt_hex, hash_hex).
    """
    if salt is None:
        salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex(), hashed.hex()

def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    """Verifies a password against the stored salt and hash."""
    try:
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)
        actual_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return hmac.compare_digest(expected_hash, actual_hash)
    except Exception:
        return False

def generate_session_token() -> str:
    """Generates a secure web dashboard session token."""
    return secrets.token_urlsafe(32)
