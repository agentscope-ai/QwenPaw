"""生成 demo-rbac 自包含 JWT 密钥与 Token（不依赖 agentgateway-main）。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ISSUER = "agentgateway.dev"
AUDIENCE = "test.agentgateway.dev"
EXP = int(datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp())
DIR = Path(__file__).resolve().parent

PROFILES = {
    "employeeQwenpaw.key": {
        "sub": "employeeQwenpaw",
        # 新发 Token 时建议含 manager（叙事用）；演示降权不依赖重签 Token
        "roles": ["manager"],
    },
    "managerQwenpaw.key": {
        "sub": "managerQwenpaw",
        "roles": ["manager"],
    },
}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def jwk_thumbprint(kty: str, crv: str, x: str, y: str) -> str:
    payload = json.dumps({"crv": crv, "kty": kty, "x": x, "y": y}, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).digest()
    return b64url(digest)


def load_or_create_keypair():
    priv_path = DIR / "priv-key.pem"
    pub_path = DIR / "pub-key"
    if priv_path.is_file() and pub_path.is_file():
        private_key = serialization.load_pem_private_key(
            priv_path.read_bytes(),
            password=None,
        )
        jwks = json.loads(pub_path.read_text(encoding="utf-8"))
        kid = jwks["keys"][0]["kid"]
        return private_key, kid

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    numbers = public_key.public_numbers()
    x = b64url(numbers.x.to_bytes(32, "big"))
    y = b64url(numbers.y.to_bytes(32, "big"))
    kid = jwk_thumbprint("EC", "P-256", x, y)

    jwks = {
        "keys": [
            {
                "use": "sig",
                "kty": "EC",
                "kid": kid,
                "crv": "P-256",
                "alg": "ES256",
                "x": x,
                "y": y,
            }
        ]
    }
    pub_path.write_text(json.dumps(jwks, indent=2) + "\n", encoding="utf-8")
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    priv_path.write_bytes(pem)
    return private_key, kid


def issue_tokens(private_key, kid: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for filename, extra in PROFILES.items():
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": EXP,
            "sub": extra["sub"],
            "roles": extra["roles"],
        }
        token = jwt.encode(
            claims,
            private_key,
            algorithm="ES256",
            headers={"kid": kid, "typ": "JWT"},
        )
        (DIR / filename).write_text(token + "\n", encoding="utf-8")
        tokens[filename] = token
        print(f"Wrote {filename}  sub={extra['sub']}  roles={extra['roles']}")
    return tokens


def update_inspector_helper(employee_token: str, manager_token: str) -> None:
    helper = DIR.parent / "inspector-helper.html"
    if not helper.is_file():
        return
    text = helper.read_text(encoding="utf-8")
    start = '    const TOKENS = {'
    end = '    };'
    i = text.find(start)
    j = text.find(end, i)
    if i < 0 or j < 0:
        return
    block = (
        f'    const TOKENS = {{\n'
        f'      employee: "Bearer {employee_token}",\n'
        f'      manager: "Bearer {manager_token}"\n'
        f'    }};'
    )
    helper.write_text(text[:i] + block + text[j + len(end) :], encoding="utf-8")
    print("Updated inspector-helper.html")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate demo-rbac JWT key pair and tokens.")
    parser.add_argument(
        "--rotate-keys",
        action="store_true",
        help="Force new EC key pair (invalidates existing .key files' signatures).",
    )
    args = parser.parse_args()

    if args.rotate_keys:
        for path in (DIR / "priv-key.pem", DIR / "pub-key"):
            if path.exists():
                path.unlink()

    private_key, kid = load_or_create_keypair()
    tokens = issue_tokens(private_key, kid)
    update_inspector_helper(
        tokens["employeeQwenpaw.key"],
        tokens["managerQwenpaw.key"],
    )
    print(f"JWKS kid={kid}")


if __name__ == "__main__":
    main()
