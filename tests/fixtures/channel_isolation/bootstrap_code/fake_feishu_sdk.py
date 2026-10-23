# -*- coding: utf-8 -*-
"""Fake Feishu SDK that writes to ordinary stdout during import."""

from __future__ import annotations

import os


print("feishu-sdk-print")
os.write(1, b"feishu-sdk-fd1\n")


SDK_READY = True
