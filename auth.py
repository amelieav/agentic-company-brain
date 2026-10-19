"""Mock Microsoft Entra ID: issues and validates signed JWTs with Entra-style claims.

This is a SIMULATION for the demo. The shape matches the real thing (issuer, audience, `roles` app-role
claim, expiry, signature check on every request), so swapping in real Entra later means replacing
`issue_token` with the OIDC login flow and `verify_token` with JWKS validation; the API code is unchanged.
"""
import os
import secrets
import time
import uuid

import jwt

SECRET = os.getenv("JWT_SECRET") or secrets.token_hex(32)  # random per process unless pinned
ISSUER = "https://login.mock-entra.local/moonpool-bakehouse/v2.0"
AUDIENCE = "api://company-brain"
TOKEN_TTL_SECONDS = 60 * 60

# Entra "app roles" as they would appear in the token's `roles` claim -> our internal role.
APP_ROLE_TO_ROLE = {"Brain.Staff": "staff", "Brain.Manager": "manager", "Brain.Exec": "exec"}
ROLE_RANK = {"staff": 0, "manager": 1, "exec": 2}

DEMO_USERS = {
    "ben": {"name": "Ben Okafor", "upn": "ben.okafor@moonpool.example", "title": "Production Operator",
            "roles": ["Brain.Staff"]},
    "priya": {"name": "Priya Raman", "upn": "priya.raman@moonpool.example", "title": "Operations Manager",
              "roles": ["Brain.Manager"]},
    "alex": {"name": "Alex Whitfield", "upn": "alex.whitfield@moonpool.example", "title": "Finance Director",
             "roles": ["Brain.Exec"]},
}


class AuthError(Exception):
    pass


def issue_token(user_id: str) -> str:
    user = DEMO_USERS.get(user_id)
    if not user:
        raise AuthError("unknown demo user")
    now = int(time.time())
    claims = {
        "iss": ISSUER, "aud": AUDIENCE, "iat": now, "nbf": now, "exp": now + TOKEN_TTL_SECONDS,
        "sub": user_id, "oid": str(uuid.uuid5(uuid.NAMESPACE_DNS, user["upn"])), "jti": uuid.uuid4().hex,
        "name": user["name"], "preferred_username": user["upn"], "roles": user["roles"],
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def verify_token(token: str) -> dict:
    """Validate signature, expiry, issuer and audience. Returns the claims plus a resolved `role`."""
    try:
        claims = jwt.decode(token, SECRET, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER)
    except jwt.PyJWTError as e:
        raise AuthError(str(e)) from e
    roles = [APP_ROLE_TO_ROLE[r] for r in claims.get("roles", []) if r in APP_ROLE_TO_ROLE]
    if not roles:
        raise AuthError("token carries no Brain.* app role")
    claims["role"] = max(roles, key=ROLE_RANK.__getitem__)  # highest role wins
    return claims
