# -*- coding: utf-8 -*-
"""Nextcloud Files API client for accessing shared files."""


import base64
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import aiohttp

logger = logging.getLogger(__name__)

# PROPFIND XML body for getting file properties
_PROPFIND_BODY = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:"
           xmlns:nc="http://nextcloud.org/ns"
           xmlns:oc="http://owncloud.org/ns">
    <d:prop>
        <d:getlastmodified/>
        <d:getcontentlength/>
        <d:getcontenttype/>
        <d:resourcetype/>
        <oc:id/>
        <oc:owner-id/>
        <oc:owner-display-name/>
        <nc:has-preview/>
    </d:prop>
</d:propfind>"""


class NextcloudFilesClient:
    """
    Client for Nextcloud Files API (WebDAV).

    Used to access file metadata and download links for files shared in Talk.
    """

    def __init__(self, base_url: str, username: str = "", password: str = ""):
        """
        Initialize Nextcloud Files client.

        Args:
            base_url: Base URL of Nextcloud server
            (e.g., https://example.com/nextcloud)
            username: Username for authentication (optional for public shares)
            password: Password or app token for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

    def build_webdav_url(self, api_user: str, file_path: str) -> Optional[str]:
        """
        Build a WebDAV download URL for a Nextcloud file.

        Uses the format: {base_url}/remote.php/dav/files/{api_user}/{file_path}
        Following OpenClaw PR #29256 implementation.

        Args:
            api_user: API username for the bot account
            file_path: File path relative to user's files root (e.g., Talk/image.jpg)  # noqa: E501

        Returns:
            WebDAV URL or None if parameters are insufficient

        Example:
            >>> client.build_webdav_url("bot-user", "Talk/image.jpg")
            'https://cloud.example.com/nextcloud/remote.php/dav/files/bot-user/Talk/image.jpg'
        """
        if not self.base_url or not api_user or not file_path:
            return None

        # Normalize base URL
        base_url = self.base_url.rstrip("/")

        # Encode file path: split by "/" and encode each segment
        # This ensures spaces and special characters are properly encoded
        encoded_path_segments = [
            quote(segment) for segment in file_path.split("/")
        ]
        encoded_path = "/".join(encoded_path_segments)

        # Encode the username
        encoded_user = quote(api_user)

        # Build WebDAV URL
        webdav_url = (
            f"{base_url}/remote.php/dav/files/{encoded_user}/{encoded_path}"
        )

        return webdav_url

    def _prepare_download_request(self, url: str) -> tuple:
        """Prepare authentication and headers for download request."""
        # Check if this is a Nextcloud URL that needs auth
        is_share_url = "/s/" in url
        is_webdav_url = "/remote.php/dav/files/" in url
        needs_auth = (
            (is_share_url or is_webdav_url) and self.username and self.password
        )

        logger.info(
            "Nextcloud download auth: is_share=%s, is_webdav=%s, "
            "needs_auth=%s, username=%s...",
            is_share_url,
            is_webdav_url,
            needs_auth,
            self.username[:2] if self.username else "N/A",
        )

        # Create authentication
        auth = (
            aiohttp.BasicAuth(self.username, self.password)
            if self.username and self.password
            else None
        )
        headers = {}

        # For share URLs, we need to add Authorization header manually
        if needs_auth and is_share_url:
            credentials = f"{self.username}:{self.password}"
            encoded_credentials = base64.b64encode(
                credentials.encode("utf-8"),
            ).decode("ascii")
            headers["Authorization"] = f"Basic {encoded_credentials}"
            logger.info(
                "Added Authorization header for share URL download",
            )
        elif needs_auth and is_webdav_url:
            logger.info("Using session BasicAuth for WebDAV URL download")

        return auth, headers, needs_auth

    def _validate_downloaded_content(self, content: bytes, url: str) -> bool:
        """Validate downloaded content to ensure it's not an error page."""
        # Verify content is not HTML (login page)
        if content.startswith(b"<!DOCTYPE") or content.startswith(
            b"<html",
        ):
            logger.error(
                "Downloaded content is HTML (login page), "
                "not binary file: url=%s",
                url,
            )
            logger.error(
                "First 500 bytes of content: %s",
                content[:500],
            )
            return False

        # Check for XML error responses
        if content.startswith(b"<?xml"):
            logger.error(
                "Downloaded content is XML (likely error): url=%s",
                url,
            )
            logger.error(
                "First 500 bytes of XML content: %s",
                content[:500],
            )
            return False

        return True

    def _validate_image_signature(self, content: bytes, url: str) -> bool:
        """Validate image file signatures for image files."""
        png_sig = b"\x89PNG\r\n\x1a\n"
        jpg_sig = b"\xff\xd8\xff"
        gif_sig = b"GIF8"
        webp_sig = b"RIFF"

        valid_image = (
            content.startswith(png_sig)
            or content.startswith(jpg_sig)
            or content.startswith(gif_sig)
            or content.startswith(webp_sig)
        )

        if not valid_image:
            logger.error(
                "Content doesn't match expected image format: url=%s",
                url,
            )
            logger.error(
                "Content starts with: %s",
                content[:20],
            )
            return False
        else:
            logger.info(
                "Valid image file signature confirmed for: %s",
                url,
            )
            return True

    async def download_file(self, url: str, local_path: str) -> bool:
        """
        Download file from URL to local path, handling Nextcloud authentication.  # noqa: E501

        For Nextcloud share URLs (/s/...) and WebDAV URLs, this method uses
        Basic Auth if credentials are available.

        Args:
            url: URL to download from
            local_path: Local file path to save to

        Returns:
            True if successful, False otherwise
        """
        logger.info(
            "NextcloudFilesClient.download_file: url=%s..., local_path=%s",
            url[:50],
            local_path,
        )

        try:
            logger.info(
                "Downloading file from Nextcloud: url=%s -> %s",
                url,
                local_path,
            )

            # Prepare request authentication and headers
            auth, headers, _ = self._prepare_download_request(url)
            logger.info("Making authenticated request to: %s", url)

            # Create new session per request to avoid event loop issues
            async with aiohttp.ClientSession(auth=auth) as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    logger.info("Response status: %s", resp.status)

                    if resp.status != 200:
                        resp_text = await resp.text()
                        logger.error(
                            "Failed to download file: status=%s, resp=%s",
                            resp.status,
                            resp_text[:500],
                        )

                        if resp.status == 401:
                            logger.error(
                                "401 Unauthorized - Authentication failed",
                            )
                        elif resp.status == 404:
                            logger.error("404 Not Found - File not found")
                        elif resp.status == 403:
                            logger.error("403 Forbidden - Access denied")

                        return False

                    # Download and validate content
                    content = await resp.read()
                    logger.info(
                        "Downloaded content size: %s bytes",
                        len(content),
                    )

                    # Validate content is not an error page
                    if not self._validate_downloaded_content(content, url):
                        return False

                    # Validate image file signatures if needed
                    if url.lower().endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".webp"),
                    ):
                        if not self._validate_image_signature(content, url):
                            return False

                    # Save to file
                    local_path_obj = Path(local_path)
                    local_path_obj.parent.mkdir(parents=True, exist_ok=True)
                    with open(local_path_obj, "wb") as f:
                        f.write(content)

                    logger.info(
                        "Successfully downloaded file to %s (%s bytes)",
                        local_path,
                        len(content),
                    )
                    return True

        except Exception as e:
            logger.exception("Error downloading file from Nextcloud: %s", e)
            return False


async def create_nextcloud_files_client(
    backend_url: str,
    username: str = "",
    password: str = "",
) -> NextcloudFilesClient:
    """
    Create a Nextcloud Files client instance.

    Args:
        backend_url: Nextcloud backend URL
        username: Optional username
        password: Optional password/token

    Returns:
        NextcloudFilesClient instance
    """
    return NextcloudFilesClient(backend_url, username, password)
