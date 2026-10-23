"""Own one real legacy map lock until the test explicitly releases stdin."""

import fcntl
import os
from pathlib import Path
import sys

path, ready = map(Path, sys.argv[1:])
with path.open("a+b") as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    ready.write_text(str(os.getpid()))
    try:
        sys.stdin.buffer.read(1)
    finally:
        fcntl.flock(stream, fcntl.LOCK_UN)
