# -*- coding: utf-8 -*-
"""Lightweight network abuse protection for QwenPaw Hub."""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from .config import AccessSecurityConfig, RateLimitConfig

_IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class HubAccessSecurity:
    """Resolve client addresses and enforce configurable request limits."""

    def __init__(
        self,
        config: AccessSecurityConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._attempts: dict[tuple[str, str], deque[float]] = {}
        self._blocked_until: dict[tuple[str, str], float] = {}
        self.configure(config)

    def configure(self, config: AccessSecurityConfig) -> None:
        """Apply validated security settings without retaining stale blocks."""
        with self._lock:
            self._config = config
            self._blacklist = self._networks(config.ip_blacklist)
            self._trusted_proxies = self._networks(
                config.trusted_proxy_ips,
            )
            if hasattr(self, "_attempts"):
                self._attempts.clear()
                self._blocked_until.clear()

    def client_ip(self, request: Request) -> str:
        """Trust forwarding headers only from explicitly trusted proxies."""
        peer = request.client.host if request.client is not None else "0.0.0.0"
        if not self._contains(self._trusted_proxies, peer):
            return peer
        forwarded = request.headers.get("x-forwarded-for", "")
        for token in reversed(forwarded.split(",")):
            try:
                candidate = str(ipaddress.ip_address(token.strip()))
            except ValueError:
                return peer
            if not self._contains(self._trusted_proxies, candidate):
                return candidate
        return peer

    def is_blacklisted(self, address: str) -> bool:
        """Return whether an address belongs to a blocked network."""
        return self._contains(self._blacklist, address)

    def retry_after(self, action: str, address: str) -> int | None:
        """Return remaining block time when an action must be rejected."""
        policy = self._policy(action)
        if not policy.enabled:
            return None
        key = (action, address)
        now = self._clock()
        with self._lock:
            blocked_until = self._blocked_until.get(key, 0.0)
            if blocked_until > now:
                return max(1, math.ceil(blocked_until - now))
            if key in self._blocked_until:
                self._blocked_until.pop(key, None)
                self._attempts.pop(key, None)
                return None
            attempts = self._attempts.setdefault(key, deque())
            self._discard_expired(attempts, now, policy.window_seconds)
            if len(attempts) < policy.max_attempts:
                return None
            blocked_until = now + policy.block_seconds
            self._blocked_until[key] = blocked_until
            return policy.block_seconds

    def record_attempt(self, action: str, address: str) -> None:
        """Record an authentication attempt for one client address."""
        policy = self._policy(action)
        if not policy.enabled:
            return
        key = (action, address)
        now = self._clock()
        with self._lock:
            attempts = self._attempts.setdefault(key, deque())
            self._discard_expired(attempts, now, policy.window_seconds)
            attempts.append(now)

    def clear(self, action: str, address: str) -> None:
        """Clear failed attempts after successful authentication."""
        key = (action, address)
        with self._lock:
            self._attempts.pop(key, None)
            self._blocked_until.pop(key, None)

    def _policy(self, action: str) -> RateLimitConfig:
        if action == "login":
            return self._config.login_rate_limit
        if action == "registration":
            return self._config.registration_rate_limit
        raise ValueError(f"Unknown access security action: {action}")

    @staticmethod
    def _networks(values: list[str]) -> list[_IPNetwork]:
        return [ipaddress.ip_network(value, strict=False) for value in values]

    @staticmethod
    def _contains(
        networks: list[_IPNetwork],
        address: str,
    ) -> bool:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return False
        return any(parsed in network for network in networks)

    @staticmethod
    def _discard_expired(
        attempts: deque[float],
        now: float,
        window_seconds: int,
    ) -> None:
        threshold = now - window_seconds
        while attempts and attempts[0] <= threshold:
            attempts.popleft()
