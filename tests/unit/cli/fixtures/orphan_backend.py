# -*- coding: utf-8 -*-
"""Three generations with independent sessions and no delay after spawn."""

import signal
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path


def main(role, mode, delay, marker):
    if role == "leaf":
        sys.stdin.buffer.read()  # EOF when the middle worker exits.
        time.sleep(float(delay))
        marker.touch()
        return

    managed = mode == "sdk" or (mode == "mixed" and role == "backend")
    if managed:
        from qwenpaw.plugins.resources import ResourceOwner, ResourceScope
        from qwenpaw.process_ownership import backend_instance

        scope = ResourceScope(ResourceOwner("test", 1), lambda: None)
        spawn = scope.process
    else:
        spawn = subprocess.Popen
    child_role = "worker" if role == "backend" else "leaf"
    command = [
        sys.executable,
        __file__,
        child_role,
        mode,
        delay,
        str(marker),
    ]
    if role == "worker":
        print("ready", flush=True)
        sys.stdin.buffer.read()  # EOF when the backend exits.
        child = spawn(command, stdin=subprocess.PIPE, start_new_session=True)
        marker.with_suffix(".pid").write_text(str(child.pid))
        return

    with backend_instance() if managed else nullcontext():
        worker = spawn(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            start_new_session=True,
        )
        assert worker.stdout.readline().strip() == b"ready"
        print(worker.pid, flush=True)
        signal.pause()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]))
