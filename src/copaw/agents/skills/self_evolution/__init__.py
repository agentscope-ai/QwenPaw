# -*- coding: utf-8 -*-
"""
Self-Evolution Module - 自我进化引擎

让 AI Agent 具有自我进化能力，自动从错误中学习，持续改进。
"""
from .error_catcher import (
    ErrorCatcher,
    ErrorCategory,
    register_error,
    catch_errors,
)
from .pattern_detector import PatternDetector, detect_patterns
from .ai_attributor import AIAttributor, attribute_error
from .dashboard import EvolutionDashboard, generate_report

__all__ = [
    "ErrorCatcher",
    "ErrorCategory",
    "register_error",
    "catch_errors",
    "PatternDetector",
    "detect_patterns",
    "AIAttributor",
    "attribute_error",
    "EvolutionDashboard",
    "generate_report",
]


def session_startup_check() -> dict:
    """会话启动检查 - 每次会话启动时自动运行"""
    from .session_check import run_session_check

    return run_session_check()


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="Self-Evolution Engine")
    parser.add_argument(
        "command",
        choices=["session_startup", "detect_patterns", "dashboard"],
        help="Command to run",
    )
    args = parser.parse_args()

    if args.command == "session_startup":
        result = session_startup_check()
        print(result)
    elif args.command == "detect_patterns":
        detector = PatternDetector()
        patterns = detector.detect()
        print(f"Found {len(patterns)} patterns")
    elif args.command == "dashboard":
        dashboard = EvolutionDashboard()
        report = dashboard.generate_report()
        print(report)


if __name__ == "__main__":
    main()