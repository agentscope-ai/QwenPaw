#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QwenPaw Startup Performance Analyzer

Collects startup performance data and outputs JSON for visualization.
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def collect_import_time(output_dir):
    """Collect Python import time data."""
    print("📊 Collecting import time...")

    log_file = output_dir / "importtime.log"

    cmd = [
        sys.executable,
        "-X",
        "importtime",
        "-m",
        "qwenpaw",
        "app",
        "--help",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stderr + result.stdout

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"   ✓ {log_file.name}")
    return log_file


def collect_execution_trace(output_dir, script_dir):
    """Collect function execution trace using tracer module.

    Args:
        output_dir: Output directory for trace file
        script_dir: Script directory containing tracer.py

    Returns:
        Path to trace file or None if failed
    """
    print("🔍 Collecting execution trace...")

    trace_file = output_dir / "execution_trace.json"
    tracer_script = script_dir / "tracer.py"

    if not tracer_script.exists():
        print(f"   ⚠ {tracer_script.name} not found")
        return None

    # Run the tracer script
    try:
        subprocess.run(
            [sys.executable, str(tracer_script), str(trace_file)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        if trace_file.exists():
            print(f"   ✓ {trace_file.name}")
            return trace_file
        else:
            print("   ⚠ Not generated")
            return None
    except Exception as e:
        print(f"   ⚠ Skipped: {e}")
        return None


def parse_import_log(log_file):
    """Parse importtime log."""
    print("🔬 Parsing import data...")

    imports = []

    with open(log_file, encoding="utf-8") as f:
        for line in f:
            match = re.search(
                r"import time:\s+(\d+)\s+\|\s+(\d+)\s+\|\s+(.+)$",
                line,
            )
            if match:
                imports.append(
                    {
                        "package": match.group(3).strip(),
                        "self_ms": int(match.group(1)) / 1000,
                        "cumulative_ms": int(match.group(2)) / 1000,
                    },
                )

    # Filter QwenPaw and third-party
    qwenpaw = [i for i in imports if "qwenpaw" in i["package"]]
    third_party = [
        i
        for i in imports
        if not i["package"].startswith("_")
        and "." not in i["package"]
        and i["package"]
        not in ["io", "os", "sys", "time", "re", "abc", "typing"]
    ]

    qwenpaw.sort(key=lambda x: x["cumulative_ms"], reverse=True)
    third_party.sort(key=lambda x: x["cumulative_ms"], reverse=True)

    total_qwenpaw = sum(
        i["cumulative_ms"] for i in qwenpaw if i["package"].count(".") == 1
    )
    total_third_party = sum(i["cumulative_ms"] for i in third_party[:10])

    print(
        f"   ✓ {len(imports)} imports, {len(qwenpaw)} QwenPaw, {len(third_party)} third-party",
    )

    return {
        "qwenpaw_imports": qwenpaw,
        "third_party_imports": third_party,
        "summary": {
            "total_ms": total_qwenpaw + total_third_party,
            "total_qwenpaw_ms": total_qwenpaw,
            "total_third_party_ms": total_third_party,
        },
    }


def parse_execution_trace(trace_file):
    """Parse execution trace data."""
    if not trace_file or not trace_file.exists():
        return None

    print("🔬 Parsing execution trace...")

    try:
        with open(trace_file, encoding="utf-8") as f:
            data = json.load(f)

        functions = [
            {
                "function": func,
                "total_ms": sum(times) * 1000,
                "count": len(times),
                "avg_ms": sum(times) / len(times) * 1000,
            }
            for func, times in data["function_times"].items()
        ]
        functions.sort(key=lambda x: x["total_ms"], reverse=True)

        qwenpaw_funcs = [f for f in functions if "qwenpaw" in f["function"]]

        print(f"   ✓ {len(functions)} functions, {len(qwenpaw_funcs)} QwenPaw")

        return {
            "qwenpaw_functions": qwenpaw_funcs[:50],
            "metadata": data["metadata"],
            "execution_order": data["execution_order"],
        }
    except Exception as e:
        print(f"   ⚠ Parse failed: {e}")
        return None


def main():  # pylint: disable=too-many-statements
    """Main function."""
    print("=" * 60)
    print("🐾 QwenPaw Startup Performance Analyzer")
    print("=" * 60)
    print()

    # Use __file__ to get absolute path
    script_dir = Path(__file__).resolve().parent
    output_dir = script_dir / "output"
    output_dir.mkdir(exist_ok=True)

    start = time.time()

    # Collect data
    log_file = collect_import_time(output_dir)
    print()
    trace_file = collect_execution_trace(output_dir, script_dir)
    print()

    # Parse data
    import_data = parse_import_log(log_file)
    print()
    exec_data = parse_execution_trace(trace_file)
    print()

    # Generate report
    print("💾 Saving analysis.json...")

    report = {
        "generated_at": datetime.now().isoformat(),
        "import_analysis": import_data,
        "execution_analysis": exec_data,
    }

    with open(
        output_dir / "analysis.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("   ✓ analysis.json")
    print()

    # Copy viewer
    import shutil

    html_src = script_dir / "viewer.html"
    html_dst = output_dir / "report.html"

    if html_src.exists():
        shutil.copy(html_src, html_dst)
        print(f"📊 Report: {html_dst}")
        print()

        # Start HTTP server and open browser
        import threading
        import http.server
        import socketserver
        import webbrowser

        port = 8000
        # Use absolute path from __file__
        root_dir = Path(__file__).resolve().parent.parent.parent

        # Calculate relative path from root to report
        try:
            relative_report = html_dst.relative_to(root_dir)
            report_url = (
                f"http://localhost:{port}/{relative_report.as_posix()}"
            )
        except ValueError:
            # Fallback if paths are not relative
            report_url = f"http://localhost:{port}/scripts/startup_profile/output/report.html"

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(root_dir), **kwargs)

            def log_message(self, fmt, *args):
                pass  # Suppress server logs

        # Find available port
        httpd = None
        for attempt_port in range(port, port + 10):
            try:
                httpd = socketserver.TCPServer(("", attempt_port), Handler)
                port = attempt_port
                # Update URL with actual port
                try:
                    relative_report = html_dst.relative_to(root_dir)
                    report_url = (
                        f"http://localhost:{port}/{relative_report.as_posix()}"
                    )
                except ValueError:
                    report_url = (
                        f"http://localhost:{port}/"
                        "scripts/startup_profile/output/report.html"
                    )
                break
            except OSError:
                continue

        if httpd is None:
            print(
                "⚠ Could not find available port, please run manually:",
            )
            print(f"  cd {root_dir}")
            print("  python -m http.server 8000")
            return

        def run_server():
            httpd.serve_forever()

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        print(
            f"🌐 Server started at http://localhost:{port}/ (root: {root_dir.name})",
        )
        print(f"📊 Opening: {report_url}")
        print()
        print("Press Ctrl+C to stop the server")
        print()

        webbrowser.open(report_url)

        try:
            # Keep main thread alive
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n👋 Server stopped")

    print()
    print("=" * 60)
    print(f"✅ Done in {time.time() - start:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
