import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BUILTIN_ROUTES } from "../../../layouts/registry/builtinRoutes";
import { BUILTIN_MENU } from "../../../layouts/registry/builtinMenu";
import { menuRegistry, routeRegistry } from "../../../plugins/registry/store";
import { buildRouteNamespace } from "../../../plugins/registry/sdk";
import { removePluginRuntime } from "../../../plugins/pluginRuntimeCleanup";
import MCPPage from "./index";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  reload: vi.fn(),
  fetch: vi.fn(),
  agent: { selectedAgent: "one" },
  t: (key: string, options?: { defaultValue?: string }) =>
    options?.defaultValue ?? key,
}));
vi.mock("@agentscope-ai/design", async (original) => ({
  ...(await original<typeof import("@agentscope-ai/design")>()),
  // The global design test shim omits Select; keep the retained form valid.
  Select: ({
    value,
    options = [],
    onChange,
  }: {
    value?: string;
    options?: Array<{ value: string; label: string }>;
    onChange?: (value: string) => void;
  }) => (
    <select value={value} onChange={(event) => onChange?.(event.target.value)}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));
vi.mock("../../../api/request", () => ({ request: mocks.request }));
vi.mock("../../../plugins/usePluginLoader", () => ({
  reloadFrontendPlugin: mocks.reload,
}));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => mocks.agent,
}));
vi.mock("react-i18next", async (original) => ({
  ...(await original<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: mocks.t }),
}));
vi.mock("@/components/PageHeader", () => ({
  PageHeader: ({
    current,
    extra,
  }: {
    current: React.ReactNode;
    extra: React.ReactNode;
  }) => (
    <header>
      <h1>{current}</h1>
      {extra}
    </header>
  ),
}));
vi.mock("@/components/InlineHelp", () => ({ default: () => null }));
vi.mock("./useMCP", () => ({
  useMCP: () => ({
    agentId: mocks.agent.selectedAgent,
    ready: true,
    error: null,
    clients: [
      {
        key: "saved",
        name: "Saved offline server",
        enabled: false,
        transport: "stdio",
        command: "run",
      },
    ],
    providerServers: [],
    loading: false,
    toggleEnabled: vi.fn(),
    deleteClient: vi.fn(),
    createClient: vi.fn(),
    updateClient: vi.fn(),
    updatePolicy: vi.fn(),
    refreshClients: vi.fn(),
  }),
}));
vi.mock("./components", () => ({
  MCPClientCard: ({
    client,
    readOnly,
  }: {
    client: { name: string };
    readOnly: boolean;
  }) => (
    <article>
      {client.name}
      <button disabled={readOnly}>Saved server action</button>
    </article>
  ),
}));

const absent = {
  id: "qwenpaw-mcp",
  installed: false,
  enabled: false,
  status: "not_installed",
  diagnostics: [] as string[],
};
const active = { ...absent, installed: true, enabled: true, status: "active" };
const bundle = readFileSync(
  resolve(process.cwd(), "../plugins/protocol/mcp/frontend/dist/index.js"),
  "utf8",
);
let lifecycle = absent;

function mountActualPlugin() {
  // Execute the shipped inert bundle against the actual public registry API.
  // No private Console imports are provided to plugin code.
  new Function(bundle)();
}

