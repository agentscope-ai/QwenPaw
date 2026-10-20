# -*- coding: utf-8 -*-
"""Start a sidecar with only its explicitly granted environment."""

import json
import os
import runpy
import sys


def run_module(arguments, environment):
    """Run a sidecar module without replacing the supervised Windows PID."""
    if len(arguments) < 2 or arguments[0] != "-m":
        raise ValueError("Windows sidecars must use python -m <module>")
    inherited_paths = {
        os.path.abspath(path)
        for path in os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if path
    }
    os.environ.clear()
    os.environ.update(environment)
    # Match python -m lookup without retaining the launcher's directory or
    # the Host's PYTHONPATH in the isolated service interpreter.
    sys.path[:] = [os.getcwd()] + [
        path
        for path in sys.path[1:]
        if os.path.abspath(path) not in inherited_paths
    ]
    sys.argv = arguments[1:]
    runpy.run_module(arguments[1], run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as stream:
        service_environment = json.load(stream)
    if os.name == "nt":
        run_module(sys.argv[2:], service_environment)
    else:
        os.execve(
            sys.executable,
            [sys.executable, *sys.argv[2:]],
            service_environment,
        )
