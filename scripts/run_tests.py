#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local test runner script for CoPaw project.

Usage:
    python scripts/run_tests.py [OPTIONS]

Options:
    -u, --unit [DIR]      Run unit tests (optionally specify subdirectory)
    -i, --integrated      Run integrated tests
    -a, --all             Run all tests (default)
    -c, --coverage        Generate coverage report
    -p, --parallel        Run tests in parallel
    -h, --help            Show this help message

Examples:
    python scripts/run_tests.py                    # Run all tests
    python scripts/run_tests.py -u                 # Run all unit tests
    python scripts/run_tests.py -u providers       # Run unit tests in providers
    python scripts/run_tests.py -i                 # Run integrated tests
    python scripts/run_tests.py -a -c              # Run all tests with coverage
    python scripts/run_tests.py -p                 # Run tests in parallel
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional


class Colors:
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
    """Check if pytest is installed."""
    try:
        subprocess.run(
            ["pytest", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def run_unit_tests(
    project_root: Path,
    subdir: Optional[str] = None,
    coverage: bool = False,
    parallel: bool = False,
) -> int:
    """Run unit tests."""
    if subdir:
        # Run specific subdirectory
        test_path = project_root / "tests" / "unit" / subdir
        if not test_path.is_dir():
            print_error(f"Unit test directory not found: {test_path}")
            return 1

        print_info(f"Running unit tests in: {subdir}")
        return_code = run_pytest(test_path, coverage, parallel)
        if return_code == 0:
            print_success(f"Unit tests in {subdir} completed")
        return return_code
    else:
        # Run all unit test subdirectories
        print_info("Running all unit tests...")
        unit_dir = project_root / "tests" / "unit"

        if not unit_dir.is_dir():
            print_warning("Unit test directory not found: tests/unit")
            return 0

        subdirs = [d for d in unit_dir.iterdir() if d.is_dir()]
        if not subdirs:
            print_warning("No unit test subdirectories found")
            return 0

        overall_return_code = 0
        for test_dir in subdirs:
            dirname = test_dir.name
            print_info(f"Running unit tests in: {dirname}")
            return_code = run_pytest(test_dir, coverage, parallel)
            if return_code == 0:
                print_success(f"Unit tests in {dirname} completed")
            else:
                overall_return_code = return_code
            print()

        return overall_return_code


def run_integrated_tests(
    project_root: Path,
    coverage: bool = False,
    parallel: bool = False,
) -> int:
    """Run integrated tests."""
    print_info("Running integrated tests...")
    integrated_dir = project_root / "tests" / "integrated"

    if not integrated_dir.is_dir():
        print_warning("Integrated test directory not found: tests/integrated")
        return 0

    # Check if there are any Python test files
    test_files = list(integrated_dir.glob("*.py"))
    if not test_files:
        print_warning("No integrated test files found in tests/integrated")
        return 0

    return_code = run_pytest(integrated_dir, coverage, parallel)
    if return_code == 0:
        print_success("Integrated tests completed")
    return return_code


def run_pytest(
    test_path: Path,
    coverage: bool = False,
    parallel: bool = False,
) -> int:
    """Run pytest with specified options."""
    cmd = ["pytest", "-v", str(test_path)]

    if coverage:
        cmd.extend(
            [
                "--cov=src/copaw",
                "--cov-report=html",
                "--cov-report=term-missing",
            ],
        )

    if parallel:
        cmd.extend(["-n", "auto"])

    try:
        result = subprocess.run(cmd, cwd=test_path.parents[2], check=True)
        return result.returncode
    except subprocess.CalledProcessError as e:
        return e.returncode


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="CoPaw test runner",
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
        help="Run integrated tests",
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
        print('  pip install -e ".[dev,full]"')
        return 1

    # Determine what to run
    run_all = args.all or (args.unit is None and not args.integrated)

    print()
    print_info("CoPaw Test Runner")
    print("=================")
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
        integrated_code = run_integrated_tests(
            project_root,
            coverage=args.coverage,
            parallel=args.parallel,
        )
        return_code = unit_code or integrated_code
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
    if args.coverage:
        print_success(
            "Test run completed! Coverage report generated in htmlcov/index.html",
        )
    else:
        print_success("Test run completed!")
    print()

    return return_code


if __name__ == "__main__":
    sys.exit(main())
