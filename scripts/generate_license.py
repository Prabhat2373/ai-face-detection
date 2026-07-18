#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hmac
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class LicensePayload:
    tenantId: str
    companyName: str
    plan: str
    cloudSyncEnabled: bool
    issuedAt: str
    expiresAt: str | None
    machineId: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a signed offline license payload.")
    parser.add_argument("--secret", required=True, help="Signing secret shared with the app for offline verification.")
    parser.add_argument("--tenant-id", required=True, help="Tenant/company identifier.")
    parser.add_argument("--company-name", required=True, help="Customer company name.")
    parser.add_argument("--plan", default="local", help="License plan name.")
    parser.add_argument("--cloud-sync", action="store_true", help="Enable cloud sync for the license.")
    parser.add_argument("--expires-at", default="", help="Optional ISO timestamp, e.g. 2027-07-14T00:00:00Z")
    parser.add_argument("--machine-id", default="", help="Optional machine binding ID.")
    parser.add_argument("--out", default="", help="Optional output file path. Defaults to stdout.")
    return parser.parse_args()


def sign_payload(secret: str, payload: dict[str, object]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def main() -> int:
    args = parse_args()
    payload = LicensePayload(
        tenantId=args.tenant_id.strip().lower(),
        companyName=args.company_name.strip(),
        plan=args.plan.strip() or "local",
        cloudSyncEnabled=bool(args.cloud_sync),
        issuedAt=utc_now(),
        expiresAt=args.expires_at.strip() or None,
        machineId=args.machine_id.strip() or None,
    )
    payload_dict = asdict(payload)
    signature = sign_payload(args.secret, payload_dict)
    license_blob = {
        "payload": payload_dict,
        "signature": signature,
        "algorithm": "HS256",
    }
    rendered = json.dumps(license_blob, indent=2, ensure_ascii=False)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.write("\n")
        print(f"Wrote license to {args.out}")
    else:
        sys.stdout.write(rendered)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
