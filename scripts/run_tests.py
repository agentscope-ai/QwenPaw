#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local test runner script for QwenPaw project.

Usage:
    python scripts/run_tests.py [OPTIONS]

Options:
    -u, --unit [DIR]      Run unit tests (optionally specify subdirectory)
    -i, --integrated      Run integration tests (tests/integration)
    -a, --all             Run all tests (default)
    -c, --coverage        Generate coverage report
    -p, --parallel        Run tests in parallel
    -h, --help            Show this help message

Examples:
    python scripts/run_tests.py                    # Run all tests
    python scripts/run_tests.py -u                 # Run all unit tests
    python scripts/run_tests.py -u providers       # Run unit tests in providers
    python scripts/run_tests.py -i                 # Run integration tests
    python scripts/run_tests.py -a -c              # Run all tests with coverage
    python scripts/run_tests.py -p                 # Run tests in parallel

Notes:
    * The default ``-a`` run executes the complete ``tests/unit`` tree
      (root-level files included), ``tests/contract`` and
      ``tests/integration`` — the same tiers GitHub Actions runs.
    * A missing test suite directory is reported as an error with a
      nonzero exit status instead of being silently skipped.
    * Output is safe on terminals with limited encodings (for example
      CP936/GBK on Windows): unencodable status symbols are replaced
      instead of raising ``UnicodeEncodeError``.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _make_output_safe(stream) -> None:
    """Keep printing from crashing on limited terminal encodings.

    Windows consoles frequently use CP936/GBK; the Unicode status
    symbols below used to raise ``UnicodeEncodeError`` before the test
    outcome was reported.  Replacing unencodable characters keeps the
    runner usable there.
    """
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


_make_output_safe(sys.stdout)
_make_output_safe(sys.stderr)


class Colors:  # pylint: disable=too-few-public-methods
    """ANSI color codes for terminal output."""

    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"  # No Color


def print_info(message: str) -> None:
    """Print info message."""
    print(f"{Colors.BLUE}ℹ {message}{Colors.NC}")


def print_success(message: str) -> None:
    """Print success message."""
    print(f"{Colors.GREEN}✓ {message}{Colors.NC}")


def print_error(message: str) -> None:
    """Print error message."""
    print(f"{Colors.RED}✗ {message}{Colors.NC}")


def print_warning(message: str) -> None:
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠ {message}{Colors.NC}")


def check_pytest() -> bool:
    """Check that pytest is usable by the active interpreter."""
    try:
        subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def run_pytest(
    project_root: Path,
    test_path: Path,
    coverage: bool = False,
    parallel: bool = False,
) -> int:
    """Run pytest for ``test_path`` from the repository root.

    Running from the root lets pytest pick up the repository
    configuration (markers, timeouts, ...), and invoking pytest through
    ``sys.executable`` targets the active interpreter even when the
    ``pytest`` entry point is not on PATH.
    """
    cmd = [sys.executable, "-m", "pytest", "-v", str(test_path)]

    if coverage:
        cmd.extend(
            [
                "--cov=src/qwenpaw",
                "--cov-report=html",
                "--cov-report=term-missing",
            ],
        )

    if parallel:
        cmd.extend(["-n", "auto"])

    try:
        result = subprocess.run(cmd, cwd=project_root, check=True)
        return result.returncode
    except subprocess.CalledProcessError as e:
        return e.returncode


def run_unit_tests(
    project_root: Path,
    subdir: Optional[str] = None,
    coverage: bool = False,
    parallel: bool = False,
) -> int:
    """Run unit tests.

    Without ``subdir`` the complete ``tests/unit`` tree is executed in
    one pytest invocation, so files placed directly in ``tests/unit``
    are included as well.
    """
    if subdir:
        test_path = project_root / "tests" / "unit" / subdir
        if not test_path.is_dir():
            print_error(f"Unit test directory not found: {test_path}")
            return 1

        print_info(f"Running unit tests in: {subdir}")
        return_code = run_pytest(project_root, test_path, coverage, parallel)
        if return_code == 0:
            print_success(f"Unit tests in {subdir} completed")
        return return_code

    unit_dir = project_root / "tests" / "unit"
    if not unit_dir.is_dir():
        print_error("Unit test directory not found: tests/unit")
        return 1

    print_info("Running all unit tests...")
    return_code = run_pytest(project_root, unit_dir, coverage, parallel)
    if return_code == 0:
        print_success("Unit tests completed")
    return return_code


