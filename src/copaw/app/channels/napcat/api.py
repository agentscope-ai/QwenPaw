# -*- coding: utf-8 -*-
"""NapCat API calls."""

from typing import Any, Dict, List, Optional

import aiohttp

from .exceptions import NapCatApiError


async def api_request(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    access_token: str,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make HTTP API request to NapCat."""
    url = f"http://{host}:{port}{path}"
    headers = {"Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    kwargs: Dict[str, Any] = {"headers": headers}
    if body is not None:
        kwargs["json"] = body

    async with session.request(method, url, **kwargs) as resp:
        data = await resp.json()
        if resp.status >= 400:
            raise NapCatApiError(path=path, status=resp.status, data=data)
        # Check OneBot retcode and status
        retcode = data.get("retcode", 0)
        status = data.get("status", "ok")
        if retcode != 0 or status == "failed":
            msg = data.get("message") or data.get("wording", "Unknown error")
            raise NapCatApiError(
                path=path,
                status=resp.status,
                data=data,
                message=msg,
            )
        return data


async def send_group_message(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    access_token: str,
    group_id: str,
    message: Any,
    auto_escape: bool = True,
) -> int:
    """Send message to group.

    Returns:
        message_id on success
    """
    body = {
        "group_id": group_id,
        "message": message,
        "auto_escape": auto_escape,
    }
    result = await api_request(
        session,
        host,
        port,
        access_token,
        "POST",
        "/send_group_msg",
        body,
    )
    return (result.get("data") or {}).get("message_id", 0)


async def send_private_message(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    access_token: str,
    user_id: str,
    message: Any,
    auto_escape: bool = True,
) -> int:
    """Send private message.

    Returns:
        message_id on success
    """
    body = {
        "user_id": user_id,
        "message": message,
        "auto_escape": auto_escape,
    }
    result = await api_request(
        session,
        host,
        port,
        access_token,
        "POST",
        "/send_private_msg",
        body,
    )
    return (result.get("data") or {}).get("message_id", 0)


async def get_login_info(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    access_token: str,
) -> Dict[str, Any]:
    """Get login info."""
    result = await api_request(
        session,
        host,
        port,
        access_token,
        "POST",
        "/get_login_info",
        None,
    )
    return result.get("data", {})


async def get_group_list(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    access_token: str,
) -> List[Dict[str, Any]]:
    """Get group list."""
    result = await api_request(
        session,
        host,
        port,
        access_token,
        "POST",
        "/get_group_list",
        None,
    )
    return result.get("data", [])
