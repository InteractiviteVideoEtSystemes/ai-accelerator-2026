#!/usr/bin/env python3
"""Derive Supabase anon and service_role API keys (HS256 JWTs) from a JWT secret.

Used as a Terraform `external` data source. Reads a JSON object from stdin with a
"jwt_secret" key and prints a JSON object with "anon_key" and "service_role_key".

Only the Python standard library is used so it runs anywhere Terraform runs.
The generated tokens mirror the structure of the keys produced by the Supabase
CLI / self-hosted defaults: iss=supabase, a long-lived exp, and the role claim.
"""
import base64
import hashlib
import hmac
import json
import sys
import time


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign(payload: dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    segments = [
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(_b64url(signature))
    return ".".join(segments)


def main() -> None:
    query = json.load(sys.stdin)
    secret = query.get("jwt_secret", "")
    if not secret:
        sys.stderr.write("gen-supabase-jwt: missing 'jwt_secret' input\n")
        sys.exit(1)

    iat = int(time.time())
    # 10 years, matching Supabase's long-lived local keys.
    exp = iat + 60 * 60 * 24 * 365 * 10

    anon = _sign({"role": "anon", "iss": "supabase", "iat": iat, "exp": exp}, secret)
    service = _sign(
        {"role": "service_role", "iss": "supabase", "iat": iat, "exp": exp}, secret
    )

    # Terraform's external data source requires string-valued JSON on stdout.
    json.dump({"anon_key": anon, "service_role_key": service}, sys.stdout)


if __name__ == "__main__":
    main()