def run_contract_tests(
    project_root: Path,
    coverage: bool = False,
    parallel: bool = False,
) -> int:
    """Run contract tests (tests/contract)."""
    print_info("Running contract tests...")
    contract_dir = project_root / "tests" / "contract"
    if not contract_dir.is_dir():
        print_error("Contract test directory not found: tests/contract")
        return 1

    return_code = run_pytest(project_root, contract_dir, coverage, parallel)
    if return_code == 0:
        print_success("Contract tests completed")
    return return_code


def run_integrated_tests(
    project_root: Path,
    coverage: bool = False,
    parallel: bool = False,
) -> int:
    """Run integration tests (tests/integration).

    A missing directory is an error: silently returning success here
    used to mask the fact that no integration test ran at all.
    """
    print_info("Running integration tests...")
    integration_dir = project_root / "tests" / "integration"
    if not integration_dir.is_dir():
        print_error(
            "Integration test directory not found: tests/integration",
        )
        return 1

    return_code = run_pytest(
        project_root,
        integration_dir,
        coverage,
        parallel,
    )
    if return_code == 0:
        print_success("Integration tests completed")
    return return_code


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="QwenPaw test runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-u",
        "--unit",
        nargs="?",
        const="",
        metavar="DIR",
        help="Run unit tests (optionally specify subdirectory)",
    )
    parser.add_argument(
        "-i",
        "--integrated",
        action="store_true",
        help="Run integration tests (tests/integration)",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Run all tests (default)",
    )
    parser.add_argument(
        "-c",
        "--coverage",
        action="store_true",
        help="Generate coverage report",
    )
    parser.add_argument(
        "-p",
        "--parallel",
        action="store_true",
        help="Run tests in parallel (requires pytest-xdist)",
    )

    args = parser.parse_args()

    # Get project root
    script_path = Path(__file__).resolve()
    project_root = script_path.parents[1]

    # Check if pytest is installed
    if not check_pytest():
        print_error(
            "pytest is not installed. Please install dev dependencies:",
        )
        print('  pip install -e ".[dev,test,full]"')
        return 1

    # Determine what to run
    run_all = args.all or (args.unit is None and not args.integrated)

    print()
    print_info("QwenPaw Test Runner")
    print("===================")
    print()

    return_code = 0

    if run_all:
        print_info("Running all tests...")
        print()
        unit_code = run_unit_tests(
            project_root,
            coverage=args.coverage,
            parallel=args.parallel,
        )
        print()
        contract_code = run_contract_tests(
            project_root,
            coverage=args.coverage,
            parallel=args.parallel,
        )
        print()
        integrated_code = run_integrated_tests(
            project_root,
            coverage=args.coverage,
            parallel=args.parallel,
        )
        return_code = unit_code or contract_code or integrated_code
    elif args.unit is not None:
        return_code = run_unit_tests(
            project_root,
            subdir=args.unit if args.unit else None,
            coverage=args.coverage,
            parallel=args.parallel,
        )
    elif args.integrated:
        return_code = run_integrated_tests(
            project_root,
            coverage=args.coverage,
            parallel=args.parallel,
        )

    print()
    if return_code == 0:
        if args.coverage:
            print_success(
                "Test run completed! Coverage report generated in "
                "htmlcov/index.html",
            )
        else:
            print_success("All test suites completed successfully!")
    else:
        print_error(
            f"Test run finished with failures (exit code {return_code})",
        )
    print()

    return return_code


if __name__ == "__main__":
    sys.exit(main())
