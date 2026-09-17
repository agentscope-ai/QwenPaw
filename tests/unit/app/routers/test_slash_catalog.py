# -*- coding: utf-8 -*-
"""Web 斜杠菜单必须公开后端已经支持的记忆命令。"""

from qwenpaw.app.routers.slash import _command_items


def test_memory_commands_are_advertised_in_slash_catalog() -> None:
    commands = {item.command for item in _command_items(plan_enabled=False)}

    assert {"/dream", "/memorize", "/reme_status"} <= commands
