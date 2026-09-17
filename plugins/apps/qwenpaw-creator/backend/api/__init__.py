# -*- coding: utf-8 -*-
"""Creator HTTP package.

Composition roots import :mod:`api.router` explicitly.  Keeping this package
initializer side-effect free prevents an incidental ``import api`` (for
example, while loading one route module in a test) from composing the complete
HTTP surface or reviving the removed flat ``router`` module name.
"""
