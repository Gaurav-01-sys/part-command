"""
utils/euler_oauth.py
---------------------
Implements the full OAuth 2.1 + PKCE + Dynamic Client Registration (DCR)
flow for https://mcp.eulerapp.com/mcp.

Key features
------------
- **DCR** : registers a new client on first use via POST /oauth/register
- **PKCE** : generates code_verifier (128 chars, URL-safe random) and
             code_challenge (S256 = BASE64URL(SHA256(verifier)))
- **Auth URL** : builds the authorization redirect for the user's browser
- **Token exchange** : exchanges the authorization code for
                       (access_token, refresh_token, expires_in)
- **Token refresh** : silently refreshes the access token using the
                      refresh_token before it expires
- **Encrypted file persistence** : optionally persists tokens to a JSON
  file so users do not need to re-authorize after a restart. The file is
  XOR-obfuscated with a key derived from a machine-local secret.

No third-party dependencies beyond what the project already uses
(stdlib urllib + json).  httpx is already a transitive dep of `anthropic`
but is not required here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── EULER OAuth 2.1 endpoints ─────────────────────────────────────────────────
ISSUER            = "https://mcp.eulerapp.com"
AUTHORIZATION_URL = "https://mcp.eulerapp.com/oauth/authorize"
TOKEN_URL         = "https://mcp.eulerapp.com/oauth/token"
REGISTRATION_URL  = "https://mcp.eulerapp.com/oauth/register"

DEFAULT_SCOPES     = "customer partner"
REFRESH_BUFFER_SECS = 300   # refresh 5 min before actual expiry


# ── Token dataclass ───────────────────────────────────────────────────────────

@dataclass
class TokenSet:
    access_token:  str
    refresh_token: str  = ""
    expires_at:    float = 0.0
    client_id:     str  = ""
    client_secret: str  = ""
    token_type:    str  = "Bearer"

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return time.time() >= (self.expires_at - REFRESH_BUFFER_SECS)

    def preview(self) -> str:
        t = self.access_token
        if len(t) <= 8:
            return "****"
        return t[:4] + "..." + t[-4:]


# ── In-process singleton ──────────────────────────────────────────────────────

_token_set: Optional[TokenSet] = None
_pending:   dict               = {}


# def get_token_set() -> Optional[TokenSet]:
#     global _token_set
#     if _token_set and _token_set.is_expired() and _token_set.refresh_token:
#         try:
#             _token_set = _do_refresh(_token_set)
#             _persist(_token_set)
#             log.info("EULER token silently refreshed.")
#         except Exception as exc:
#             log.warning("EULER silent token refresh failed: %s", exc)
#     return _token_set

def get_token_set() -> Optional[TokenSet]:
    global _token_set
    if _token_set is None:
        _token_set = load_persisted()
    if _token_set and _token_set.is_expired() and _token_set.refresh_token:
        try:
            _token_set = _do_refresh(_token_set)
            _persist(_token_set)
        except Exception as exc:
            log.warning("EULER silent token refresh failed: %s", exc)
    return _token_set


def set_token_set(ts: TokenSet) -> None:
    global _token_set
    _token_set = ts
    _persist(ts)


def clear_token_set() -> None:
    global _token_set, _pending
    _token_set = None
    _pending   = {}
    _delete_persisted()


def is_connected() -> bool:
    ts = get_token_set()
    return ts is not None and bool(ts.access_token)


# ── PKCE ──────────────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    verifier  = secrets.token_urlsafe(96)
    digest    = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _generate_state() -> str:
    return secrets.token_urlsafe(32)


# ── Dynamic Client Registration ───────────────────────────────────────────────

def _register_client(redirect_uri: str) -> tuple[str, str]:
    payload = json.dumps({
        "client_name":    "Partner Management Command Center",
        "redirect_uris":  [redirect_uri],
        "grant_types":    ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
        "scope": DEFAULT_SCOPES,
    }).encode()

    req = urllib.request.Request(
        REGISTRATION_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        raise RuntimeError(
            f"DCR failed HTTP {exc.code}: {body.decode(errors='replace')}"
        ) from exc

    client_id     = data["client_id"]
    client_secret = data.get("client_secret", "")
    log.info("EULER DCR: registered client_id=%s", client_id)
    return client_id, client_secret


# ── Authorization URL ─────────────────────────────────────────────────────────

def build_auth_url(redirect_uri: str) -> str:
    """
    Perform DCR (or reuse existing client creds), generate PKCE, and
    return the authorization URL to open in the user's browser.
    """
    global _pending

    existing_ts = get_token_set()
    if existing_ts and existing_ts.client_id:
        client_id     = existing_ts.client_id
        client_secret = existing_ts.client_secret
    else:
        client_id, client_secret = _register_client(redirect_uri)

    verifier, challenge = _generate_pkce()
    state = _generate_state()

    _pending = {
        "verifier":      verifier,
        "client_id":     client_id,
        "client_secret": client_secret,
        "state":         state,
        "redirect_uri":  redirect_uri,
    }

    params = {
        "response_type":         "code",
        "client_id":             client_id,
        "redirect_uri":          redirect_uri,
        "scope":                 DEFAULT_SCOPES,
        "state":                 state,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
    }
    return AUTHORIZATION_URL + "?" + urllib.parse.urlencode(params)


# ── Token exchange ────────────────────────────────────────────────────────────

def exchange_code(code: str, state: str | None = None) -> TokenSet:
    """Exchange an auth code for tokens. Must be called after build_auth_url."""
    if not _pending:
        raise RuntimeError("No pending OAuth flow — call build_auth_url() first.")
    if state and state != _pending.get("state"):
        raise ValueError(f"OAuth state mismatch (received {state!r}).")

    body: dict = {
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  _pending["redirect_uri"],
        "client_id":     _pending["client_id"],
        "code_verifier": _pending["verifier"],
    }
    if _pending["client_secret"]:
        body["client_secret"] = _pending["client_secret"]

    data = _post_token(body)
    ts = TokenSet(
        access_token=  data["access_token"],
        refresh_token= data.get("refresh_token", ""),
        expires_at=    time.time() + data.get("expires_in", 3600),
        client_id=     _pending["client_id"],
        client_secret= _pending["client_secret"],
        token_type=    data.get("token_type", "Bearer"),
    )
    set_token_set(ts)
    return ts


# ── Token refresh ─────────────────────────────────────────────────────────────

def _do_refresh(ts: TokenSet) -> TokenSet:
    if not ts.refresh_token:
        raise RuntimeError("No refresh_token available.")
    body: dict = {
        "grant_type":    "refresh_token",
        "refresh_token": ts.refresh_token,
        "client_id":     ts.client_id,
    }
    if ts.client_secret:
        body["client_secret"] = ts.client_secret
    data = _post_token(body)
    return TokenSet(
        access_token=  data["access_token"],
        refresh_token= data.get("refresh_token", ts.refresh_token),
        expires_at=    time.time() + data.get("expires_in", 3600),
        client_id=     ts.client_id,
        client_secret= ts.client_secret,
        token_type=    data.get("token_type", "Bearer"),
    )


def _post_token(body: dict) -> dict:
    payload = urllib.parse.urlencode(body).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept":       "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        raise RuntimeError(
            f"Token endpoint HTTP {exc.code}: {body_bytes.decode(errors='replace')}"
        ) from exc


# ── File persistence (XOR-obfuscated) ─────────────────────────────────────────

def _token_file() -> Optional[Path]:
    path_str = os.getenv("EULER_TOKEN_FILE", "")
    if path_str:
        return Path(path_str)
    project_root = Path(__file__).parent.parent
    return project_root / ".euler_token"


def _derive_key() -> bytes:
    secret = os.getenv("EULER_TOKEN_SECRET", "")
    if not secret:
        secret = (
            os.getenv("COMPUTERNAME", "")
            + os.getenv("USERNAME", "")
            + "euler-mcp-key-v1"
        )
    return hashlib.sha256(secret.encode()).digest()


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


def _persist(ts: TokenSet) -> None:
    fpath = _token_file()
    if fpath is None:
        return
    try:
        raw = json.dumps(asdict(ts)).encode()
        enc = _xor_bytes(raw, _derive_key())
        fpath.write_text(base64.b64encode(enc).decode(), encoding="ascii")
        log.debug("EULER token persisted to %s", fpath)
    except Exception as exc:
        log.warning("Could not persist EULER token: %s", exc)


def _delete_persisted() -> None:
    fpath = _token_file()
    if fpath and fpath.exists():
        fpath.unlink(missing_ok=True)


def load_persisted() -> Optional[TokenSet]:
    """Load + decrypt the persisted token file. Returns None on any error."""
    fpath = _token_file()
    if fpath is None or not fpath.exists():
        return None
    try:
        enc = base64.b64decode(fpath.read_text(encoding="ascii").strip())
        raw = _xor_bytes(enc, _derive_key())
        ts  = TokenSet(**json.loads(raw))
        log.info("EULER token loaded from %s", fpath)
        return ts
    except Exception as exc:
        log.warning("Could not load EULER token file: %s", exc)
        return None


def try_load_persisted() -> Optional[TokenSet]:
    """
    Load persisted token on startup, refresh if needed, and set the global.
    Returns None if no usable token is available.
    """
    global _token_set
    ts = load_persisted()
    if ts is None:
        return None
    if ts.is_expired():
        if ts.refresh_token:
            try:
                ts = _do_refresh(ts)
                _persist(ts)
                log.info("EULER persisted token refreshed on startup.")
            except Exception as exc:
                log.warning("Startup token refresh failed (%s) — re-auth required.", exc)
                _delete_persisted()
                return None
        else:
            log.info("Persisted EULER token expired, no refresh_token — re-auth required.")
            _delete_persisted()
            return None
    _token_set = ts
    return ts
