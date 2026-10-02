from __future__ import annotations

import hashlib
import secrets
import bcrypt
import datetime
import jwt
from jwt import InvalidTokenError


def hash_password(password: str) -> bytes:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("password must be between 12 and 128 characters")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))


def verify_password(password: str, password_hash: bytes) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode() if isinstance(password_hash, str) else password_hash)
    except (ValueError, TypeError):
        return False


def create_token(user_id: str, secret: str, lifetime_seconds: int) -> str:
    if len(secret) < 32:
        raise ValueError("JWT_SECRET must contain at least 32 characters")
    return jwt.encode(
        {"sub": user_id, "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=lifetime_seconds)},
        secret,
        algorithm="HS256",
    )


def verify_token(token: str, secret: str) -> str | None:
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"])
        subject = data.get("sub")
        return subject if isinstance(subject, str) and subject else None
    except (InvalidTokenError, TypeError, ValueError):
        return None


def new_invitation_code() -> str:
    return secrets.token_urlsafe(32)


def hash_invitation(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()