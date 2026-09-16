import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { MCPClientInfo } from "../../../api/types";

const hoisted = vi.hoisted(() => {
  const messageMock = {
    success: vi.fn(),
    error: vi.fn(),
  };
  const apiMocks = {
    listMCPClients: vi.fn(),
    createMCPClient: vi.fn(),
    updateMCPClient: vi.fn(),
    toggleMCPClient: vi.fn(),
    deleteMCPClient: vi.fn(),
    updateMCPPolicy: vi.fn(),
  };
  // A stable translation function so useCallback dependencies don't change on
  // every render and trigger an infinite loadClients loop via useEffect.
  const stableT = (k: string) => k;
  const agentState = { selectedAgent: "agent-1", agents: [] as any[] };
  const scopeState = { current: true };
  const scope = {
    get agentId() {
      return agentState.selectedAgent;
    },
    ready: true,
    get canEdit() {
      return (
        agentState.agents.find(
          (agent: any) => agent.id === agentState.selectedAgent,
        )?.can_edit !== false
      );
    },
    signal: new AbortController().signal,
    current: () => scopeState.current,
  };
  const harnessMocks = { listMCP: vi.fn() };
  return { messageMock, apiMocks, harnessMocks, stableT, agentState, scopeState, scope };
});

vi.mock("../../../api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => hoisted.agentState,
}));

vi.mock("../../../api/skillScope", () => ({
  useSkillScope: () => hoisted.scope,
}));
vi.mock("../../../api/modules/harness", () => ({
  harnessApi: hoisted.harnessMocks,
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.messageMock }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: hoisted.stableT }),
}));

import { useMCP } from "./useMCP";

const { messageMock, apiMocks, harnessMocks, agentState, scopeState } = hoisted;

function makeClient(overrides: Partial<MCPClientInfo> = {}): MCPClientInfo {
  return {
    key: "client-1",
    name: "Client One",
    description: "desc",
    command: "cmd",
    enabled: false,
    transport: "stdio",
    ...overrides,
  } as MCPClientInfo;
}

