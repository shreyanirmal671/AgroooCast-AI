from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend_database import User, get_user_by_username


SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_REFRESH_EXPIRE_MINUTES", "10080"))


def create_access_token(payload: dict, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    to_encode = payload.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(payload: dict, expires_minutes: int = REFRESH_TOKEN_EXPIRE_MINUTES) -> str:
    to_encode = payload.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def get_bearer_token(auth_header: str) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def get_current_user(db: Session, token: str | None, expect_refresh: bool = False) -> tuple[User | None, str | None]:
    if not token:
        return None, "Missing bearer token"

    try:
        payload = decode_token(token)

        token_type = payload.get("type")
        if expect_refresh and token_type != "refresh":
            return None, "Invalid refresh token"
        if not expect_refresh and token_type == "refresh":
            return None, "Access token required"

        username = payload.get("sub")
        if not username:
            return None, "Invalid or expired token"
    except JWTError:
        return None, "Invalid or expired token"

    user = get_user_by_username(db, username)
    if not user:
        return None, "Invalid or expired token"
    return user, None


def require_roles(db: Session, token: str | None, allowed_roles: set[str]) -> tuple[User | None, str | None]:
    user, error = get_current_user(db, token)
    if error:
        return None, error

    if user is None or user.role not in allowed_roles:
        return None, "Insufficient role permissions"

    return user, None
