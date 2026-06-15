#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sign, verify, and build example fixtures for skill ZIP packages.

Usage:
  python extension/skill_sign/sign_tool/sign_skill.py gen-keypair
  python extension/skill_sign/sign_tool/sign_skill.py sign --input skill.zip
  python extension/skill_sign/sign_tool/sign_skill.py verify --input skill.zip --sig skill.zip.sig
  python extension/skill_sign/sign_tool/sign_skill.py build-examples
"""
from __future__ import annotations

import argparse
import base64
import shutil
import sys
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_SCRIPT_DIR = Path(__file__).resolve().parent
_EXTENSION_DIR = _SCRIPT_DIR.parents[1]
if str(_EXTENSION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTENSION_DIR))

from skill_sign.constants import (  # noqa: E402
    DEFAULT_PRIVATE_KEY_PATH,
    DEFAULT_PUBLIC_KEY_PATH,
    EXAMPLES_DIR,
    KEYS_DIR,
    TRUST_DIR,
)
from skill_sign.verifier import verify_skill_package_signature  # noqa: E402


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    raw = path.read_bytes()
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("private key must be Ed25519")
    return key


def _write_public_key(private_key: Ed25519PrivateKey, path: Path) -> None:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(public_bytes)


def _write_private_key(private_key: Ed25519PrivateKey, path: Path) -> None:
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(private_bytes)


def cmd_gen_keypair(force: bool) -> int:
    if DEFAULT_PRIVATE_KEY_PATH.exists() and not force:
        print(
            f"Private key already exists: {DEFAULT_PRIVATE_KEY_PATH}\n"
            "Use --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    private_key = Ed25519PrivateKey.generate()
    _write_private_key(private_key, DEFAULT_PRIVATE_KEY_PATH)
    _write_public_key(private_key, DEFAULT_PUBLIC_KEY_PATH)
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    print(f"private_key={DEFAULT_PRIVATE_KEY_PATH}")
    print(f"public_key={DEFAULT_PUBLIC_KEY_PATH}")
    print(f"public_key_hex={public_raw.hex()}")
    return 0


def cmd_sign(input_path: Path, output_path: Path | None, private_key_path: Path) -> int:
    if not input_path.is_file():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1
    if not private_key_path.is_file():
        print(
            f"Private key not found: {private_key_path}\n"
            "Run `sign_skill.py gen-keypair` first.",
            file=sys.stderr,
        )
        return 1

    private_key = _load_private_key(private_key_path)
    package_data = input_path.read_bytes()
    signature = private_key.sign(package_data)
    sig_path = output_path or Path(f"{input_path}.sig")
    sig_path.write_text(base64.b64encode(signature).decode("ascii") + "\n", encoding="ascii")
    print(f"signed={input_path}")
    print(f"signature={sig_path}")
    return 0


def cmd_verify(input_path: Path, sig_path: Path, public_key_path: Path) -> int:
    if not input_path.is_file():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1
    if not sig_path.is_file():
        print(f"Signature file not found: {sig_path}", file=sys.stderr)
        return 1

    result = verify_skill_package_signature(
        input_path.read_bytes(),
        sig_path.read_bytes(),
        public_key_path=public_key_path,
    )
    if result.valid:
        print(f"valid=true signer={result.signer} sha256={result.package_sha256}")
        return 0

    print(f"valid=false error={result.error}", file=sys.stderr)
    return 1


def _zip_skill_dir(source_dir: Path, output_zip: Path) -> None:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(source_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(source_dir).as_posix()
                zf.write(file_path, arcname)


def cmd_build_examples(private_key_path: Path, public_key_path: Path) -> int:
    valid_src = EXAMPLES_DIR / "valid" / "demo-skill"
    if not valid_src.is_dir():
        print(f"Missing example source directory: {valid_src}", file=sys.stderr)
        return 1
    if not private_key_path.is_file():
        print(
            f"Private key not found: {private_key_path}\n"
            "Run `sign_skill.py gen-keypair` first.",
            file=sys.stderr,
        )
        return 1
    if not public_key_path.is_file():
        print(f"Public key not found: {public_key_path}", file=sys.stderr)
        return 1

    valid_zip = EXAMPLES_DIR / "valid" / "demo-skill.zip"
    valid_sig = EXAMPLES_DIR / "valid" / "demo-skill.zip.sig"
    invalid_zip = EXAMPLES_DIR / "invalid" / "tampered-skill.zip"
    invalid_sig = EXAMPLES_DIR / "invalid" / "tampered-skill.zip.sig"

    _zip_skill_dir(valid_src, valid_zip)
    if cmd_sign(valid_zip, valid_sig, private_key_path) != 0:
        return 1

    invalid_zip.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(valid_zip, invalid_zip)
    tampered = bytearray(invalid_zip.read_bytes())
    tampered[-1] ^= 0x01
    invalid_zip.write_bytes(bytes(tampered))
    shutil.copy2(valid_sig, invalid_sig)

    if cmd_verify(valid_zip, valid_sig, public_key_path) != 0:
        return 1
    if cmd_verify(invalid_zip, invalid_sig, public_key_path) == 0:
        print("Expected tampered example to fail verification", file=sys.stderr)
        return 1

    print("examples=ok")
    print(f"valid_zip={valid_zip}")
    print(f"invalid_zip={invalid_zip}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Skill package signing tool")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("gen-keypair", help="Generate Ed25519 keypair")
    gen.add_argument("--force", action="store_true", help="Overwrite existing keys")

    sign = sub.add_parser("sign", help="Sign a skill ZIP package")
    sign.add_argument("--input", required=True, type=Path)
    sign.add_argument("--output", type=Path)
    sign.add_argument("--private-key-file", type=Path, default=DEFAULT_PRIVATE_KEY_PATH)

    verify = sub.add_parser("verify", help="Verify a signed skill ZIP package")
    verify.add_argument("--input", required=True, type=Path)
    verify.add_argument("--sig", required=True, type=Path)
    verify.add_argument("--pubkey", type=Path, default=DEFAULT_PUBLIC_KEY_PATH)

    build = sub.add_parser("build-examples", help="Build valid/invalid example fixtures")
    build.add_argument("--private-key-file", type=Path, default=DEFAULT_PRIVATE_KEY_PATH)
    build.add_argument("--pubkey", type=Path, default=DEFAULT_PUBLIC_KEY_PATH)

    args = parser.parse_args(argv)

    if args.command == "gen-keypair":
        return cmd_gen_keypair(args.force)
    if args.command == "sign":
        return cmd_sign(args.input, args.output, args.private_key_file)
    if args.command == "verify":
        return cmd_verify(args.input, args.sig, args.pubkey)
    if args.command == "build-examples":
        return cmd_build_examples(args.private_key_file, args.pubkey)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
