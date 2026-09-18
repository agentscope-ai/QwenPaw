"""A connected HTTP transport must apply credentials rotated after init."""

import pytest

from qwenpaw.drivers.capabilities import DriverInvocation, format_capability_id
from qwenpaw.drivers.contracts import CredentialRef, DriverCard, PolicyRule
from qwenpaw.drivers.credentials.providers import CredentialProvider
from qwenpaw.drivers.credentials.types import ResolvedCredential
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler


class RotatingProvider(CredentialProvider):
    token = "initial-token"

    async def resolve(self):
        return ResolvedCredential(
            kind="oauth2_auth_code", secrets={"access_token": self.token}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport,client_class",
    [
        ("streamable_http", "HttpAutoClient"),
        ("sse", "HttpStatefulClient"),
    ],
)
async def test_rotated_token_reloads_connected_http_before_invocation(
    monkeypatch,
    transport,
    client_class,
):
    events = []

    class Client:
        def __init__(self, **kwargs):
            self.headers = kwargs["headers"]

        async def connect(self):
            events.append(("connect", dict(self.headers)))

        async def reload(self):
            events.append(("reload", dict(self.headers)))

        async def close(self, **kwargs):
            pass

        async def call_tool(self, name, arguments):
            events.append(("call", dict(self.headers)))
            return {"ok": True}

    monkeypatch.setattr(f"qwenpaw.drivers.handlers.mcp.{client_class}", Client)
    provider = RotatingProvider()
    card = DriverCard(
        "rotating",
        "mcp",
        {"transport": transport, "url": "http://localhost/mcp"},
        credentials={"oauth": CredentialRef("oauth2_auth_code", "test")},
        policy=[PolicyRule(subject="*", effect="allow")],
    )
    handler = MCPDriverHandler(card, provider, {"oauth": provider})
    await handler.init()
    provider.token = "refreshed-token"
    invocation = DriverInvocation(
        format_capability_id("mcp", "rotating", "tool", "invoke", "echo"), {}
    )
    result = await handler.invoke_capability(invocation)
    assert result.ok
    assert events == [
        ("connect", {"Authorization": "Bearer initial-token"}),
        ("reload", {"Authorization": "Bearer refreshed-token"}),
        ("call", {"Authorization": "Bearer refreshed-token"}),
    ]
    await handler.invoke_capability(invocation)
    assert sum(event == "reload" for event, _ in events) == 1
    await handler.shutdown()
