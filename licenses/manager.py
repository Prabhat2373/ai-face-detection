#!/usr/bin/env python3
"""
Offline license manager for FaceAgent.

Responsibilities:
- Compute a stable machine fingerprint (machine-bound identifier).
- Derive a symmetric key from the fingerprint + application salt (PBKDF2-HMAC-SHA256).
- Decrypt a Fernet-encrypted license token (the on-disk license file).
- Verify an RSA-PSS+SHA256 signature on the license payload using a bundled
  public key (PEM).
- Create a local, unsigned trial license (machine-bound) for short-term offline trials.
- Write a fingerprint file for vendor provisioning.

License file on disk:
- The file is the raw Fernet token (bytes). After decryption, it yields a JSON
  envelope like:
    {
      "payload": "<canonical-json-string>",
      "signature": "<base64-signature>"   # empty string for unsigned local trial
    }
- The payload string itself is canonical JSON (sorted keys, compact separators)
  and the vendor signs the UTF-8 bytes of that string.

Security notes:
- Keep APP_SALT stable across releases; vendor must use the same salt when
  generating encrypted tokens.
- Vendor signs payloads with their RSA private key. The client only needs the
  public key to verify signatures.
- Local trial licenses are unsigned and therefore weaker; they exist to allow
  immediate evaluations without vendor interaction.

Dependencies:
- cryptography (pip install cryptography)
"""

from __future__ import annotations

import base64
import json
import os
import platform
import socket
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Application-wide static salt used when deriving per-machine symmetric keys.
# IMPORTANT: keep this stable. Changing it will invalidate all previously
# generated encrypted license files.
APP_SALT: bytes = b"FaceAgentOfflineLicenseV1"

# PBKDF2 iteration count. Reasonable value for desktop apps.
_PBKDF2_ITERS: int = 390000

# Path to the vendor public key (PEM). Replace with real key in distribution.
PUBLIC_KEY_PATH = Path(__file__).resolve().parent / "public_key.pem"

# Allowed license types
ALLOWED_LICENSE_TYPES = {"trial", "professional", "enterprise"}


# ---------------------------------------------------------------------------
# Exceptions + dataclass
# ---------------------------------------------------------------------------

class LicenseError(Exception):
    """Base class for license-related errors."""


class LicenseInvalidError(LicenseError):
    """License is malformed, invalid, or signature verification failed."""


class LicenseExpiredError(LicenseError):
    """License has expired."""


@dataclass
class LicenseInfo:
    license_type: str
    issued_at: Optional[datetime]
    expires_at: Optional[datetime]
    hardware_id: str
    raw_payload: Dict[str, Any]
    is_local_trial: bool = False


# ---------------------------------------------------------------------------
# Machine fingerprint generation
# ---------------------------------------------------------------------------

def _get_linux_machine_id() -> Optional[str]:
    """Return the machine-id on Linux systems, if available."""
    candidates = ["/etc/machine-id", "/var/lib/dbus/machine-id"]
    for p in candidates:
        try:
            path = Path(p)
            if path.exists():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    return text
        except Exception:
            continue
    return None


def get_machine_fingerprint() -> str:
    """
    Compute a stable machine fingerprint.

    The fingerprint is computed by collecting several platform identifiers
    (node name, MAC via uuid.getnode(), platform-specific machine-id) and
    hashing them with SHA-256. The result is returned as a hex string.

    This value is intended to be stable for the same physical machine and is
    safe to share with the vendor for license provisioning.
    """
    parts = []

    try:
        node = platform.node() or ""
        parts.append(node)
    except Exception:
        parts.append("")

    try:
        mac = uuid.getnode()
        parts.append(str(mac))
    except Exception:
        parts.append("")

    try:
        if sys.platform.startswith("linux"):
            mid = _get_linux_machine_id() or ""
            parts.append(mid)
    except Exception:
        parts.append("")

    try:
        parts.append(socket.gethostname())
    except Exception:
        parts.append("")

    raw = "||".join(parts)
    h = sha256(raw.encode("utf-8")).hexdigest()
    return h


def write_fingerprint_file(path: Path) -> str:
    """
    Write the current machine fingerprint to the given file path (UTF-8)
    and return the fingerprint string.
    """
    fp = get_machine_fingerprint()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fp, encoding="utf-8")
    return fp


# ---------------------------------------------------------------------------
# Key derivation and public key loading
# ---------------------------------------------------------------------------

def _derive_fernet_key(fingerprint: str) -> bytes:
    """
    Derive a 32-byte key for Fernet from the fingerprint and APP_SALT using PBKDF2.
    Returns base64.urlsafe_b64encoded key suitable for Fernet.
    """
    password = fingerprint.encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=APP_SALT,
        iterations=_PBKDF2_ITERS,
    )
    raw_key = kdf.derive(password)
    return base64.urlsafe_b64encode(raw_key)


def _load_vendor_public_key():
    """Load and return the vendor public key object from PUBLIC_KEY_PATH."""
    if not PUBLIC_KEY_PATH.exists():
        raise LicenseInvalidError(f"Vendor public key not found at {PUBLIC_KEY_PATH}")
    data = PUBLIC_KEY_PATH.read_bytes()
    try:
        pub = serialization.load_pem_public_key(data)
        return pub
    except Exception as exc:
        raise LicenseInvalidError("Unable to load vendor public key") from exc


# ---------------------------------------------------------------------------
# Decrypt and verify license file
# ---------------------------------------------------------------------------

