/**
 * mcp.ts - request contract layer for the MCP client / tool / OAuth surface.
 *
 * Sibling coverage note: ./mcp.test.ts already pins the two access-policy
 * endpoints (getMCPPolicy and updateMCPPolicy) including a full policy body.
 * This file deliberately covers the twelve wrappers that file leaves out, so
 * the two do not duplicate each other:
 *   - client CRUD: listMCPClients / getMCPClient / createMCPClient /
 *     updateMCPClient / toggleMCPClient / deleteMCPClient
 *   - tool discovery and whitelist: listMCPTools / updateMCPToolWhitelist
 *   - access principals: listMCPAccessPrincipals
 *   - the OAuth 2.1 PKCE trio: startOAuth / getOAuthStatus / revokeOAuth
 *
 * Three details are pinned here because a silent change to any of them would
 * not be caught elsewhere:
 *   - toggleMCPClient uses PATCH, the only verb of its kind in api/modules,
 *     and sends no body at all.
 *   - updateMCPToolWhitelist wraps its argument in { tools } and accepts
 *     null, which must serialise to {"tools":null} rather than disappear.
 *   - the read-only wrappers call request with exactly one argument; passing
 *     an options object would be a contract change, so the single-argument
 *     form is asserted rather than merely tolerated.
 *
 * Assertions are on path / method / body - the frontend contract - never on
 * backend behaviour.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { mcpApi } from "./mcp";

vi.mock("../request", () => ({ request: vi.fn() }));

import { request } from "../request";

/** Every stub resolves to this, so each case also pins value pass-through. */
const SENTINEL = { __passthrough: true } as never;

function stubRequest(): void {
  vi.mocked(request).mockResolvedValue(SENTINEL);
}

afterEach(() => {
  vi.clearAllMocks();
  vi.mocked(request).mockReset();
});

describe("mcpApi client listing and lookup", () => {
  it("lists clients from the collection root without an options object", async () => {
    stubRequest();

    const out = await mcpApi.listMCPClients();

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp");
    expect(out).toBe(SENTINEL);
  });

  it("gets one client by key", async () => {
    stubRequest();

    const out = await mcpApi.getMCPClient("local_stdio_echo");

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp/local_stdio_echo");
    expect(out).toBe(SENTINEL);
  });

  it("percent-encodes a client key containing a space", async () => {
    stubRequest();

    await mcpApi.getMCPClient("my client");

    expect(request).toHaveBeenCalledWith("/mcp/my%20client");
  });

  it("percent-encodes a client key containing a slash", async () => {
    stubRequest();

    await mcpApi.getMCPClient("team/echo");

    expect(request).toHaveBeenCalledWith("/mcp/team%2Fecho");
  });

  it("percent-encodes a non-ASCII client key", async () => {
    stubRequest();

    await mcpApi.getMCPClient("回声");

    expect(request).toHaveBeenCalledWith("/mcp/%E5%9B%9E%E5%A3%B0");
  });
});

describe("mcpApi client writes", () => {
  it("creates a client with POST and a JSON body", async () => {
    stubRequest();

    const body = {
      client_key: "remote_http",
      client: {
        name: "Remote HTTP",
        enabled: true,
        transport: "streamable_http" as const,
        url: "https://example.com/mcp",
      },
    };
    const out = await mcpApi.createMCPClient(body);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp", {
      method: "POST",
      body: JSON.stringify(body),
    });
    expect(out).toBe(SENTINEL);
  });

  it("updates a client with PUT against the keyed path", async () => {
    stubRequest();

    const body = { name: "Renamed", enabled: false };
    const out = await mcpApi.updateMCPClient("local_stdio_echo", body);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp/local_stdio_echo", {
      method: "PUT",
      body: JSON.stringify(body),
    });
    expect(out).toBe(SENTINEL);
  });

  it("encodes the client key in the update path but not in the body", async () => {
    stubRequest();

    await mcpApi.updateMCPClient("a b/c", { name: "a b/c" });

    expect(request).toHaveBeenCalledWith("/mcp/a%20b%2Fc", {
      method: "PUT",
      body: JSON.stringify({ name: "a b/c" }),
    });
  });

  it("toggles a client with PATCH and no body", async () => {
    stubRequest();

    const out = await mcpApi.toggleMCPClient("local_stdio_echo");

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp/toggle/local_stdio_echo", {
      method: "PATCH",
    });
    expect(out).toBe(SENTINEL);
  });

  it("keeps the toggle verb as PATCH rather than PUT or POST", async () => {
    stubRequest();

    await mcpApi.toggleMCPClient("k");

    const opts = vi.mocked(request).mock.calls[0][1] as { method?: string };
    expect(opts.method).toBe("PATCH");
    expect(Object.keys(opts)).toEqual(["method"]);
  });

  it("encodes the client key in the toggle path", async () => {
    stubRequest();

    await mcpApi.toggleMCPClient("team/echo v2");

    expect(request).toHaveBeenCalledWith("/mcp/toggle/team%2Fecho%20v2", {
      method: "PATCH",
    });
  });

  it("deletes a client with DELETE and no body", async () => {
    stubRequest();

    const out = await mcpApi.deleteMCPClient("local_stdio_echo");

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp/local_stdio_echo", {
      method: "DELETE",
    });
    expect(out).toBe(SENTINEL);
  });
});

