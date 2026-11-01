"""A connection's own secret: a Databricks personal access token, kept encrypted in its connection_config.

Each Databricks connection can carry its own token, so two workspaces with different credentials sit side by side.
The token is sealed with a key derived from SECRET_KEY: a database dump never holds a usable token, and changing
SECRET_KEY makes stored tokens unreadable (enter them again). It is never sent back by the API; a response only says
that one is set. A connection without its own token uses DATABRICKS_TOKEN from the server's configuration.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from kairos_kb.config import get_settings
from kairos_kb.exceptions import KairosException

logger = logging.getLogger(__name__)

SEALED = "token_encrypted"
DEFAULT_SECRET = "change-me-in-production"


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"kairos-connection-token:{get_settings().secret_key}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(config: Optional[Dict[str, Any]], token: str) -> Dict[str, Any]:
    """config with this token sealed into it (a blank token leaves config as it is)."""
    out = {k: v for k, v in (config or {}).items() if k != SEALED}
    token = (token or "").strip()
    if not token:
        return out
    s = get_settings()
    if s.secret_key == DEFAULT_SECRET and s.app_env == "production":
        raise KairosException("Set SECRET_KEY on the server before storing a connection's token.", status_code=400)
    out[SEALED] = _fernet().encrypt(token.encode()).decode()
    return out


def token_of(config: Optional[Dict[str, Any]]) -> Optional[str]:
    """The connection's own token, or None (none stored, or sealed under a different SECRET_KEY)."""
    sealed = (config or {}).get(SEALED)
    if not sealed:
        return None
    try:
        return _fernet().decrypt(str(sealed).encode()).decode()
    except InvalidToken:
        logger.warning("A connection's stored token can't be read (SECRET_KEY changed?); enter it again.")
        return None


def public(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """config as the API shows it: the sealed token replaced by has_token."""
    out = {k: v for k, v in (config or {}).items() if k != SEALED}
    if (config or {}).get(SEALED):
        out["has_token"] = True
    return out