describe("useMCP", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listMCPClients.mockReset();
    apiMocks.createMCPClient.mockReset();
    apiMocks.updateMCPClient.mockReset();
    apiMocks.toggleMCPClient.mockReset();
    apiMocks.deleteMCPClient.mockReset();
    apiMocks.updateMCPPolicy.mockReset();
    harnessMocks.listMCP.mockReset();
    messageMock.success.mockReset();
    messageMock.error.mockReset();

    apiMocks.listMCPClients.mockResolvedValue([]);
    agentState.selectedAgent = "agent-1";
    agentState.agents = [{ id: "agent-1", can_edit: true }];
    scopeState.current = true;
  });

  it("mounts and calls listMCPClients, sets clients, loading true->false", async () => {
    const clients = [makeClient(), makeClient({ key: "client-2" })];
    apiMocks.listMCPClients.mockResolvedValue(clients);

    const { result } = renderHook(() => useMCP());

    await waitFor(() => {
      expect(result.current.clients).toEqual(clients);
    });
    expect(result.current.loading).toBe(false);
    expect(apiMocks.listMCPClients).toHaveBeenCalledTimes(1);
  });

  it("message.error('mcp.loadError') when loadClients fails", async () => {
    apiMocks.listMCPClients.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useMCP());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(messageMock.error).toHaveBeenCalledWith("mcp.loadError");
  });

  it("createClient success: calls createMCPClient with client_key + client, message.success, returns true", async () => {
    apiMocks.createMCPClient.mockResolvedValue(undefined);
    const { result } = renderHook(() => useMCP());
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: boolean | undefined;
    await act(async () => {
      ret = await result.current.createClient("my-key", {
        name: "My",
        command: "run",
      });
    });

    expect(apiMocks.createMCPClient).toHaveBeenCalledWith(
      {
        client_key: "my-key",
        client: { name: "My", command: "run" },
      },
      expect.objectContaining({ agentId: "agent-1" }),
    );
    expect(messageMock.success).toHaveBeenCalledWith("mcp.createSuccess");
    expect(ret).toBe(true);
  });

  it("createClient failure with error.message: message.error receives error.message, returns false", async () => {
    apiMocks.createMCPClient.mockRejectedValue(new Error("dup key"));
    const { result } = renderHook(() => useMCP());
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: boolean | undefined;
    await act(async () => {
      ret = await result.current.createClient("k", {
        name: "N",
        command: "c",
      });
    });

    expect(messageMock.error).toHaveBeenCalledWith("dup key");
    expect(ret).toBe(false);
  });

  it("createClient failure without error.message: message.error receives 'mcp.createError'", async () => {
    apiMocks.createMCPClient.mockRejectedValue({});
    const { result } = renderHook(() => useMCP());
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: boolean | undefined;
    await act(async () => {
      ret = await result.current.createClient("k", {
        name: "N",
        command: "c",
      });
    });

    expect(messageMock.error).toHaveBeenCalledWith("mcp.createError");
    expect(ret).toBe(false);
  });

  it("updateClient success: calls updateMCPClient, message.success('mcp.updateSuccess'), returns true", async () => {
    apiMocks.updateMCPClient.mockResolvedValue(undefined);
    const { result } = renderHook(() => useMCP());
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: boolean | undefined;
    await act(async () => {
      ret = await result.current.updateClient("client-1", { name: "Renamed" });
    });

    expect(apiMocks.updateMCPClient).toHaveBeenCalledWith(
      "client-1",
      { name: "Renamed", expected_revision: undefined },
      expect.objectContaining({ agentId: "agent-1" }),
    );
    expect(messageMock.success).toHaveBeenCalledWith("mcp.updateSuccess");
    expect(ret).toBe(true);
  });

  it("toggleEnabled on enabled client: message.success('mcp.disableSuccess')", async () => {
    apiMocks.toggleMCPClient.mockResolvedValue(undefined);
    const { result } = renderHook(() => useMCP());
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.toggleEnabled(makeClient({ enabled: true }));
    });

    expect(apiMocks.toggleMCPClient).toHaveBeenCalledWith(
      "client-1",
      undefined,
      expect.objectContaining({ agentId: "agent-1" }),
    );
    expect(messageMock.success).toHaveBeenCalledWith("mcp.disableSuccess");
  });

  it("deleteClient success: message.success('mcp.deleteSuccess')", async () => {
    apiMocks.deleteMCPClient.mockResolvedValue(undefined);
    const { result } = renderHook(() => useMCP());
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.deleteClient(makeClient());
    });

    expect(apiMocks.deleteMCPClient).toHaveBeenCalledWith(
      "client-1",
      undefined,
      expect.objectContaining({ agentId: "agent-1" }),
    );
    expect(messageMock.success).toHaveBeenCalledWith("mcp.deleteSuccess");
  });

  it("includes the loaded revision and explicit keep actions when updating", async () => {
    const client = makeClient({
      revision: 12,
      credential_fields: { headers: ["Authorization"], env: ["API_KEY"] },
    });
    apiMocks.listMCPClients.mockResolvedValue([client]);
    apiMocks.updateMCPClient.mockResolvedValue(undefined);
    const { result } = renderHook(() => useMCP());
    await waitFor(() => expect(result.current.clients).toEqual([client]));

    await act(() =>
      result.current.updateClient("client-1", {
        name: "Renamed",
        credential_updates: {
          headers: { Authorization: { action: "keep" } },
          env: { API_KEY: { action: "keep" } },
        },
      }, 12),
    );

    expect(apiMocks.updateMCPClient).toHaveBeenCalledWith(
      "client-1",
      expect.objectContaining({ expected_revision: 12 }),
      expect.objectContaining({ agentId: "agent-1" }),
    );
  });

  it("does not mutate configuration when the current actor is read-only", async () => {
    agentState.agents = [{ id: "agent-1", can_edit: false }];
    const { result } = renderHook(() => useMCP());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const updated = await result.current.updateClient("client-1", {
      name: "blocked",
    });

    expect(updated).toBe(false);
    expect(apiMocks.updateMCPClient).not.toHaveBeenCalled();
  });

  it("discards a list response after the captured actor or Agent changes", async () => {
    let resolveList!: (clients: MCPClientInfo[]) => void;
    apiMocks.listMCPClients.mockReturnValue(
      new Promise((resolve) => {
        resolveList = resolve;
      }),
    );
    const { result } = renderHook(() => useMCP());

    scopeState.current = false;
    resolveList([makeClient({ key: "stale-client" })]);

    await act(async () => Promise.resolve());
    expect(result.current.clients).toEqual([]);
  });

  it("silently discards a stale Provider discovery failure", async () => {
    let rejectProvider!: (error: Error) => void;
    harnessMocks.listMCP.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectProvider = reject;
      }),
    );
    agentState.agents = [{
      id: "agent-1",
      can_edit: true,
      backend: "provider",
      backend_capabilities: { provider_mcp_discovery: true },
    }];
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    renderHook(() => useMCP());
    await waitFor(() => expect(harnessMocks.listMCP).toHaveBeenCalled());

    scopeState.current = false;
    rejectProvider(new Error("old request"));
    await act(async () => Promise.resolve());

    expect(warn).not.toHaveBeenCalled();
  });
});