describe("mcpApi tools and access principals", () => {
  it("lists tools from the tools sub-collection", async () => {
    stubRequest();

    const out = await mcpApi.listMCPTools("local_stdio_echo");

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp/tools/local_stdio_echo");
    expect(out).toBe(SENTINEL);
  });

  it("encodes the client key in the tools path", async () => {
    stubRequest();

    await mcpApi.listMCPTools("a/b c");

    expect(request).toHaveBeenCalledWith("/mcp/tools/a%2Fb%20c");
  });

  it("lists access principals from a fixed path", async () => {
    stubRequest();

    const out = await mcpApi.listMCPAccessPrincipals();

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp/access-principals");
    expect(out).toBe(SENTINEL);
  });

  it("replaces the tool whitelist with PUT and a wrapped body", async () => {
    stubRequest();

    const out = await mcpApi.updateMCPToolWhitelist("local_stdio_echo", [
      "echo",
      "ping",
    ]);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp/tools/local_stdio_echo", {
      method: "PUT",
      body: JSON.stringify({ tools: ["echo", "ping"] }),
    });
    expect(out).toBe(SENTINEL);
  });

  it("sends a single-item whitelist as a one element array", async () => {
    stubRequest();

    await mcpApi.updateMCPToolWhitelist("k", ["echo"]);

    expect(request).toHaveBeenCalledWith("/mcp/tools/k", {
      method: "PUT",
      body: JSON.stringify({ tools: ["echo"] }),
    });
  });

  it("sends an empty whitelist as an empty array, not as null", async () => {
    stubRequest();

    await mcpApi.updateMCPToolWhitelist("k", []);

    expect(request).toHaveBeenCalledWith("/mcp/tools/k", {
      method: "PUT",
      body: '{"tools":[]}',
    });
  });

  it("serialises a null whitelist explicitly as tools null", async () => {
    stubRequest();

    await mcpApi.updateMCPToolWhitelist("k", null);

    expect(request).toHaveBeenCalledWith("/mcp/tools/k", {
      method: "PUT",
      body: '{"tools":null}',
    });
  });

  it("encodes the client key when replacing the whitelist", async () => {
    stubRequest();

    await mcpApi.updateMCPToolWhitelist("a b", ["echo"]);

    expect(request).toHaveBeenCalledWith("/mcp/tools/a%20b", {
      method: "PUT",
      body: JSON.stringify({ tools: ["echo"] }),
    });
  });

  it("keeps non-ASCII tool names intact in the JSON body", async () => {
    stubRequest();

    await mcpApi.updateMCPToolWhitelist("k", ["回声", "ping"]);

    const opts = vi.mocked(request).mock.calls[0][1] as { body?: string };
    expect(JSON.parse(opts.body ?? "")).toEqual({ tools: ["回声", "ping"] });
  });
});

describe("mcpApi OAuth flow", () => {
  it("starts OAuth with POST against the keyed start path", async () => {
    stubRequest();

    const body = {
      url: "https://example.com/mcp",
      scope: "read write",
      client_id: "pre-registered",
    };
    const out = await mcpApi.startOAuth("remote_http", body);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp/oauth/start/remote_http", {
      method: "POST",
      body: JSON.stringify(body),
    });
    expect(out).toBe(SENTINEL);
  });

  it("starts OAuth with a minimal body when optional fields are omitted", async () => {
    stubRequest();

    await mcpApi.startOAuth("remote_http", { url: "https://example.com/mcp" });

    expect(request).toHaveBeenCalledWith("/mcp/oauth/start/remote_http", {
      method: "POST",
      body: '{"url":"https://example.com/mcp"}',
    });
  });

  it("passes overridden discovery endpoints through verbatim", async () => {
    stubRequest();

    const body = {
      url: "https://example.com/mcp",
      auth_endpoint: "https://idp.example.com/authorize",
      token_endpoint: "https://idp.example.com/token",
    };
    await mcpApi.startOAuth("remote_http", body);

    const opts = vi.mocked(request).mock.calls[0][1] as { body?: string };
    expect(JSON.parse(opts.body ?? "")).toEqual(body);
  });

  it("encodes the client key in the OAuth start path", async () => {
    stubRequest();

    await mcpApi.startOAuth("a/b c", { url: "https://example.com/mcp" });

    expect(request).toHaveBeenCalledWith("/mcp/oauth/start/a%2Fb%20c", {
      method: "POST",
      body: '{"url":"https://example.com/mcp"}',
    });
  });

  it("reads OAuth status from the keyed status path", async () => {
    stubRequest();

    const out = await mcpApi.getOAuthStatus("remote_http");

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp/oauth/status/remote_http");
    expect(out).toBe(SENTINEL);
  });

  it("revokes OAuth tokens with DELETE against the bare oauth path", async () => {
    stubRequest();

    const out = await mcpApi.revokeOAuth("remote_http");

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/mcp/oauth/remote_http", {
      method: "DELETE",
    });
    expect(out).toBe(SENTINEL);
  });

  it("keeps the revoke path distinct from the status and start paths", async () => {
    stubRequest();

    await mcpApi.revokeOAuth("k");
    await mcpApi.getOAuthStatus("k");
    await mcpApi.startOAuth("k", { url: "https://example.com/mcp" });

    const paths = vi.mocked(request).mock.calls.map((c) => c[0]);
    expect(paths).toEqual([
      "/mcp/oauth/k",
      "/mcp/oauth/status/k",
      "/mcp/oauth/start/k",
    ]);
  });

  it("encodes the client key in the revoke path", async () => {
    stubRequest();

    await mcpApi.revokeOAuth("a b/c");

    expect(request).toHaveBeenCalledWith("/mcp/oauth/a%20b%2Fc", {
      method: "DELETE",
    });
  });
});
