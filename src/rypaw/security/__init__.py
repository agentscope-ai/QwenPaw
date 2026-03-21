# -*- coding: utf-8 -*-
"""
Security framework for CoPaw.

This package centralises all security-related mechanisms:

* **Tool-call guarding** (``copaw.security.tool_guard``)
  Pre-execution parameter scanning to detect dangerous tool usage
  patterns (command injection, data exfiltration, etc.).

Sub-modules are kept independent so each concern can evolve (or be
disabled) without affecting the others.  Import-time cost is near-zero
because heavy dependencies are lazily loaded inside each sub-module.
"""
