"""Signed inter-service tokens for master <-> node communication."""

import hashlib
import secrets

from django.conf import settings
from django.core import signing


def sign_token(payload: dict) -> str:
    """Sign a payload dict with CLUSTER_SECRET. Returns a signed token string."""
    return signing.dumps(payload, key=settings.CLUSTER_SECRET)


def verify_token(token_str: str, expected_role: str, max_age: int = 60) -> dict | None:
    """Verify a signed token. Returns payload if valid, None otherwise."""
    try:
        payload = signing.loads(token_str, key=settings.CLUSTER_SECRET, max_age=max_age)
    except (signing.SignatureExpired, signing.BadSignature):
        return None
    if payload.get("role") != expected_role:
        return None
    return payload


def make_master_token() -> str:
    """Create a token for master -> node requests."""
    return sign_token({"role": "master", "name": "master"})


def make_node_token(node_name: str) -> str:
    """Create a token for node -> master heartbeats."""
    return sign_token({"role": "node", "name": node_name})


def make_enrollment_token() -> str:
    """Create a random one-time enrollment token."""
    return secrets.token_urlsafe(32)


def hash_enrollment_token(token: str) -> str:
    """Hash an enrollment token before storing it."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def make_node_credential() -> str:
    """Create a random long-lived credential for one storage node."""
    return secrets.token_urlsafe(32)


def hash_node_credential(credential: str) -> str:
    """Hash a node credential before storing it."""
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()