# -*- coding: utf-8 -*-
"""
飞书认证模块
"""

import threading
import time
from typing import Optional

import requests


class FeishuAuth:
    """飞书认证模块"""

    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    REQUEST_TIMEOUT = 30  # 请求超时（秒）

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: Optional[str] = None
        self._token_expiry: float = 0  # token 过期时间戳
        self._lock = threading.Lock()

    def get_token(self) -> str:
        """获取 tenant_access_token，支持过期自动刷新"""
        with self._lock:
            # 如果 token 存在且距离过期还有 60 秒以上，直接返回
            if self._token and time.time() + 60 < self._token_expiry:
                return self._token

            resp = requests.post(self.TOKEN_URL, json={
                "app_id": self.app_id,
                "app_secret": self.app_secret
            }, timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                raise Exception(f"获取 token 失败: {data.get('msg')}")

            self._token = data["tenant_access_token"]
            # 存储过期时间戳（expire 单位为秒）
            expires_in = data.get("expire", 7200)
            self._token_expiry = time.time() + expires_in
            return self._token
