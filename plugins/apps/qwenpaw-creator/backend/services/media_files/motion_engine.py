# -*- coding: utf-8 -*-
"""Deterministic JS engine assets for ``html_js`` motion documents.

An ``html_js`` motion document drives its animation from an inline script
through the ``window.__hf = { duration, seek }`` protocol (a minimal subset
of the HyperFrames runtime contract).  This module owns everything the
renderer needs beyond the document itself:

- the vendor registry: which animation runtimes may be referenced, pinned
  by content hash so a library upgrade can never silently reuse stale
  rendered frames;
- the determinism prelude injected before document scripts, freezing wall
  clocks and seeding ``Math.random`` so one (html, seek time) pair always
  paints the same pixels;
- the engine digest that salts frame-cache keys and render fingerprints
  with every out-of-document input (prelude + vendor bytes).

Vendor library files are not committed to the repository (GSAP ships under
the GreenSock Standard License, not this project's license).  They are
fetched once into :func:`vendor_root` via ``python -m
services.media_files.motion_engine fetch`` and verified against the pinned
hash on every use.

Adding a new vendor runtime (registry extension procedure)
-----------------------------------------------------------
The whitelist plus content-hash pin mechanism is fixed; growing the
registry means one reviewed :data:`VENDOR_LIBS` entry, never a code path
change.  For each candidate library:

1. License review first: record the exact license in ``license_note`` and
   decide whether the file may be committed.  Anything not distributable
   under this project's license (e.g. GSAP) stays fetch-on-demand and its
   filename must be covered by ``vendor/.gitignore``.
2. Pin one exact upstream artifact: a versioned, immutable ``source_url``
   (no ``@latest``), its ``sha256`` over the raw bytes and ``size_bytes``.
   Compute the hash from a fresh download, not from local caches.
3. Seek-safety review: the runtime must be drivable through the
   ``window.__hf`` protocol under the determinism prelude (no wall-clock
   or rAF-driven internal state).  See docs/motion_hf_contract.md.
4. Register the :class:`VendorLib` entry and update the authoring
   contract in ``motion_design.py`` so documents may reference the new
   ``vendor/<filename>``.
5. Digest upversion happens automatically: :func:`engine_digest` and
   :func:`full_engine_digest` fold every pinned hash into frame-cache
   keys and render fingerprints, so any pin change invalidates stale
   frames.  Bump :data:`MOTION_ENGINE_PROTOCOL_VERSION` only for
   behavioral engine changes (prelude semantics, seek schedule), not for
   registry growth.
6. Verify with ``python -m services.media_files.motion_engine fetch``
   plus the vendor-registry unit tests before shipping.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import threading

from domain.errors import ValidationError

# Version 2: renderer-managed exits track the real playhead instead of
# the (possibly wrapped/clamped) timeline time, fixing end-of-segment
# exits for looping and short-duration documents.
MOTION_ENGINE_PROTOCOL_VERSION = 2

# Injected via Page.addInitScript so it runs before any document script.
# ``__qpMotionClock`` is the worker-side seek hook: every captured frame
# first pins the frozen clocks to the frame timestamp.
MOTION_PRELUDE_SCRIPT = """\
(() => {
  "use strict";
  let clockMs = 0;
  Object.defineProperty(window, "__qpMotionClock", {
    value: (ms) => { clockMs = Number(ms) || 0; },
    writable: false,
    configurable: false,
  });
  const frozenNow = () => clockMs;
  Date.now = frozenNow;
  if (window.performance) {
    try { window.performance.now = frozenNow; } catch (error) {}
  }
  let seed = 2463534242 >>> 0;
  Math.random = () => {
    seed ^= seed << 13; seed >>>= 0;
    seed ^= seed >>> 17;
    seed ^= seed << 5; seed >>>= 0;
    return seed / 4294967296;
  };
})();
"""

MOTION_PRELUDE_SHA256 = hashlib.sha256(
    MOTION_PRELUDE_SCRIPT.encode("utf-8"),
).hexdigest()

# Documents reference vendor runtimes with exactly this relative prefix;
# the capture worker materialises the files next to the document.
VENDOR_SRC_PREFIX = "vendor/"

_VENDOR_SRC_PATTERN = re.compile(
    r"""<\s*script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class VendorLib:
    """One pinned, locally vendored animation runtime."""

    name: str
    filename: str
    sha256: str
    size_bytes: int
    source_url: str
    license_note: str


VENDOR_LIBS: dict[str, VendorLib] = {
    "gsap": VendorLib(
        name="gsap",
        filename="gsap.min.js",
        sha256=(
            "92bb9a96476f983d212a2bc4f54c889039c1696d"
            "d4461d40a736860938570fbb"
        ),
        size_bytes=72927,
        source_url="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js",
        license_note="GreenSock Standard License (free use, not committed)",
    ),
}

