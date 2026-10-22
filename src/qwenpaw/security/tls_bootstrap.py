# -*- coding: utf-8 -*-
"""Bootstrap and verify TLS package floors without project dependencies.

Run this file directly before installing QwenPaw, or use it to repair an
existing environment. Never disable certificate verification to bootstrap.
"""

import argparse
import json
import re
import ssl
import subprocess
import sys

MIN_CERTIFI = "2026.10.19"
MIN_PIP = "26.2.2"
MIN_UV = "0.13.4"
PIP_WHEEL = (
    "pip @ https://files.pythonhosted.org/packages/3f/06/"
    "3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/"
    "pip-26.2.2-py3-none-any.whl#sha256="
    "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
)
_PROBE = """
import importlib
import json
import sys
if len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1])
versions = {}
for name in ('pip', 'certifi', 'pip._vendor.certifi'):
    try:
        versions[name] = importlib.import_module(name).__version__
    except ModuleNotFoundError:
        versions[name] = None
print(json.dumps(versions))
"""


def at_least(value: str | None, minimum: str) -> bool:
    """Accept stable numeric versions, rejecting unknown/prerelease values."""
    if not value or not re.fullmatch(r"\d+(?:\.\d+)+", value):
        return False
    actual = tuple(int(part) for part in value.split("."))
    required = tuple(int(part) for part in minimum.split("."))
    return actual >= required


def inspect_python(python: str, target: str | None = None) -> dict:
    """Inspect the actual modules loaded by the selected interpreter."""
    command = [python, "-c", _PROBE]
    if target:
        command.append(target)
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def require_pip(python: str) -> bool:
    """Reject unsafe pip; return False only when pip is absent."""
    versions = inspect_python(python)
    if versions["pip"] is None:
        return False
    for name, minimum in (
        ("pip", MIN_PIP),
        ("pip._vendor.certifi", MIN_CERTIFI),
    ):
        if not at_least(versions[name], minimum):
            raise RuntimeError(
                f"Unsafe {name} ({versions[name]}) in {python}; "
                f"requires >= {minimum}. Run tls_bootstrap.py with "
                "this interpreter or update QwenPaw Desktop.",
            )
    return True


def require_uv(uv: str) -> None:
    """Check the executable that will perform the dependency download."""
    result = subprocess.run(
        [uv, "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    match = re.match(r"^uv (\S+)", result.stdout)
    if not match or not at_least(match[1], MIN_UV):
        raise RuntimeError(
            f"Unsafe uv at {uv}; requires >= {MIN_UV}. "
            "Install a patched uv from the official release and retry.",
        )


def require_system_certs() -> None:
    """Reject an empty or still-affected effective OpenSSL trust store."""
    certs = ssl.create_default_context().get_ca_certs()
    if not certs:
        raise RuntimeError("The effective system CA store is empty")
    for cert in certs:
        for rdn in cert["subject"]:
            if ("commonName", "emSign ECC Root CA - G3") in rdn:
                raise RuntimeError(
                    "The effective CA store still trusts emSign ECC Root "
                    "CA - G3; update system/custom CA certificates first",
                )


def bootstrap(
    python: str,
    *,
    check: bool = False,
    target: str | None = None,
) -> dict:
    """Repair pip first, then certifi, and verify their loaded versions."""
    versions = inspect_python(python)
    if not check:
        if versions["pip"] is None:
            subprocess.run(
                [python, "-m", "ensurepip", "--upgrade"],
                check=True,
            )
        if not (
            at_least(versions["pip"], MIN_PIP)
            and at_least(versions["pip._vendor.certifi"], MIN_CERTIFI)
        ):
            subprocess.run(
                [
                    python,
                    "-m",
                    "pip",
                    "install",
                    "--force-reinstall",
                    "--no-deps",
                    "--no-cache-dir",
                    PIP_WHEEL,
                ],
                check=True,
            )
        if not require_pip(python):
            raise RuntimeError(f"pip is missing from {python}")
        if target or not at_least(versions["certifi"], MIN_CERTIFI):
            command = [python, "-m", "pip", "install", "--no-deps"]
            if target:
                command.extend(["--upgrade", "--target", target])
            command.append(f"certifi>={MIN_CERTIFI}")
            subprocess.run(command, check=True)
    if not require_pip(python):
        raise RuntimeError(f"pip is missing from {python}")
    versions = inspect_python(python, target)
    if not at_least(versions["certifi"], MIN_CERTIFI):
        raise RuntimeError(f"certifi >= {MIN_CERTIFI} required: {versions}")
    return versions


def main() -> None:
    """Upgrade one explicit environment or check a package installer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--uv", help="Check this uv executable only")
    parser.add_argument("--system-certs", action="store_true")
    parser.add_argument(
        "--target",
        help="Repair a plugin dependency directory",
    )
    args = parser.parse_args()
    if args.system_certs:
        require_system_certs()
    elif args.uv:
        require_uv(args.uv)
    else:
        print(
            json.dumps(
                bootstrap(
                    args.python,
                    check=args.check,
                    target=args.target,
                ),
                sort_keys=True,
            ),
        )


if __name__ == "__main__":
    main()
