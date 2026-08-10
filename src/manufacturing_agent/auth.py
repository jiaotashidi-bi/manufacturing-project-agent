from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, Header, HTTPException

from .config import AppSettings, get_settings

ROLE_ORDER = {"viewer": 0, "analyst": 1, "approver": 2, "admin": 3}


@dataclass(frozen=True)
class CurrentUser:
    subject: str
    roles: frozenset[str]
    auth_mode: str

    def has_any_role(self, allowed: set[str]) -> bool:
        return bool(self.roles & allowed)


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url)


def resolve_user(
    settings: Annotated[AppSettings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_user: Annotated[str, Header()] = "demo-user",
    x_role: Annotated[str, Header()] = "analyst",
) -> CurrentUser:
    if settings.auth_mode == "demo":
        roles = frozenset(role.strip() for role in x_role.split(",") if role.strip())
        invalid = roles - ROLE_ORDER.keys()
        if invalid:
            raise HTTPException(status_code=400, detail=f"Unknown roles: {sorted(invalid)}")
        return CurrentUser(x_user, roles or frozenset({"viewer"}), "demo")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        signing_key = _jwks_client(settings.oidc_jwks_url or "").get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            options={"require": ["exp", "iat", "sub"]},
        )
    except (jwt.PyJWTError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from exc
    raw_roles = claims.get(settings.oidc_role_claim, [])
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    roles = frozenset(str(role) for role in raw_roles if str(role) in ROLE_ORDER)
    return CurrentUser(str(claims["sub"]), roles or frozenset({"viewer"}), "oidc")


UserDependency = Annotated[CurrentUser, Depends(resolve_user)]


def require_roles(*roles: str):
    allowed = set(roles)

    def dependency(user: UserDependency) -> CurrentUser:
        if not user.has_any_role(allowed):
            raise HTTPException(status_code=403, detail=f"Requires one of roles: {sorted(allowed)}")
        return user

    return dependency