def decrypt_license_file(path: Path, fingerprint: Optional[str] = None) -> bytes:
    """
    Decrypt the license token at `path` using the key derived from `fingerprint`.
    If fingerprint is None, compute the local machine fingerprint.

    Returns the decrypted envelope bytes (UTF-8 JSON).
    Raises LicenseInvalidError on failure.
    """
    if fingerprint is None:
        fingerprint = get_machine_fingerprint()

    token = path.read_bytes()
    key = _derive_fernet_key(fingerprint)
    f = Fernet(key)
    try:
        plain = f.decrypt(token)
        return plain
    except InvalidToken as exc:
        raise LicenseInvalidError("Unable to decrypt license file with this machine fingerprint") from exc
    except Exception as exc:
        raise LicenseInvalidError("Failed to decrypt license file") from exc


def _verify_signature(payload_bytes: bytes, signature_b64: str) -> None:
    """
    Verify the base64-encoded signature over payload_bytes using vendor public key.
    Raises LicenseInvalidError if verification fails.
    """
    pub = _load_vendor_public_key()
    try:
        signature = base64.b64decode(signature_b64)
    except Exception as exc:
        raise LicenseInvalidError("Invalid base64 signature") from exc

    try:
        pub.verify(
            signature,
            payload_bytes,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
    except Exception as exc:
        raise LicenseInvalidError("Signature verification failed") from exc


def _parse_iso_datetime(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def load_license(path: Path, allow_local_trial: bool = True) -> LicenseInfo:
    """
    Full flow to load and validate a license file:
    - Decrypt the token using local machine fingerprint-derived key.
    - Parse the envelope JSON: { "payload": "<json-string>", "signature": "<b64>" }
    - Verify signature if present; if signature empty and allow_local_trial is True,
      accept as a local trial.
    - Parse payload JSON and validate fields (license_type, hardware binding, expiry).

    Returns a LicenseInfo instance on success.
    Raises LicenseInvalidError or LicenseExpiredError on failure.
    """
    fingerprint = get_machine_fingerprint()
    plain = decrypt_license_file(path, fingerprint)

    try:
        envelope = json.loads(plain.decode("utf-8"))
    except Exception as exc:
        raise LicenseInvalidError("License envelope is not valid JSON") from exc

    if not isinstance(envelope, dict) or "payload" not in envelope or "signature" not in envelope:
        raise LicenseInvalidError("License envelope missing required fields")

    payload_text = envelope.get("payload")
    signature = envelope.get("signature") or ""

    if not isinstance(payload_text, str):
        raise LicenseInvalidError("License payload is not a string")

    payload_bytes = payload_text.encode("utf-8")

    is_local_trial = False
    if signature:
        _verify_signature(payload_bytes, signature)
    else:
        # unsigned license: allow only when explicitly permitted (local trial)
        if not allow_local_trial:
            raise LicenseInvalidError("Unsigned license files are not accepted")
        is_local_trial = True

    try:
        payload = json.loads(payload_text)
    except Exception as exc:
        raise LicenseInvalidError("License payload JSON is invalid") from exc

    ltype = payload.get("license_type")
    if ltype not in ALLOWED_LICENSE_TYPES:
        raise LicenseInvalidError(f"Unsupported license type: {ltype}")

    issued_at = _parse_iso_datetime(payload.get("issued_at")) or datetime.now(timezone.utc)
    expires_at = _parse_iso_datetime(payload.get("expires_at"))
    hw = payload.get("hardware_id")

    # Hardware binding must match local fingerprint
    if hw != fingerprint:
        raise LicenseInvalidError("License hardware_id does not match this machine")

    # Expiry check
    now = datetime.now(timezone.utc)
    if expires_at is not None and expires_at < now:
        raise LicenseExpiredError("License has expired")

    return LicenseInfo(
        license_type=ltype,
        issued_at=issued_at,
        expires_at=expires_at,
        hardware_id=hw,
        raw_payload=payload,
        is_local_trial=is_local_trial,
    )


# ---------------------------------------------------------------------------
# Local trial creation (unsigned, weaker)
# ---------------------------------------------------------------------------

def create_local_trial(path: Path, days: int = 14) -> LicenseInfo:
    """
    Create a locally-generated trial license bound to this machine.
    The envelope is unsigned (signature = ""), so load_license(..., allow_local_trial=True)
    will accept it. This is weaker than a vendor-signed license and intended
    for quick evaluations.
    """
    fingerprint = get_machine_fingerprint()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=days)

    payload = {
        "license_type": "trial",
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "hardware_id": fingerprint,
        "meta": {"origin": "local-trial"},
    }

    # Canonical payload string
    payload_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)

    envelope = {"payload": payload_text, "signature": ""}
    envelope_bytes = json.dumps(envelope, separators=(",", ":")).encode("utf-8")

    key = _derive_fernet_key(fingerprint)
    token = Fernet(key).encrypt(envelope_bytes)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(token)

    return LicenseInfo(
        license_type="trial",
        issued_at=now,
        expires_at=expires,
        hardware_id=fingerprint,
        raw_payload=payload,
        is_local_trial=True,
    )


# ---------------------------------------------------------------------------
# Utility: export fingerprint to file (for vendor)
# ---------------------------------------------------------------------------
def write_fingerprint_file(path: Path) -> str:
    """
    Compute the machine fingerprint and write it to the provided path (UTF-8).
    Returns the fingerprint string.
    """
    fp = get_machine_fingerprint()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fp, encoding="utf-8")
    return fp

# ---------------------------------------------------------------------------
# End of file
# ---------------------------------------------------------------------------