function CurrentRoute() {
  const route = routeRegistry.snapshot().find(({ id }) => id === "core.mcp")!;
  const Component = route.Component;
  return (
    <MemoryRouter initialEntries={["/mcp"]}>
      <Routes>
        <Route path={route.path} element={<Component />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  routeRegistry.__resetForTests();
  menuRegistry.__resetForTests();
  routeRegistry.addBuiltin(BUILTIN_ROUTES);
  menuRegistry.addBuiltin(BUILTIN_MENU);
  routeRegistry.replace("test-page", "core.mcp", MCPPage);
  mocks.agent.selectedAgent = "one";
  lifecycle = absent;
  mocks.request.mockImplementation(async (path, init) => {
    if (path === "/mcp-plugin/install" && init?.method === "POST")
      lifecycle = active;
    return lifecycle;
  });
  mocks.fetch.mockImplementation(async (path, init) => {
    if (path.includes("/management"))
      return Response.json({
        plugin_id: "qwenpaw-mcp",
        workspace_id: mocks.agent.selectedAgent,
        capabilities: ["oauth"],
      });
    lifecycle =
      init?.method === "DELETE"
        ? absent
        : { ...active, enabled: false, status: "disabled" };
    return Response.json({ ok: true });
  });
  window.QwenPaw = {
    route: buildRouteNamespace(),
    host: {
      React,
      useSelectedAgent: () => ({ id: mocks.agent.selectedAgent }),
      useLocale: () => "en",
      fetch: mocks.fetch,
    },
  } as unknown as typeof window.QwenPaw;
  mocks.reload.mockImplementation(async () => mountActualPlugin());
});

describe("retained MCP route and actual plugin bundle", () => {
  it("deep link and navigation exist while absent, showing saved config readonly without loading the bundle", async () => {
    render(<CurrentRoute />);
    await screen.findByRole("button", { name: "Install" });
    expect(screen.getByText("Saved offline server")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Saved server action" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "mcp.create" })).toBeDisabled();
    expect(
      menuRegistry
        .snapshot()
        .some(({ id, route }) => id === "core.mcp" && route === "core.mcp"),
    ).toBe(true);
    expect(
      routeRegistry.snapshot().find(({ id }) => id === "core.mcp")?.path,
    ).toBe("/mcp");
    expect(mocks.reload).not.toHaveBeenCalled();
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(mocks.request.mock.calls.every(([, init]) => !init?.method)).toBe(
      true,
    );
  });

  it("install click mounts real management in the same route and uninstall restores initial shell", async () => {
    const view = render(<CurrentRoute />);
    fireEvent.click(await screen.findByRole("button", { name: "Install" }));
    await waitFor(() => expect(mocks.reload).toHaveBeenCalledOnce());
    view.rerender(<CurrentRoute />);
    await screen.findByRole("region", { name: "MCP plugin management" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Saved server action" }),
      ).toBeEnabled(),
    );
    expect(mocks.fetch).toHaveBeenCalledWith(
      "/qwenpaw-mcp/management?agent_id=one",
      { signal: expect.any(AbortSignal) },
    );
    fireEvent.click(screen.getByRole("button", { name: "Uninstall" }));
    await waitFor(() =>
      expect(mocks.fetch).toHaveBeenCalledWith(
        "/plugins/qwenpaw-mcp",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    view.rerender(<CurrentRoute />);
    await screen.findByRole("button", { name: "Install" });
    expect(
      screen.queryByRole("region", { name: "MCP plugin management" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Saved offline server")).toBeInTheDocument();
    expect(
      routeRegistry.snapshot().find(({ id }) => id === "core.mcp")?.path,
    ).toBe("/mcp");
    expect(menuRegistry.snapshot().some(({ id }) => id === "core.mcp")).toBe(
      true,
    );
  });

  it("failed management admission remains readonly and retries the public capability request", async () => {
    lifecycle = active;
    mocks.fetch.mockResolvedValueOnce(
      new Response("unavailable", { status: 503 }),
    );
    mountActualPlugin();
    render(<CurrentRoute />);
    await screen.findByRole("alert");
    expect(
      screen.getByRole("button", { name: "Saved server action" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Saved server action" }),
      ).toBeEnabled(),
    );
    expect(mocks.fetch).toHaveBeenCalledTimes(2);
  });

  it("workspace switch and unload abort plugin requests while preserving core registrations", async () => {
    lifecycle = active;
    let resolve!: (value: Response) => void;
    mocks.fetch.mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    mountActualPlugin();
    const view = render(<CurrentRoute />);
    const oldSignal = mocks.fetch.mock.calls[0][1].signal as AbortSignal;
    mocks.agent.selectedAgent = "two";
    view.rerender(<CurrentRoute />);
    expect(oldSignal.aborted).toBe(true);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Saved server action" }),
      ).toBeEnabled(),
    );
    await act(async () =>
      resolve(Response.json({ plugin_id: "qwenpaw-mcp", workspace_id: "one" })),
    );
    expect(
      screen.getByRole("button", { name: "Saved server action" }),
    ).toBeEnabled();
    const newSignal = mocks.fetch.mock.calls[1][1].signal as AbortSignal;
    act(() => removePluginRuntime("qwenpaw-mcp"));
    view.rerender(<CurrentRoute />);
    expect(newSignal.aborted).toBe(true);
    expect(
      screen.queryByRole("region", { name: "MCP plugin management" }),
    ).not.toBeInTheDocument();
    expect(routeRegistry.snapshot().some(({ id }) => id === "core.mcp")).toBe(
      true,
    );
    expect(menuRegistry.snapshot().some(({ id }) => id === "core.mcp")).toBe(
      true,
    );
  });
});

it("startup and explicit reload leave exactly one meaningful management wrapper", async () => {
  lifecycle = active;
  mountActualPlugin();
  mountActualPlugin();
  render(<CurrentRoute />);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Saved server action" }),
    ).toBeEnabled(),
  );
  expect(
    screen.getAllByRole("region", { name: "MCP plugin management" }),
  ).toHaveLength(1);
  expect(mocks.fetch).toHaveBeenCalledTimes(1);
});

it.each(["Disable", "Uninstall"])(
  "canceled pending %s releases busy controls after workspace readmission",
  async (action) => {
    lifecycle = active;
    const implementation = mocks.fetch.getMockImplementation()!;
    let resolve!: (value: Response) => void;
    let mutationSignal: AbortSignal | undefined;
    mocks.fetch.mockImplementation((path, init) => {
      if (init?.method === "POST" || init?.method === "DELETE") {
        mutationSignal = init.signal;
        return new Promise<Response>((done) => {
          resolve = done;
        });
      }
      return implementation(path, init);
    });
    mountActualPlugin();
    const view = render(<CurrentRoute />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Saved server action" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: action }));
    expect(screen.getByRole("button", { name: "Disable" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Uninstall" })).toBeDisabled();
    mocks.agent.selectedAgent = "two";
    view.rerender(<CurrentRoute />);
    expect(mutationSignal?.aborted).toBe(true);
    await waitFor(() =>
      expect(mocks.fetch).toHaveBeenCalledWith(
        "/qwenpaw-mcp/management?agent_id=two",
        expect.anything(),
      ),
    );
    await act(async () => resolve(Response.json({ ok: true })));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Saved server action" }),
      ).toBeEnabled(),
    );
    expect(screen.getByRole("button", { name: "Disable" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Uninstall" })).toBeEnabled();
    expect(
      screen.getByRole("region", { name: "MCP plugin management" }),
    ).toBeInTheDocument();
  },
);

it.each([
  ["invalid_upgrade_record", "Review the MCP installation record, then retry"],
  [
    "offline_upgrade_failed_check_dependencies_and_storage",
    "Check offline dependencies and storage, then retry",
  ],
])(
  "shows actionable passive startup recovery for %s",
  async (code, guidance) => {
    lifecycle = { ...absent, diagnostics: [code] };
    render(<CurrentRoute />);
    await screen.findByText(guidance);
    expect(screen.getByText("Saved offline server")).toBeInTheDocument();
    expect(mocks.request.mock.calls.every(([, init]) => !init?.method)).toBe(
      true,
    );
    expect(mocks.fetch).not.toHaveBeenCalled();
  },
);

it("shows selected blocked workspace recovery beside active global management and clears on scope change", async () => {
  lifecycle = Object.assign({}, active, {
    upgrade: { status: "installed", diagnostics: [] },
    workspace: {
      id: "one",
      status: "needs_review",
      eligible: false,
      diagnostics: ["workspace_needs_review"],
    },
  });
  mountActualPlugin();
  const view = render(<CurrentRoute />);
  const guidance =
    "Review this workspace’s saved MCP configuration, then retry";
  await screen.findByText(guidance);
  expect(mocks.request.mock.calls.every(([, init]) => !init?.method)).toBe(
    true,
  );
  lifecycle = Object.assign({}, active, {
    upgrade: { status: "installed", diagnostics: [] },
    workspace: {
      id: "two",
      status: "configured",
      eligible: true,
      diagnostics: [],
    },
  });
  mocks.agent.selectedAgent = "two";
  view.rerender(<CurrentRoute />);
  await waitFor(() =>
    expect(screen.queryByText(guidance)).not.toBeInTheDocument(),
  );
});

it("ordinary unused state does not imply blocked recovery", async () => {
  lifecycle = Object.assign({}, absent, {
    upgrade: { status: "skipped", diagnostics: [] },
    workspace: {
      id: "one",
      status: "unused",
      eligible: false,
      diagnostics: [],
    },
  });
  render(<CurrentRoute />);
  await screen.findByRole("button", { name: "Install" });
  expect(
    screen.queryByText(
      /Review the MCP installation record|Check offline dependencies|Review this workspace/,
    ),
  ).not.toBeInTheDocument();
});
