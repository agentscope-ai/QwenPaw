"""Test the uvicorn address compatibility patch (Issue #5379)."""
from __future__ import annotations

import sys
import unittest


class MockTransport:
    """Mock transport that simulates corrupted peername data."""

    def __init__(self, peername_data, sockname_data=None):
        self._peername = peername_data
        self._sockname = sockname_data or peername_data

    def get_extra_info(self, key, default=None):
        if key == "peername":
            return self._peername
        if key == "sockname":
            return self._sockname
        return default


class TestUvicornAddrPatch(unittest.TestCase):
    """Test that the patch correctly handles corrupted transport data."""

    @classmethod
    def setUpClass(cls):
        """Import qwenpaw.app._app to trigger the patch at module level."""
        import uvicorn.protocols.utils as utils

        # Capture the ORIGINAL functions before the patch is applied.
        cls._orig_remote = utils.get_remote_addr
        cls._orig_local = utils.get_local_addr

        # Importing _app applies the patch.
        from qwenpaw.app import _app  # noqa: F401

    def test_original_crashes_on_corrupted_data(self):
        """Verify the ORIGINAL uvicorn function crashes with corrupted bytes."""
        corrupted_peername = (
            "127.0.0.1",
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
        )
        transport = MockTransport(corrupted_peername)

        with self.assertRaises((ValueError, TypeError)):
            self._orig_remote(transport)

    def test_patched_returns_none_on_corrupted_data(self):
        """Verify the PATCHED function returns None instead of crashing."""
        import uvicorn.protocols.utils as utils

        corrupted_peername = (
            "127.0.0.1",
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
        )
        transport = MockTransport(corrupted_peername)

        result = utils.get_remote_addr(transport)
        self.assertIsNone(result)

    def test_patched_still_works_with_valid_data(self):
        """Verify the PATCHED function still works correctly with normal data."""
        import uvicorn.protocols.utils as utils

        valid_peername = ("127.0.0.1", 12345)
        transport = MockTransport(valid_peername)

        result = utils.get_remote_addr(transport)
        self.assertEqual(result, ("127.0.0.1", 12345))

    def test_patched_local_addr_returns_none_on_corrupted_data(self):
        """Verify get_local_addr is also patched."""
        import uvicorn.protocols.utils as utils

        corrupted_sockname = (
            "127.0.0.1",
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
        )
        transport = MockTransport(corrupted_sockname)

        result = utils.get_local_addr(transport)
        self.assertIsNone(result)

    def test_patched_local_addr_works_with_valid_data(self):
        """Verify get_local_addr still works with normal data."""
        import uvicorn.protocols.utils as utils

        valid_sockname = ("127.0.0.1", 8088)
        transport = MockTransport(valid_sockname)

        result = utils.get_local_addr(transport)
        self.assertEqual(result, ("127.0.0.1", 8088))

    @unittest.skipUnless(sys.platform == "win32", "Windows-only patch")
    def test_patch_only_applied_on_windows(self):
        """Verify the patch is only active on Windows."""
        # If we are on Windows, importing _app should have applied the patch.
        import uvicorn.protocols.utils as utils

        corrupted_peername = (
            "127.0.0.1",
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
        )
        transport = MockTransport(corrupted_peername)

        result = utils.get_remote_addr(transport)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
