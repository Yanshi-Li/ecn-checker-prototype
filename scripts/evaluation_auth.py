"""Authentication and authorization primitives for the local reviewer area."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Mapping


ROLES = frozenset({"TESTER", "REVIEWER", "ADMINISTRATOR"})


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Return a portable PBKDF2 password record; never store plaintext passwords."""
    if not password:
        raise ValueError("password must not be empty")
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 300_000)
    return "pbkdf2_sha256$300000${}${}".format(
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password record using a constant-time digest comparison."""
    try:
        algorithm, iterations, salt_value, digest_value = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode())
        expected = base64.urlsafe_b64decode(digest_value.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def normalise_role(role: object) -> str:
    value = str(role or "").strip().upper()
    if value not in ROLES:
        raise ValueError("role must be TESTER, REVIEWER, or ADMINISTRATOR")
    return value


def can_review(role: object) -> bool:
    return normalise_role(role) in {"REVIEWER", "ADMINISTRATOR"}


def can_administer(role: object) -> bool:
    return normalise_role(role) == "ADMINISTRATOR"


def can_access_attempt(role: object, *, assigned: bool = False) -> bool:
    value = normalise_role(role)
    return value == "ADMINISTRATOR" or (value == "REVIEWER" and assigned)
