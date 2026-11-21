# -*- coding: utf-8 -*-
"""Rate limiting utilities for authentication endpoints."""
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from math import ceil
from typing import Dict, Deque


@dataclass(frozen=True)
class LoginLockStatus:
    locked: bool
    failed_attempts: int
    remaining_attempts: int
    retry_after_seconds: int


class LoginRateLimiter:
    """In-memory rate limiter for login attempts
    to prevent brute-force attacks."""

    def __init__(self):
        # Track login attempts
        self.ip_attempts: Dict[str, Deque[tuple]] = defaultdict(
            lambda: deque(maxlen=300),
        )

        # Track locked IPs: {ip: unlock_timestamp}
        self.locked_ips: Dict[str, float] = {}

        # Track login attempts by username:
        # {username: [(timestamp, success), ...]}
        self.user_attempts: Dict[str, Deque[tuple]] = defaultdict(
            lambda: deque(maxlen=100),
        )

        # Track locked users: {username: unlock_timestamp}
        self.locked_users: Dict[str, float] = {}

        # Configuration - Account dimension
        self.user_max_failed_attempts = 5  # Lock account after 5 failures
        self.user_lock_duration = 15 * 60  # 15 minutes

        # Configuration - IP dimension
        self.ip_max_failed_per_minute = 50  # Rule 1: Max failed attempts
        self.ip_max_total_per_minute = 200  # Rule 2: Max total requests
        self.ip_max_usernames_per_minute = 30  # Rule 3: Max unique usernames
        self.ip_lock_duration = 15 * 60  # 15 minutes

    def _cleanup_old_attempts(self, attempts_deque: Deque[tuple]) -> None:
        """Remove attempts older than 1 minute."""
        cutoff_time = time.time() - 60  # 60 seconds
        while attempts_deque and attempts_deque[0][0] < cutoff_time:
            attempts_deque.popleft()

    def is_ip_locked(self, ip_address: str) -> bool:
        """Check if an IP is currently locked."""
        if ip_address in self.locked_ips:
            if time.time() < self.locked_ips[ip_address]:
                return True
            else:
                # Lock expired, remove from locked list
                del self.locked_ips[ip_address]
        return False

    def is_ip_rate_limited(self, ip_address: str) -> bool:
        """Check if an IP violates any of the three rate limiting rules."""
        # Clean up old attempts
        self._cleanup_old_attempts(self.ip_attempts[ip_address])

        attempts = list(self.ip_attempts[ip_address])
        if not attempts:
            return False

        # Rule 1: Check failed attempts count
        failed_count = sum(1 for _, success, _ in attempts if not success)
        if failed_count >= self.ip_max_failed_per_minute:
            return True

        # Rule 2: Check total request frequency
        total_count = len(attempts)
        if total_count >= self.ip_max_total_per_minute:
            return True

        # Rule 3: Check unique usernames count
        unique_usernames = set(username for _, _, username in attempts)
        if len(unique_usernames) >= self.ip_max_usernames_per_minute:
            return True

        return False

    def is_ip_limited(self, ip_address: str) -> bool:
        """Check if an IP is currently rate-limited or locked."""
        return self.is_ip_locked(ip_address) or self.is_ip_rate_limited(
            ip_address,
        )

    def is_user_locked(self, username: str) -> bool:
        """Check if a user account is locked due to failed login attempts."""
        return self.user_status(username).locked

    def user_status(self, username: str) -> LoginLockStatus:
        """Return the same normalized account state used by login and admin UI."""
        username = username.strip()
        now = time.time()
        if username in self.locked_users:
            if now >= self.locked_users[username]:
                del self.locked_users[username]
        retry_after = max(0, ceil(self.locked_users.get(username, now) - now))
        attempts = self.user_attempts.get(username)
        if attempts is not None:
            self._cleanup_old_attempts(attempts)
        failed = sum(1 for _, success in attempts or () if not success)
        return LoginLockStatus(
            locked=retry_after > 0,
            failed_attempts=failed,
            remaining_attempts=0 if retry_after else max(
                0, self.user_max_failed_attempts - failed
            ),
            retry_after_seconds=retry_after,
        )

    def ip_retry_after_seconds(self, ip_address: str) -> int:
        """Return the IP protection delay without exposing any other account."""
        if self.is_ip_locked(ip_address):
            return max(1, ceil(self.locked_ips[ip_address] - time.time()))
        attempts = self.ip_attempts.get(ip_address)
        if attempts:
            self._cleanup_old_attempts(attempts)
        if attempts and self.is_ip_rate_limited(ip_address):
            return max(1, ceil(attempts[0][0] + 60 - time.time()))
        return 0

    def record_login_attempt(
        self,
        ip_address: str,
        username: str,
        success: bool,
    ) -> None:
        """Record a login attempt."""
        username = username.strip()
        self.user_status(username)
        timestamp = time.time()

        # Record attempt for IP (with username for tracking unique accounts)
        self.ip_attempts[ip_address].append((timestamp, success, username))

        # Record attempt for user
        self.user_attempts[username].append((timestamp, success))

        if success:
            # On successful login, clear failed attempts for this user
            self._cleanup_old_attempts(self.user_attempts[username])
            self.user_attempts[username] = deque(
                [
                    (ts, succ)
                    for ts, succ in self.user_attempts[username]
                    if succ
                ],
                maxlen=100,
            )
            # Remove user lock if exists
            self.locked_users.pop(username, None)
        else:
            # On failed login, check if we need to lock the user
            self._cleanup_old_attempts(self.user_attempts[username])
            recent_failed_attempts_user = sum(
                1 for _, succ in self.user_attempts[username] if not succ
            )

            # Lock user account if too many failed attempts
            if recent_failed_attempts_user >= self.user_max_failed_attempts:
                # In-flight failed requests must not extend an existing lock.
                self.locked_users.setdefault(
                    username, timestamp + self.user_lock_duration
                )

            # Check if IP should be locked based on rate limiting rules
            if self.is_ip_rate_limited(ip_address):
                self.locked_ips[ip_address] = timestamp + self.ip_lock_duration

    def clear_user_failed_attempts(self, username: str) -> None:
        """Clear failed login attempts for a user."""
        username = username.strip()
        self._cleanup_old_attempts(self.user_attempts[username])
        self.user_attempts[username] = deque(
            [(ts, succ) for ts, succ in self.user_attempts[username] if succ],
            maxlen=100,
        )
        self.locked_users.pop(username, None)


# Global rate limiter instance
rate_limiter = LoginRateLimiter()
