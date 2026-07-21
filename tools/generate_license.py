#!/usr/bin/env python3
"""
Vendor helper script to create signed & encrypted license tokens for FaceAgent.

This script produces the same token format consumed by `licenses.manager.decrypt_license_file`.
Token creation steps:
  1. Build a canonical JSON payload containing:
       {
         "license_type": "<trial|professional|enterprise>",
         "issued_at": "<ISO8601 UTC>",
         "expires_at": "<ISO8601 UTC or null>",
         "hardware_id": "<machine fingerprint>",
         "meta": {... optional ...}
       }
     The payload string is canonical: `json.dumps(..., separators=(",", ":"), sort_keys=True)`.
  2. Sign the UTF-8 bytes of that payload using an RSA private key with RSA-PSS+SHA256:
       signature = base64.b64encode(private_key.sign(payload_bytes, PSS(...), SHA256))
  3. Build the envelope:
       {"payload": "<payload-string>", "signature": "<base64-signature>"}
     (For unsigned tokens, signature is the empty string.)
     The envelope bytes are encoded via:
       envelope_bytes = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
  4. Derive a Fernet key from the machine fingerprint using PBKDF2-HMAC-SHA256 and the
     application salt. This must use the same APP_SALT and iteration count as the client.
  5. Encrypt the envelope bytes with Fernet(key) and write the token bytes to disk.

Usage (examples):
  # Signed license, expires in 365 days:
  python generate_license.py \\
      --fingerprint-file /path/to/machine_id.txt \\
      --license-type professional \\
      --days 365 \\
      --private-key vendor_private.pem \\
      --out license.key

  # Create an unsigned local trial token (for testing / evaluation):
  python generate_license.py --fingerprint <hexfp> --license-type trial --days 14 --unsigned --out license.key

Notes:
- The APP_SALT and PBKDF2 iteration count are intentionally the same as the client
  (`licenses.manager`) so that the derived Fernet key matches.
- The vendor must keep the private key secure. The corresponding public key is distributed
  with the client to verify signatures.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ---------------------------------------------------------------------------
# Constants -- must match client (licenses.manager)
# ---------------------------------------------------------------------------
APP_SALT: bytes = b"FaceAgentOfflineLicenseV1"
_PBKDF2_ITERS: int = 390000

ALLOWED_LICENSE_TYPES = {"trial", "professional", "enterprise"}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------
def _derive_fernet_key(fingerprint: str, salt: bytes = APP_SALT, iterations: int = _PBKDF2_ITERS) -> bytes:
    """
    Derive a 32-byte key for Fernet from the fingerprint and APP_SALT using PBKDF2.
    Returns base64.urlsafe_b64encoded key suitable for Fernet.
    """
    password = fingerprint.encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    raw_key = kdf.derive(password)
    return base64.urlsafe_b64encode(raw_key)


def _canonical_json(obj: Any) -> str:
    """
    Return canonical JSON string for the object: sorted keys, compact separators.
    """
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


def _load_private_key(path: Path, password: Optional[bytes] = None):
    data = path.read_bytes()
    try:
        key = serialization.load_pem_private_key(data, password=password)
        return key
    except Exception as exc:
        raise RuntimeError(f"Failed to load private key from {path}: {exc}") from exc


def _sign_payload(private_key, payload_bytes: bytes) -> bytes:
    """
    Sign payload_bytes using RSA-PSS + SHA256 and return the raw signature bytes.
    """
    sig = private_key.sign(
        payload_bytes,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return sig


# ---------------------------------------------------------------------------
# License generation
# ---------------------------------------------------------------------------
def generate_license_token(
    *,
    fingerprint: str,
    license_type: str,
    issued_at: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
    meta: Optional[Dict[str, Any]] = None,
    private_key_path: Optional[Path] = None,
    private_key_password: Optional[bytes] = None,
    unsigned: bool = False,
) -> bytes:
    """
    Create a Fernet-encrypted license token (bytes) for the given machine fingerprint.

    - fingerprint: machine fingerprint (string)
    - license_type: one of ALLOWED_LICENSE_TYPES
    - issued_at: datetime (UTC) or None -> now UTC
    - expires_at: datetime (UTC) or None -> no expiry
    - meta: optional dict placed into payload["meta"]
    - private_key_path: path to PEM private key. Required unless unsigned=True.
    - private_key_password: optional password bytes for encrypted private keys.
    - unsigned: if True, create envelope with empty signature (useful for local trials).
    """
    if license_type not in ALLOWED_LICENSE_TYPES:
        raise ValueError(f"Unsupported license_type: {license_type}; allowed: {ALLOWED_LICENSE_TYPES}")

    now = issued_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    exp = expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    payload = {
        "license_type": license_type,
        "issued_at": now.isoformat(),
        "expires_at": exp.isoformat() if exp is not None else None,
        "hardware_id": fingerprint,
        "meta": meta or {},
    }

    # Canonical payload string
    payload_text = _canonical_json(payload)
    payload_bytes = payload_text.encode("utf-8")

    signature_b64 = ""
    if not unsigned:
        if private_key_path is None:
            raise ValueError("private_key_path is required for signed licenses")
        private_key = _load_private_key(private_key_path, password=private_key_password)
        signature = _sign_payload(private_key, payload_bytes)
        signature_b64 = base64.b64encode(signature).decode("ascii")

    envelope = {"payload": payload_text, "signature": signature_b64}
    envelope_bytes = json.dumps(envelope, separators=(",", ":")).encode("utf-8")

    # Encrypt envelope with Fernet key derived from fingerprint
    key = _derive_fernet_key(fingerprint)
    token = Fernet(key).encrypt(envelope_bytes)
    return token


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate signed & encrypted license tokens for FaceAgent.")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--fingerprint", help="Machine fingerprint string")
    grp.add_argument("--fingerprint-file", type=Path, help="Read machine fingerprint from file (UTF-8)")

    p.add_argument("--license-type", required=True, choices=sorted(ALLOWED_LICENSE_TYPES), help="License type")
    p.add_argument("--days", type=int, help="License validity in days from now (mutually exclusive with --expires)")
    p.add_argument("--expires", help="Expiry ISO datetime (UTC) e.g. 2026-12-31T23:59:59+00:00")
    p.add_argument("--issued-at", help="Issued-at ISO datetime (UTC). Defaults to now.")
    p.add_argument("--meta", help="Optional JSON string to include in payload meta")
    p.add_argument("--private-key", type=Path, help="PEM file containing RSA private key (required unless --unsigned)")
    p.add_argument("--key-password", help="Password for encrypted private key (if applicable)")
    p.add_argument("--unsigned", action="store_true", help="Create an unsigned license (signature will be empty)")
    p.add_argument("--out", type=Path, default=Path("license.key"), help="Output path for license token (bytes)")
    p.add_argument("--print-base64", action="store_true", help="Also print base64 token to stdout")
    p.add_argument("--pubout", type=Path, help="If provided along with --private-key, write the corresponding public key PEM to this path")
    return p.parse_args()


def _load_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # datetime.fromisoformat handles offsets; ensure tzinfo present
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main() -> None:
    args = _parse_args()

    if args.fingerprint:
        fingerprint = args.fingerprint.strip()
    else:
        # read file
        fp = Path(args.fingerprint_file)
        if not fp.exists():
            raise SystemExit(f"Fingerprint file not found: {fp}")
        fingerprint = fp.read_text(encoding="utf-8").strip()

    if args.meta:
        try:
            meta = json.loads(args.meta)
            if not isinstance(meta, dict):
                raise ValueError("meta must be a JSON object")
        except Exception as exc:
            raise SystemExit(f"Invalid --meta JSON: {exc}")
    else:
        meta = {}

    issued_at = _load_iso(args.issued_at)
    expires_at = _load_iso(args.expires) if args.expires else None
    if args.days is not None:
        if expires_at is not None:
            raise SystemExit("Specify either --days or --expires, not both")
        expires_at = datetime.now(timezone.utc) + timedelta(days=args.days)

    private_key_path = args.private_key
    private_key_password = args.key_password.encode("utf-8") if args.key_password else None

    if args.unsigned:
        private_key_path = None

    if not args.unsigned and private_key_path is None:
        raise SystemExit("Private key required for signed license. Provide --private-key or use --unsigned.")

    token = generate_license_token(
        fingerprint=fingerprint,
        license_type=args.license_type,
        issued_at=issued_at,
        expires_at=expires_at,
        meta=meta,
        private_key_path=private_key_path,
        private_key_password=private_key_password,
        unsigned=args.unsigned,
    )

    out_path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(token)
    print(f"Wrote license token ({len(token)} bytes) to: {out_path}")

    if args.print_base64:
        print(base64.b64encode(token).decode("ascii"))

    # Optionally emit public key PEM if requested
    if args.pubout and args.private_key:
        priv = _load_private_key(args.private_key, password=private_key_password)
        pub = priv.public_key()
        pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        args.pubout.parent.mkdir(parents=True, exist_ok=True)
        args.pubout.write_bytes(pem)
        print(f"Wrote public key PEM to: {args.pubout}")


if __name__ == "__main__":
    main()
