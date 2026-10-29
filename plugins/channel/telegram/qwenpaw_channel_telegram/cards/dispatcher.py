# -*- coding: utf-8 -*-
"""Instance-owned native approval dispatch, without host Agent execution."""


class TelegramCardHandler:
    def __init__(self, platform):
        self._platform = platform

    async def handle_callback_query(self, query):
        await self._platform._handle_callback(query)
