# -*- coding: utf-8 -*-
"""Runtime-only SDK dependencies and per-client connection HTTP settings."""

import json
import platform
import time

import requests
import aiohttp
import dingtalk_stream
from dingtalk_stream.version import VERSION_STRING
from dingtalk_stream.utils import DINGTALK_OPENAPI_ENDPOINT
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dingtalk.oauth2_1_0 import (
    client as dingtalk_oauth_client,
    models as dingtalk_oauth_models,
)
from alibabacloud_dingtalk.robot_1_0 import (
    client as dingtalk_robot_client,
    models as dingtalk_robot_models,
)
from alibabacloud_dingtalk.card_1_0 import (
    client as dingtalk_card_client,
    models as dingtalk_card_models,
)
from alibabacloud_tea_util import models as tea_util_models
from Tea.exceptions import TeaException, UnretryableException, RetryError

__all__ = [
    "open_api_models",
    "dingtalk_oauth_client",
    "dingtalk_oauth_models",
    "dingtalk_robot_client",
    "dingtalk_robot_models",
    "dingtalk_card_client",
    "dingtalk_card_models",
    "tea_util_models",
    "TeaException",
    "StreamClient",
]

# Older OpenAPI releases use Tea only. New releases wrap network failures in
# Dara RetryError; preserve compatibility with the declared OpenAPI >=0.4.4.
_NETWORK_ERRORS = (TimeoutError, aiohttp.ClientConnectionError, RetryError)
try:
    from darabonba.exceptions import RetryError as DaraRetryError
except ModuleNotFoundError as missing_dara:
    if missing_dara.name not in ("darabonba", "darabonba.exceptions"):
        raise
else:
    _NETWORK_ERRORS += (DaraRetryError,)


def raise_uncertain(error):
    """Unwrap the SDK's known transport envelope without guessing by text."""
    cause = (
        error.inner_exception
        if isinstance(error, UnretryableException)
        else error
    )
    if isinstance(cause, _NETWORK_ERRORS):
        raise TimeoutError("DingTalk delivery outcome is unknown") from error


_GroupDeliverModel = (
    dingtalk_card_models.DeliverCardRequestImGroupOpenDeliverModel
)
_RobotDeliverModel = (
    dingtalk_card_models.DeliverCardRequestImRobotOpenDeliverModel
)


class StreamClient(dingtalk_stream.DingTalkStreamClient):
    """Use the SDK wire format without mutating SDK modules or classes."""

    def __init__(self, credential, endpoint=""):
        super().__init__(credential)
        self._access_token = {}
        self.connection_error = None
        self.endpoint = endpoint or DINGTALK_OPENAPI_ENDPOINT
        self.OPEN_CONNECTION_API = (
            self.endpoint + "/v1.0/gateway/connections/open"
        )

    def open_connection(self):
        topics = (
            [{"type": "EVENT", "topic": "*"}]
            if self._is_event_required
            else []
        )
        topics.extend(
            {"type": "CALLBACK", "topic": topic}
            for topic in self.callback_handler_map
        )
        try:
            response = requests.post(
                self.OPEN_CONNECTION_API,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": f"DingTalkStream/1.0 SDK/{VERSION_STRING} "
                    f"Python/{platform.python_version()}",
                },
                data=json.dumps(
                    {
                        "clientId": self.credential.client_id,
                        "clientSecret": self.credential.client_secret,
                        "subscriptions": topics,
                        "ua": f"dingtalk-sdk-python/v{VERSION_STRING}-union",
                        "localIp": self.get_host_ip(),
                    },
                ).encode("utf-8"),
                timeout=(10, 30),
            )
            response.raise_for_status()
            self.connection_error = None
            return response.json()
        except Exception as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )
            self.connection_error = type(exc).__name__ + (
                f" (HTTP {status})" if status else ""
            )
            return None

    def get_access_token(self):
        if (
            self._access_token
            and time.time() < self._access_token["expireTime"]
        ):
            return self._access_token["accessToken"]
        response = requests.post(
            self.endpoint + "/v1.0/oauth2/accessToken",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            data=json.dumps(
                {
                    "appKey": self.credential.client_id,
                    "appSecret": self.credential.client_secret,
                },
            ),
            timeout=(10, 30),
        )
        response.raise_for_status()
        result = response.json()
        result["expireTime"] = int(time.time()) + result["expireIn"] - 300
        self._access_token = result
        return result["accessToken"]
