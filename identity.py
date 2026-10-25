"""Identity and role-based access control (Phase 1.2). No Streamlit imports.

Identity sources, in order:
1. Azure App Service Easy Auth headers (``X-Ms-Client-Principal-*``), trusted only when the app runs
   behind Easy Auth (``WEBSITE_AUTH_ENABLED=True``) or ``TRUST_AUTH_HEADERS=1`` is set explicitly.
2. A local-development fallback: ``ALLOWED_EMAILS`` (comma separated) plus ``DEV_USER_EMAIL``, which
   must be on that list.

Roles: viewer, reviewer (publish rules), official (approve or hold), admin (uploads, scope toggle, and
everything else). The audit actor is always the verified identity, never typed text.
"""
from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

ROLES: tuple[str, ...] = ("viewer", "reviewer", "official", "admin")

PERMISSIONS: dict[str, frozenset[str]] = {
    "view": frozenset(ROLES),
    "publish_rules": frozenset({"reviewer", "admin"}),
    "decide": frozenset({"official", "admin"}),
    "upload_data": frozenset({"admin"}),
    "toggle_scope": frozenset({"admin"}),
    "confirm_verified_data": frozenset({"admin"}),
    "edit_facts": frozenset({"reviewer", "official", "admin"}),
    "refresh_funding": frozenset({"reviewer", "official", "admin"}),
    "run_tamper_demo": frozenset({"admin"}),
}

_ROLE_CLAIMS = ("roles", "role", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role")
_EMAIL_CLAIMS = ("preferred_username", "email", "emails",
                 "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress", "upn")
_NAME_CLAIMS = ("name", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name")


@dataclass(frozen=True)
class Identity:
    """A verified user. ``source`` is ``easy_auth`` or ``dev``."""

    email: str
    name: str
    idp: str
    roles: frozenset[str] = field(default_factory=lambda: frozenset({"viewer"}))
    source: str = "easy_auth"

    @property
    def actor(self) -> str:
        """Audit actor string, always derived from the verified identity."""
        return f"user:{self.email}"


def _csv(value: str | None) -> set[str]:
    return {v.strip().lower() for v in (value or "").split(",") if v.strip()}


def _header(headers: Mapping[str, str], name: str) -> str:
    lname = name.lower()
    for key, value in headers.items():
        if key.lower() == lname:
            return str(value)
    return ""


def _decode_principal(blob: str) -> dict[str, object]:
    """Decode the base64 ``X-Ms-Client-Principal`` JSON; returns ``{}`` for anything malformed."""
    if not blob:
        return {}
    try:
        padded = blob + "=" * (-len(blob) % 4)
        data = json.loads(base64.b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _claim_values(principal: dict[str, object], names: tuple[str, ...]) -> list[str]:
    claims = principal.get("claims")
    out: list[str] = []
    if isinstance(claims, list):
        for c in claims:
            if isinstance(c, dict) and str(c.get("typ", "")).lower() in {n.lower() for n in names}:
                out.append(str(c.get("val", "")))
    return out


def roles_for(email: str, token_roles: list[str], env: Mapping[str, str]) -> frozenset[str]:
    """Combine app-role claims from the token with env lists ``ROLE_ADMINS``, ``ROLE_OFFICIALS``, ``ROLE_REVIEWERS``."""
    roles = {"viewer"}
    roles.update(r.strip().lower() for r in token_roles if r.strip().lower() in ROLES)
    mail = email.lower()
    for role, var in (("admin", "ROLE_ADMINS"), ("official", "ROLE_OFFICIALS"), ("reviewer", "ROLE_REVIEWERS")):
        if mail in _csv(env.get(var)):
            roles.add(role)
    return frozenset(roles)


def _trust_headers(env: Mapping[str, str]) -> bool:
    return env.get("WEBSITE_AUTH_ENABLED", "").lower() == "true" or env.get("TRUST_AUTH_HEADERS", "") == "1"


def parse_easy_auth(headers: Mapping[str, str], env: Mapping[str, str] | None = None) -> Identity | None:
    """Parse App Service Easy Auth headers into an :class:`Identity`, or ``None`` when absent or untrusted."""
    env = os.environ if env is None else env
    if not _trust_headers(env):
        return None
    principal = _decode_principal(_header(headers, "X-Ms-Client-Principal"))
    email = _header(headers, "X-Ms-Client-Principal-Name").strip()
    if not email:
        found = _claim_values(principal, _EMAIL_CLAIMS)
        email = found[0].strip() if found else ""
    if not email:
        return None
    idp = _header(headers, "X-Ms-Client-Principal-Idp").strip() or str(principal.get("auth_typ", "")) or "unknown"
    names = _claim_values(principal, _NAME_CLAIMS)
    return Identity(email=email, name=names[0] if names else email, idp=idp,
                    roles=roles_for(email, _claim_values(principal, _ROLE_CLAIMS), env), source="easy_auth")


def dev_identity(env: Mapping[str, str] | None = None) -> Identity | None:
    """Local-development fallback: ``DEV_USER_EMAIL`` accepted only when it is listed in ``ALLOWED_EMAILS``."""
    env = os.environ if env is None else env
    allowed = _csv(env.get("ALLOWED_EMAILS"))
    email = env.get("DEV_USER_EMAIL", "").strip()
    if not allowed or not email or email.lower() not in allowed:
        return None
    return Identity(email=email, name=email, idp="local-dev", roles=roles_for(email, [], env), source="dev")


def resolve_identity(headers: Mapping[str, str], env: Mapping[str, str] | None = None) -> Identity | None:
    """Easy Auth first, then the local-dev fallback. ``None`` means an anonymous public visitor."""
    env = os.environ if env is None else env
    return parse_easy_auth(headers, env) or dev_identity(env)


def can(identity: Identity | None, permission: str) -> bool:
    """True when ``identity`` holds a role allowed for ``permission``. Anonymous users may only ``view``."""
    allowed = PERMISSIONS.get(permission)
    if allowed is None:
        return False
    if identity is None:
        return permission == "view"
    return "admin" in identity.roles or bool(identity.roles & allowed)


def require(identity: Identity | None, permission: str) -> Identity:
    """Return the identity or raise ``PermissionError`` when it lacks ``permission``."""
    if identity is None or not can(identity, permission):
        raise PermissionError(f"Permission '{permission}' is required.")
    return identity
