# -*- coding: utf-8 -*-
"""qwenpawmail-mcp: MCP server for NetEase (163/126/yeah.net)
and QQ (qq.com/foxmail.com) mailboxes.

Exposes 17 MCP tools over IMAP/SMTP. The create_mailbox tool guides users
through registering a new mailbox account (username validation, random
name generation, step-by-step provider-specific instructions and the
authorization-code setup flow). Registration itself must be completed
manually in a browser due to SMS verification requirements.

Runtime credential management tools (set_credentials, get_credential_status,
clear_credentials) let MCP clients provide mailbox credentials during a
conversation, so QWENPAWMAIL_EMAIL/QWENPAWMAIL_AUTH_CODE no longer need to
be configured via env.
"""

__version__ = "0.1.0"
