#!/usr/bin/env python3
"""
Offline license generator (vendor tool) for FaceAgent.

This CLI creates a signed license payload for a given machine fingerprint
and encrypts it into a distributable license file that the client application
can decrypt and verify offline.

Security notes:
- Keep the vendor private key secure. This tool is intended to be run by the
  vendor/operator on a secure, offline machine.
- The tool imports APP_SALT and PBKDF2 iteration count from the client's
  runtime `licenses.manager` to ensure key derivation compatibility.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import getpass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet

# Import parameters from runtime license manager so derivation matches client
try:
    from licenses.manager import APP_SALT, _PBKDF2_ITERS  # type: ignore
except Exception as exc:  # pragma: no cover - helpful error when run outside project
    raise SystemExit("Failed to import APP_SALT/_PBKDF2_ITERS from licenses.manager: ensure you run this from project root") from exc


def _derive_fernet_key(fingerprint: str) -> bytes:
    """
    Derive a base64-url-safe 32-byte key suitable for Fernet using PBKDF2-HMAC-SHA256.
    The derivation uses the shared APP_SALT and iteration count so the client can reproduce it.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=APP_SALT,
        iterations=_PBKDF2_ITERS,
    )
    raw = kdf.derive(fingerprint.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def load_private_key(path: Path, passphrase: Optional[bytes]) -> serialization.PrivateFormat:
    """
    Load an RSA private key from PEM. If the key is encrypted, provide passphrase bytes.
    Raises an exception on failure.
    """
    data = path.read_bytes()
    try:
        private_key = serialization.load_pem_private_key(data, password=passphrase)
        return private_key
    except Exception as exc:
        raise RuntimeError(f"Unable to load private key '{path}': {exc}") from exc


def build_payload(
    license_type: str,
    hardware_id: str,
    issued_at: Optional[datetime],
    expires_at: Optional[datetime],
    meta: Optional[Dict[str, Any]],
) -> str:
    """
    Build a canonical JSON payload string. Uses sorted keys and compact separators.
    """
    issued = issued_at or datetime.now(timezone.utc)
    payload_obj = {
        "license_type": license_type,
        "issued_at": issued.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
        "hardware_id": hardware_id,
        "meta": meta or {},
    }
    # Canonical JSON: sorted keys, no extra spaces
    return json.dumps(payload_obj, separators=(",", ":"), sort_keys=True)


def sign_payload(private_key, payload_bytes: bytes) -> bytes:
    """
    Sign payload_bytes with RSA-PSS + SHA256 and return signature bytes.
    """
    signature = private_key.sign(
        payload_bytes,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return signature


def create_license_file(
    private_key_path: Path,
    fingerprint: str,
    license_type: str,
    days: Optional[int],
    expires_iso: Optional[str],
    meta_json: Optional[str],
    out_path: Path,
    passphrase: Optional[bytes],
    allow_no_expiry: bool = False,
) -> None:
    """
    Produce a signed and encrypted license token and write it to out_path.
    """
    # Load private key
    private_key = load_private_key(private_key_path, passphrase)

    # Determine expiry
    issued_at = datetime.now(timezone.utc)
    expires_at = None
    if expires_iso:
        try:
            dt = datetime.fromisoformat(expires_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            expires_at = dt
        except Exception as exc:
            raise ValueError(f"Invalid --expires ISO datetime: {exc}") from exc
    elif days is not None:
        expires_at = issued_at + timedelta(days=int(days))
    else:
        if not allow_no_expiry:
            raise ValueError("Either --days or --expires must be provided (or set --allow-no-expiry).")

    # Parse meta JSON if provided
    meta_obj: Dict[str, Any] = {}
    if meta_json:
        try:
            parsed = json.loads(meta_json)
            if not isinstance(parsed, dict):
                raise ValueError("meta must be a JSON object")
            meta_obj = parsed
        except Exception as exc:
            raise ValueError(f"Invalid meta JSON: {exc}") from exc

    # Build canonical payload
    payload_text = build_payload(license_type, fingerprint, issued_at=issued_at, expires_at=expires_at, meta=meta_obj)
    payload_bytes = payload_text.encode("utf-8")

    # Sign the payload
    signature = sign_payload(private_key, payload_bytes)
    signature_b64 = base64.b64encode(signature).decode("ascii")

    # Envelope
    envelope = {"payload": payload_text, "signature": signature_b64}
    envelope_bytes = json.dumps(envelope, separators=(",", ":")).encode("utf-8")

    # Derive symmetric key and encrypt envelope with Fernet
    key = _derive_fernet_key(fingerprint)
    token = Fernet(key).encrypt(envelope_bytes)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(token)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline vendor license generator for FaceAgent")
    p.add_argument("--private-key", "-k", required=True, help="Path to vendor RSA private key PEM")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--fingerprint", help="Target machine fingerprint string")
    group.add_argument("--fingerprint-file", help="Path to file containing target machine fingerprint")
    p.add_argument("--type", "-t", dest="license_type", choices=["trial", "professional", "enterprise"], required=True, help="License type")
    p.add_argument("--days", type=int, help="Validity in days from now (alternative to --expires)")
    p.add_argument("--expires", help="Expiry as ISO datetime (e.g. 2026-12-31T23:59:59+00:00)")
    p.add_argument("--meta", help='Optional JSON object with extra metadata (e.g. \'{"seats":10}\')')
    p.add_argument("--out", "-o", required=True, help="Output license file path")
    p.add_argument("--passphrase", help="Private key passphrase (if key is encrypted). If omitted, the tool may prompt.")
    p.add_argument("--allow-no-expiry", action="store_true", help="Allow creating licenses without expiry when neither --days nor --expires are provided")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))

    private_key_path = Path(args.private_key)
    if not private_key_path.exists():
        print(f"Private key not found: {private_key_path}", file=sys.stderr)
        return 2

    if args.fingerprint:
        fingerprint = args.fingerprint.strip()
    else:
        fp_file = Path(args.fingerprint_file)
        if not fp_file.exists():
            print(f"Fingerprint file not found: {fp_file}", file=sys.stderr)
            return 2
        fingerprint = fp_file.read_text(encoding="utf-8").strip()

    out_path = Path(args.out)

    passphrase_bytes: Optional[bytes] = None
    if args.passphrase:
        passphrase_bytes = args.passphrase.encode("utf-8")
    else:
        # Try to load without passphrase first; if the key is encrypted, prompt the user.
        try:
            _ = load_private_key(private_key_path, None)
            passphrase_bytes = None
        except Exception:
            try:
                pw = getpass.getpass("Private key passphrase: ")
            except Exception:
                pw = ""
            passphrase_bytes = pw.encode("utf-8") if pw else None

    try:
        create_license_file(
            private_key_path=private_key_path,
            fingerprint=fingerprint,
            license_type=args.license_type,
            days=args.days,
            expires_iso=args.expires,
            meta_json=args.meta,
            out_path=out_path,
            passphrase=passphrase_bytes,
            allow_no_expiry=args.allow_no_expiry,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3

    print(f"License generated successfully at: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
