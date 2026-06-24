# -*- coding: utf-8 -*-
"""Rate limiting utilities for authentication endpoints."""
import time
from collections import defaultdict, deque
from typing import Dict, Deque, Tuple, Optional


class LoginRateLimiter:
    """In-memory rate limiter for login attempts
    to prevent brute-force attacks."""

    def __init__(self):
        # Track login attempts by IP address: {ip: [(timestamp, success), ...]}
        self.ip_attempts: Dict[str, Deque[tuple]] = defaultdict(
            lambda: deque(maxlen=100),
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

        # Configuration
        self.max_attempts_per_minute = (
            10  # Max attempts per minute per IP/user
        )
        self.lock_duration = 15 * 60  # Lock duration in seconds (15 minutes)
        self.max_attempts_before_lock = (
            5  # Lock after this many failed attempts
        )

    def _cleanup_old_attempts(self, attempts_deque: Deque[tuple]) -> None:
        """Remove attempts older than 1 minute."""
        cutoff_time = time.time() - 60  # 60 seconds
        while attempts_deque and attempts_deque[0][0] < cutoff_time:
            attempts_deque.popleft()

    def is_ip_limited(self, ip_address: str) -> bool:
        """Check if an IP is currently rate-limited or locked."""
        # Check if IP is locked
        if ip_address in self.locked_ips:
            if time.time() < self.locked_ips[ip_address]:
                return True
            else:
                # Lock expired, remove from locked list
                del self.locked_ips[ip_address]

        # Clean up old attempts
        self._cleanup_old_attempts(self.ip_attempts[ip_address])

        # Count recent attempts
        recent_attempts = len(self.ip_attempts[ip_address])
        return recent_attempts >= self.max_attempts_per_minute

    def is_user_limited(self, username: str) -> bool:
        """Check if a user is currently rate-limited or locked."""
        # Check if user is locked
        if username in self.locked_users:
            if time.time() < self.locked_users[username]:
                return True
            else:
                # Lock expired, remove from locked list
                del self.locked_users[username]

        # Clean up old attempts
        self._cleanup_old_attempts(self.user_attempts[username])

        # Count recent attempts
        recent_attempts = len(self.user_attempts[username])
        return recent_attempts >= self.max_attempts_per_minute

    def record_login_attempt(
        self,
        ip_address: str,
        username: str,
        success: bool,
    ) -> None:
        """Record a login attempt."""
        timestamp = time.time()

        # Record attempt for IP
        self.ip_attempts[ip_address].append((timestamp, success))

        # Record attempt for user
        self.user_attempts[username].append((timestamp, success))

        # If login failed, check if we need to lock the IP or user
        if not success:
            # Count failed attempts in last minute for IP
            self._cleanup_old_attempts(self.ip_attempts[ip_address])
            recent_failed_attempts_ip = len(
                [
                    ts_success
                    for ts, ts_success in self.ip_attempts[ip_address]
                    if not ts_success
                ],
            )

            # Count failed attempts in last minute for user
            self._cleanup_old_attempts(self.user_attempts[username])
            recent_failed_attempts_user = len(
                [
                    ts_success
                    for ts, ts_success in self.user_attempts[username]
                    if not ts_success
                ],
            )

            # Lock if too many failed attempts
            if recent_failed_attempts_ip >= self.max_attempts_before_lock:
                self.locked_ips[ip_address] = timestamp + self.lock_duration

            if recent_failed_attempts_user >= self.max_attempts_before_lock:
                self.locked_users[username] = timestamp + self.lock_duration

    def get_remaining_attempts(
        self,
        ip_address: str,
        username: str,
    ) -> tuple[int, int]:
        """Get remaining attempts for IP and user."""
        # Clean up old attempts
        self._cleanup_old_attempts(self.ip_attempts[ip_address])
        self._cleanup_old_attempts(self.user_attempts[username])

        ip_remaining = max(
            0,
            self.max_attempts_per_minute - len(self.ip_attempts[ip_address]),
        )
        user_remaining = max(
            0,
            self.max_attempts_per_minute - len(self.user_attempts[username]),
        )

        return ip_remaining, user_remaining

    def get_lock_info(
        self,
        ip_address: str,
        username: str,
    ) -> Tuple[
        bool,
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[int],
    ]:
        """
        Get detailed lock information.

        Returns:
        - bool: Whether the entity is locked
        - Optional[int]: Seconds until IP unlock (or None if not locked)
        - Optional[int]: Failed IP attempts remaining until lock
        - Optional[int]: Seconds until user unlock (or None if not locked)
        - Optional[int]: Failed user attempts remaining until lock
        """
        # Check IP lock status
        ip_locked_until = None
        if ip_address in self.locked_ips:
            remaining_time = int(self.locked_ips[ip_address] - time.time())
            if remaining_time > 0:
                ip_locked_until = remaining_time
            else:
                del self.locked_ips[ip_address]  # Clean up expired lock

        # Check user lock status
        user_locked_until = None
        if username in self.locked_users:
            remaining_time = int(self.locked_users[username] - time.time())
            if remaining_time > 0:
                user_locked_until = remaining_time
            else:
                del self.locked_users[username]  # Clean up expired lock

        # Calculate attempts remaining until lock
        self._cleanup_old_attempts(self.ip_attempts[ip_address])
        recent_failed_attempts_ip = len(
            [
                ts_success
                for ts, ts_success in self.ip_attempts[ip_address]
                if not ts_success
            ],
        )
        ip_attempts_until_lock = max(
            0,
            self.max_attempts_before_lock - recent_failed_attempts_ip,
        )

        self._cleanup_old_attempts(self.user_attempts[username])
        recent_failed_attempts_user = len(
            [
                ts_success
                for ts, ts_success in self.user_attempts[username]
                if not ts_success
            ],
        )
        user_attempts_until_lock = max(
            0,
            self.max_attempts_before_lock - recent_failed_attempts_user,
        )

        return (
            bool(ip_locked_until or user_locked_until),
            ip_locked_until,
            ip_attempts_until_lock,
            user_locked_until,
            user_attempts_until_lock,
        )


# Global rate limiter instance
rate_limiter = LoginRateLimiter()
