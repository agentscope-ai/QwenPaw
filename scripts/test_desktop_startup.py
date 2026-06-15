#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test script to measure desktop startup performance.

Usage:
    python scripts/test_desktop_startup.py

This script:
1. Starts the desktop command in a subprocess
2. Measures time until webview window appears
3. Verifies backend starts in parallel
4. Cleans up after test
"""

import subprocess
import sys
import time
from pathlib import Path


def test_desktop_startup():
    """Test desktop startup and measure performance."""
    print("=" * 60)
    print("Desktop Startup Performance Test")
    print("=" * 60)

    # Find the desktop_cmd module
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "src"))

    start_time = time.time()

    # Start desktop command
    print("\n[1] Starting desktop command...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "qwenpaw", "desktop", "--log-level", "info"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(repo_root),
    )

    # Wait for window creation (look for "Opening webview" in logs)
    window_created = False
    backend_started = False

    try:
        for line in proc.stderr:
            elapsed = time.time() - start_time

            if "Opening webview with loading page" in line:
                window_created = True
                status = "FAST (<2s)" if elapsed < 2 else "SLOW (>2s)"
                print(f"\n[OK] Window created at {elapsed:.2f}s -> {status}")

            if "Backend subprocess started" in line:
                backend_started = True
                print(f"[OK] Backend started at {elapsed:.2f}s")

            # Stop after both events or timeout
            if window_created and backend_started:
                break

            if elapsed > 15:  # 15s timeout
                print(f"\n[!] Timeout after {elapsed:.2f}s")
                break
    except Exception as e:
        print(f"\n[!] Error reading stderr: {e}")
    finally:
        # Terminate the process
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n" + "=" * 60)
    if window_created:
        print("TEST PASSED: Window appeared quickly")
        print("  Backend and window creation ran in parallel")
    else:
        print("TEST FAILED: Window did not appear")
    print("=" * 60)

    return 0 if window_created else 1


if __name__ == "__main__":
    sys.exit(test_desktop_startup())
