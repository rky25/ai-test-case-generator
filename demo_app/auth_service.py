"""
Authentication and security service for the demo application.
Demonstrates security edge cases, regex checks, and User model resolution.
"""

import hashlib
import re
from typing import Optional
from models import User


def validate_password_strength(password: str) -> bool:
    """
    Validate that password meets enterprise security standards:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special symbol (!@#$%^&*()-_=+[]{}|;:,.<>?)
    """
    if not password or len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    if not re.search(r"[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]", password):
        return False
    return True


def hash_password(password: str, salt: str = "enterprise_salt_2026") -> str:
    """Hash password using SHA-256 with salt."""
    if not password:
        raise ValueError("Password cannot be empty")
    combined = f"{salt}:{password}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def authenticate_user(users_db: dict, email: str, raw_password: str) -> Optional[User]:
    """
    Authenticate a user against the user dictionary database.

    Args:
        users_db: Mapping of email -> dict(user=User, hash=str)
        email: User email address
        raw_password: Raw plaintext password

    Returns:
        User object if authentication succeeds, None otherwise.

    Raises:
        ValueError: If email is invalid or empty.
    """
    if not email or "@" not in email:
        raise ValueError("Invalid email format")

    clean_email = email.strip().lower()
    record = users_db.get(clean_email)
    if not record:
        return None

    user: User = record["user"]
    if not user.is_active:
        return None

    expected_hash = record["hash"]
    given_hash = hash_password(raw_password)

    if given_hash == expected_hash:
        return user
    return None
