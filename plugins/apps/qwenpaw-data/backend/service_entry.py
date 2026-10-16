# -*- coding: utf-8 -*-
"""Start a sidecar with only its explicitly granted environment."""

import json
import os
import sys

if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as stream:
        environment = json.load(stream)
    os.execve(sys.executable, [sys.executable, *sys.argv[2:]], environment)
