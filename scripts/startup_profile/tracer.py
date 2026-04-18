#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Function execution tracer for QwenPaw."""
import json
import time
import traceback
from collections import defaultdict


class ExecTracer:
    """Trace function execution in qwenpaw package."""

    def __init__(self, package_names=None):
        """Initialize tracer.

        Args:
            package_names: List of package prefixes to trace
        """
        if package_names is None:
            package_names = ["qwenpaw"]
        self.package_names = package_names
        self.call_stack = []
        self.function_times = defaultdict(list)
        self.call_sequence = []
        self.start_times = {}
        self.execution_order = []
        self.call_depth = 0
        self.sequence_counter = 0

    def trace_calls(  # pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks
        self,
        frame,
        event,
        arg,
    ):
        """Trace function calls."""
        module_name = frame.f_globals.get("__name__", "")

        # Filter by package names
        if self.package_names:
            should_trace = module_name == "__main__" or any(
                module_name.startswith(pkg + ".") or module_name == pkg
                for pkg in self.package_names
            )
            if not should_trace:
                return self.trace_calls

        co = frame.f_code
        func_name = co.co_name
        filename = co.co_filename

        # Build descriptive name
        class_name = "global"
        if "self" in frame.f_locals:
            instance = frame.f_locals["self"]
            try:
                for cls in type(instance).__mro__:
                    if (
                        hasattr(cls, func_name)
                        and getattr(
                            cls,
                            func_name,
                        ).__code__
                        is co
                    ):
                        class_name = cls.__name__
                        break
                if class_name == "global":
                    class_name = type(instance).__name__
            except (AttributeError, TypeError):
                class_name = type(instance).__name__

        descriptive_name = f"{module_name}.{class_name}.{func_name}"

        if event == "call":
            current_time = time.time()
            self.sequence_counter += 1
            self.call_stack.append(descriptive_name)
            self.start_times[descriptive_name] = current_time
            self.call_depth += 1

            # Get caller info
            caller_frame = frame.f_back
            caller_name = None
            if caller_frame:
                caller_co = caller_frame.f_code
                caller_func = caller_co.co_name
                caller_module = caller_frame.f_globals.get("__name__", "")
                caller_class = "global"
                if "self" in caller_frame.f_locals:
                    caller_instance = caller_frame.f_locals["self"]
                    try:
                        for cls in type(caller_instance).__mro__:
                            if (
                                hasattr(cls, caller_func)
                                and getattr(
                                    cls,
                                    caller_func,
                                ).__code__
                                is caller_co
                            ):
                                caller_class = cls.__name__
                                break
                        if caller_class == "global":
                            caller_class = type(caller_instance).__name__
                    except (AttributeError, TypeError):
                        caller_class = "global"
                caller_name = f"{caller_module}.{caller_class}.{caller_func}"

            call_info = {
                "sequence": self.sequence_counter,
                "function": descriptive_name,
                "enter_time": current_time * 1000,
                "exit_time": None,
                "duration": None,
                "depth": self.call_depth,
                "lineno": frame.f_lineno,
                "filename": filename,
                "parent": caller_name,
            }
            self.call_sequence.append(call_info)
            self.execution_order.append(call_info)

        elif event == "return":
            if self.call_stack:
                func_name = self.call_stack.pop()
                end_time = time.time()
                duration = end_time - self.start_times.get(func_name, end_time)
                self.call_depth -= 1
                self.function_times[func_name].append(duration)

                for call_info in reversed(self.call_sequence):
                    if (
                        call_info["function"] == func_name
                        and call_info["exit_time"] is None
                    ):
                        call_info["exit_time"] = end_time * 1000
                        call_info["duration"] = duration * 1000
                        break

        elif event == "exception":
            exception_type, exception_value, tb = arg
            if self.call_stack:
                func_name = self.call_stack[-1]
                for call_info in reversed(self.call_sequence):
                    if call_info["function"] == func_name:
                        call_info["exception"] = {
                            "type": str(exception_type.__name__),
                            "value": str(exception_value),
                            "traceback": "\n".join(traceback.format_tb(tb)),
                        }
                        break

        return self.trace_calls

    def generate_json(self, output_path):
        """Generate JSON report.

        Args:
            output_path: Path to save JSON file
        """
        completed_events = [
            event
            for event in self.execution_order
            if event["enter_time"] is not None
            and event["exit_time"] is not None
        ]

        if completed_events:
            earliest_start = min(
                event["enter_time"] for event in completed_events
            )
            latest_end = max(event["exit_time"] for event in completed_events)
            total_time = latest_end - earliest_start
        else:
            total_time = 0

        json_data = {
            "metadata": {
                "package_names": self.package_names,
                "total_events": len(self.execution_order),
                "total_functions": len(self.function_times),
                "max_depth": max(
                    [call["depth"] for call in self.execution_order] + [0],
                ),
                "total_time": total_time,
                "generated_at": time.time(),
            },
            "execution_order": self.execution_order,
            "function_times": dict(self.function_times),
            "call_sequence": self.call_sequence,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, default=str)


def main():
    """Run tracer on qwenpaw app import."""
    import sys  # pylint: disable=reimported,redefined-outer-name

    if len(sys.argv) < 2:
        print("Usage: python tracer.py <output_json>")
        sys.exit(1)

    output_path = sys.argv[1]

    tracer = ExecTracer(package_names=["qwenpaw"])
    sys.settrace(tracer.trace_calls)

    try:
        # Import qwenpaw app to trigger startup
        from qwenpaw.app._app import (  # pylint: disable=unused-import
            app,
        )  # noqa: F401
    finally:
        sys.settrace(None)
        tracer.generate_json(output_path)
        print(f"Trace saved to: {output_path}")


if __name__ == "__main__":
    main()