_LIBS_BY_FILENAME = {lib.filename: lib for lib in VENDOR_LIBS.values()}

_verified_cache: dict[str, tuple[float, int]] = {}
_verified_lock = threading.Lock()


def vendor_root() -> Path:
    """Directory holding vendored runtime files (env-overridable)."""

    override = os.environ.get("QWENPAW_CREATOR_MOTION_VENDOR_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "vendor"


def referenced_vendor_filenames(html: str) -> list[str]:
    """Every ``script src`` filename under the vendor prefix, in order.

    Raises ``ValidationError`` for any script src outside the vendor
    whitelist; callers rely on this as the single gate for external code.
    """

    filenames: list[str] = []
    for src in _VENDOR_SRC_PATTERN.findall(html):
        cleaned = src.strip()
        if not cleaned.startswith(VENDOR_SRC_PREFIX):
            raise ValidationError(
                f"script src 仅允许引用 {VENDOR_SRC_PREFIX} 下的白名单运行时: {cleaned!r}",
            )
        filename = cleaned[len(VENDOR_SRC_PREFIX) :]
        if filename not in _LIBS_BY_FILENAME:
            raise ValidationError(f"未收录的动画运行时: {filename!r}")
        if filename not in filenames:
            filenames.append(filename)
    return filenames


def _verify_vendor_file(lib: VendorLib, path: Path) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    key = str(path)
    with _verified_lock:
        cached = _verified_cache.get(key)
    if cached == (stat.st_mtime, stat.st_size):
        return True
    if stat.st_size != lib.size_bytes:
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != lib.sha256:
        return False
    with _verified_lock:
        _verified_cache[key] = (stat.st_mtime, stat.st_size)
    return True


def resolve_vendor_files(filenames: list[str]) -> dict[str, str]:
    """Map vendor filename -> verified absolute path, or raise clearly."""

    resolved: dict[str, str] = {}
    root = vendor_root()
    for filename in filenames:
        lib = _LIBS_BY_FILENAME.get(filename)
        if lib is None:
            raise ValidationError(f"未收录的动画运行时: {filename!r}")
        path = root / lib.filename
        if not _verify_vendor_file(lib, path):
            raise ValidationError(
                f"动画运行时 {lib.name} 未安装或校验失败，请运行 "
                "`python -m services.media_files.motion_engine fetch` 安装",
            )
        resolved[filename] = str(path)
    return resolved


def engine_digest(filenames: list[str]) -> str:
    """Salt covering every out-of-document render input for ``html_js``.

    Composed from the protocol version, the prelude bytes and the pinned
    hashes of each referenced vendor runtime, so upgrading any of them
    invalidates cached frames and render fingerprints automatically.
    """

    parts = [
        f"protocol:{MOTION_ENGINE_PROTOCOL_VERSION}",
        f"prelude:{MOTION_PRELUDE_SHA256}",
    ]
    for filename in sorted(set(filenames)):
        lib = _LIBS_BY_FILENAME.get(filename)
        if lib is None:
            raise ValidationError(f"未收录的动画运行时: {filename!r}")
        parts.append(f"lib:{lib.name}:{lib.sha256}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def full_engine_digest() -> str:
    """Engine salt over every registered vendor runtime.

    Used by render fingerprints, where the externalized document body is
    not loaded: any vendor or prelude upgrade must invalidate every
    ``html_js`` render even without knowing which libs one doc references.
    """

    return engine_digest(sorted(_LIBS_BY_FILENAME))


def _fetch_all() -> int:
    """CLI helper: download and verify every registered vendor runtime."""

    from urllib.request import urlopen

    root = vendor_root()
    root.mkdir(parents=True, exist_ok=True)
    failures = 0
    for lib in VENDOR_LIBS.values():
        target = root / lib.filename
        if _verify_vendor_file(lib, target):
            print(f"ok        {lib.name} ({lib.filename})")
            continue
        try:
            with urlopen(lib.source_url, timeout=60) as response:
                payload = response.read()
        except OSError as error:
            print(f"fetch-err {lib.name}: {error}")
            failures += 1
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest != lib.sha256 or len(payload) != lib.size_bytes:
            print(f"pin-miss  {lib.name}: digest {digest} != {lib.sha256}")
            failures += 1
            continue
        target.write_bytes(payload)
        print(f"fetched   {lib.name} ({lib.filename}, {len(payload)} bytes)")
    return failures


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 2 and sys.argv[1] == "fetch":
        raise SystemExit(_fetch_all())
    print("usage: python -m services.media_files.motion_engine fetch")
    raise SystemExit(2)
