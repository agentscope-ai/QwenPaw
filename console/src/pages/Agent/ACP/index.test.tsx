import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ACPAgentConfig, ACPConfig } from "../../../api/types";

const mocks = vi.hoisted(() => ({
  getACPConfig: vi.fn(),
  updateACPConfig: vi.fn(),
  updateACPAgentConfig: vi.fn(),
  getACPNodeRuntime: vi.fn(),
  updateACPNodeRuntime: vi.fn(),
  message: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

const agentStore = vi.hoisted(() => {
  const state = { selectedAgent: "default" };
  const useAgentStore = Object.assign(
    vi.fn(() => ({ selectedAgent: state.selectedAgent })),
    { getState: () => state },
  );
  return { state, useAgentStore };
});

const actions = vi.hoisted(() => ({
  create: undefined as
    | ((values: Record<string, unknown>) => Promise<boolean | void>)
    | undefined,
  rename: undefined as
    | ((values: Record<string, unknown>) => Promise<boolean | void>)
    | undefined,
  remove: undefined as (() => void) | undefined,
  toggle: undefined as (() => Promise<void>) | undefined,
  nodeChange: undefined as
    | ((value: string) => void | Promise<void>)
    | undefined,
}));

vi.mock("../../../api", () => ({
  default: {
    getACPConfig: mocks.getACPConfig,
    updateACPConfig: mocks.updateACPConfig,
    updateACPAgentConfig: mocks.updateACPAgentConfig,
    getACPNodeRuntime: mocks.getACPNodeRuntime,
    updateACPNodeRuntime: mocks.updateACPNodeRuntime,
  },
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: agentStore.useAgentStore,
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mocks.message }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@agentscope-ai/design", async () => {
  const antd = await vi.importActual<typeof import("antd")>("antd");
  return {
    ...antd,
    Select: ({ onChange }: { onChange: (value: string) => void }) => {
      actions.nodeChange = onChange;
      return <button type="button">save-node-path</button>;
    },
  };
});

vi.mock("@/components/PageHeader", () => ({
  PageHeader: ({
    current,
    extra,
  }: {
    current: string;
    extra?: React.ReactNode;
  }) => (
    <header>
      <h1>{current}</h1>
      {extra}
    </header>
  ),
}));

vi.mock("@/components/InlineHelp", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@number-flow/react", () => ({
  default: ({ value }: { value: number }) => <span>{value}</span>,
}));

vi.mock("@/components/interaction/Cascade", () => ({
  Cascade: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/interaction/SharedModal", () => ({
  SharedModal: ({
    children,
    open,
  }: {
    children: React.ReactNode;
    open: boolean;
  }) => (open ? <div role="dialog">{children}</div> : null),
}));

vi.mock("./components/ACPCard", () => ({
  ACPCard: ({
    agentKey,
    config,
    onClick,
    onToggle,
  }: {
    agentKey: string;
    config: ACPAgentConfig;
    onClick: () => void;
    onToggle: () => Promise<void>;
  }) => {
    actions.toggle = onToggle;
    return (
      <div>
        <span>{agentKey}</span>
        <button type="button" onClick={onClick}>
          edit-{agentKey}
        </button>
        <button
          type="button"
          data-enabled={config.enabled}
          onClick={() => void onToggle()}
        >
          toggle-{agentKey}
        </button>
      </div>
    );
  },
}));

vi.mock("./components/ACPDrawer", () => ({
  ACPDrawer: ({
    open,
    onSubmit,
    onDelete,
  }: {
    open: boolean;
    onSubmit: (values: Record<string, unknown>) => Promise<boolean | void>;
    onDelete: () => void;
  }) => {
    if (open) {
      actions.create = onSubmit;
      actions.remove = onDelete;
    }
    return open ? (
      <div role="dialog">
        <button
          type="button"
          onClick={() =>
            void onSubmit({
              agentKey: "new-agent",
              enabled: true,
              command: "new-agent-command",
              argsText: "--serve",
              envText: "TOKEN=value",
              trusted: true,
              tool_parse_mode: "call_title",
            })
          }
        >
          save-new-agent
        </button>
      </div>
    ) : null;
  },
}));

import ACPPage from "./index";

const existingAgent: ACPAgentConfig = {
  enabled: true,
  command: "existing-command",
  args: ["--existing"],
  env: { EXISTING: "value" },
  trusted: true,
  tool_parse_mode: "call_title",
};

const loadedConfig: ACPConfig = {
  node_path: "/custom/node",
  agents: { "existing-custom": existingAgent },
};

const newAgent: ACPAgentConfig = {
  ...existingAgent,
  command: "new-owner-command",
};

const newOwnerConfig: ACPConfig = {
  node_path: "/new-owner/node",
  agents: { "new-existing": newAgent },
};

const submittedAgent = {
  agentKey: "new-agent",
  enabled: true,
  command: "new-agent-command",
  argsText: "--serve",
  envText: "TOKEN=value",
  trusted: true,
  tool_parse_mode: "call_title",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

describe("ACP load guard", () => {
  beforeEach(() => {
    mocks.getACPConfig.mockReset();
    mocks.updateACPConfig.mockReset();
    mocks.updateACPAgentConfig.mockReset();
    mocks.getACPNodeRuntime.mockReset();
    mocks.updateACPNodeRuntime.mockReset();
    mocks.message.error.mockReset();
    mocks.message.success.mockReset();
    agentStore.state.selectedAgent = "default";
    actions.create = undefined;
    actions.rename = undefined;
    actions.remove = undefined;
    actions.toggle = undefined;
    actions.nodeChange = undefined;
    mocks.getACPConfig
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(loadedConfig);
    mocks.updateACPConfig.mockImplementation(
      async (config: ACPConfig) => config,
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("blocks mutations after load failure and retries into complete state", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ACPPage />);

    const retry = await screen.findByRole("button", { name: "common.retry" });
    expect(screen.getByRole("alert")).toHaveTextContent("acp.loadError");
    expect(screen.queryByRole("button", { name: "acp.create" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "acp.nodeSettings" }),
    ).toBeNull();
    expect(screen.queryByText("existing-custom")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "toggle-existing-custom" }),
    ).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocks.getACPNodeRuntime).not.toHaveBeenCalled();
    expect(mocks.updateACPConfig).not.toHaveBeenCalled();
    expect(mocks.updateACPAgentConfig).not.toHaveBeenCalled();
    expect(mocks.updateACPNodeRuntime).not.toHaveBeenCalled();

    fireEvent.click(retry);

    expect(await screen.findByText("existing-custom")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "acp.create" }));
    fireEvent.click(screen.getByRole("button", { name: "save-new-agent" }));

    await waitFor(() => expect(mocks.updateACPConfig).toHaveBeenCalledOnce());
    expect(mocks.updateACPConfig).toHaveBeenCalledWith(
      {
        node_path: "/custom/node",
        agents: {
          "existing-custom": existingAgent,
          "new-agent": expect.objectContaining({
            enabled: true,
            command: "new-agent-command",
          }),
        },
      },
      "default",
    );
  });

  it.each(["resolve", "reject"] as const)(
    "ignores an old agent request that settles late with %s",
    async (settlement) => {
      vi.spyOn(console, "error").mockImplementation(() => {});
      agentStore.state.selectedAgent = "old";
      const oldRequest = deferred<ACPConfig>();
      const newRequest = deferred<ACPConfig>();
      mocks.getACPConfig
        .mockReset()
        .mockImplementation((agentId: string) =>
          agentId === "old" ? oldRequest.promise : newRequest.promise,
        );

      const view = render(<ACPPage />);
      await waitFor(() =>
        expect(mocks.getACPConfig).toHaveBeenCalledWith("old"),
      );

      agentStore.state.selectedAgent = "new";
      view.rerender(<ACPPage />);
      expect(screen.queryByRole("button", { name: "acp.create" })).toBeNull();
      await waitFor(() =>
        expect(mocks.getACPConfig).toHaveBeenCalledWith("new"),
      );

      await act(async () => {
        newRequest.resolve(newOwnerConfig);
        await newRequest.promise;
      });
      expect(await screen.findByText("new-existing")).toBeInTheDocument();

      await act(async () => {
        if (settlement === "resolve") {
          oldRequest.resolve(loadedConfig);
          await oldRequest.promise;
        } else {
          oldRequest.reject(new Error("late old failure"));
          await oldRequest.promise.catch(() => undefined);
        }
      });

      expect(screen.getByText("new-existing")).toBeInTheDocument();
      expect(screen.queryByText("existing-custom")).toBeNull();
      expect(screen.queryByRole("alert")).toBeNull();

      fireEvent.click(screen.getByRole("button", { name: "acp.create" }));
      fireEvent.click(screen.getByRole("button", { name: "save-new-agent" }));

      await waitFor(() => expect(mocks.updateACPConfig).toHaveBeenCalledOnce());
      expect(mocks.updateACPConfig).toHaveBeenCalledWith(
        {
          node_path: "/new-owner/node",
          agents: {
            "new-existing": newAgent,
            "new-agent": expect.objectContaining({
              command: "new-agent-command",
            }),
          },
        },
        "new",
      );
    },
  );

  it("blocks five stale-owner mutation paths and reloads current agent", async () => {
    agentStore.state.selectedAgent = "old";
    mocks.getACPConfig.mockReset().mockResolvedValue(loadedConfig);
    mocks.getACPNodeRuntime.mockResolvedValue({
      node_path: "/old/node",
      effective_node_path: "/old/node",
      candidates: [],
    });
    render(<ACPPage />);

    expect(await screen.findByText("existing-custom")).toBeInTheDocument();
    const toggle = actions.toggle;

    fireEvent.click(
      screen.getByRole("button", { name: "edit-existing-custom" }),
    );
    actions.rename = actions.create;
    const rename = actions.rename;
    const remove = actions.remove;

    fireEvent.click(screen.getByRole("button", { name: "acp.create" }));
    const create = actions.create;

    fireEvent.click(screen.getByRole("button", { name: "acp.nodeSettings" }));
    expect(
      await screen.findByRole("button", { name: "save-node-path" }),
    ).toBeInTheDocument();
    const nodeChange = actions.nodeChange;

    expect(create).toBeDefined();
    expect(rename).toBeDefined();
    expect(remove).toBeDefined();
    expect(toggle).toBeDefined();
    expect(nodeChange).toBeDefined();

    mocks.getACPConfig.mockImplementation(() => new Promise(() => {}));
    agentStore.state.selectedAgent = "new";
    await act(async () => {
      await create?.(submittedAgent);
      await rename?.({ ...submittedAgent, agentKey: "renamed-agent" });
      remove?.();
      await toggle?.();
      await nodeChange?.("/new/node");
    });

    expect(mocks.updateACPConfig).not.toHaveBeenCalled();
    expect(mocks.updateACPAgentConfig).not.toHaveBeenCalled();
    expect(mocks.updateACPNodeRuntime).not.toHaveBeenCalled();
    expect(mocks.getACPConfig).toHaveBeenCalledWith("new");
    expect(screen.getByRole("status")).toHaveTextContent("acp.loading");
  });

  it.each(["resolve", "reject"] as const)(
    "ignores an old A toggle that settles after A-B-A with %s",
    async (settlement) => {
      vi.spyOn(console, "error").mockImplementation(() => {});
      agentStore.state.selectedAgent = "agent-a";
      const staleToggle = deferred<void>();
      const disabledAgent = { ...existingAgent, enabled: false };
      mocks.getACPConfig
        .mockReset()
        .mockResolvedValueOnce(loadedConfig)
        .mockResolvedValueOnce(newOwnerConfig)
        .mockResolvedValueOnce({
          ...loadedConfig,
          agents: { "existing-custom": disabledAgent },
        });
      mocks.updateACPAgentConfig
        .mockImplementationOnce(() => staleToggle.promise)
        .mockResolvedValueOnce({});

      const view = render(<ACPPage />);
      const firstToggle = await screen.findByRole("button", {
        name: "toggle-existing-custom",
      });
      fireEvent.click(firstToggle);
      await waitFor(() =>
        expect(mocks.updateACPAgentConfig).toHaveBeenCalledTimes(1),
      );

      agentStore.state.selectedAgent = "agent-b";
      view.rerender(<ACPPage />);
      expect(await screen.findByText("new-existing")).toBeInTheDocument();

      agentStore.state.selectedAgent = "agent-a";
      view.rerender(<ACPPage />);
      const currentToggle = await screen.findByRole("button", {
        name: "toggle-existing-custom",
      });
      expect(currentToggle).toHaveAttribute("data-enabled", "false");
      fireEvent.click(currentToggle);
      await waitFor(() =>
        expect(mocks.updateACPAgentConfig).toHaveBeenCalledTimes(2),
      );
      await waitFor(() =>
        expect(currentToggle).toHaveAttribute("data-enabled", "true"),
      );

      await act(async () => {
        if (settlement === "resolve") {
          staleToggle.resolve();
          await staleToggle.promise;
        } else {
          staleToggle.reject(new Error("late toggle failure"));
          await staleToggle.promise.catch(() => undefined);
        }
      });

      expect(currentToggle).toHaveAttribute("data-enabled", "true");
      expect(mocks.message.error).not.toHaveBeenCalled();
    },
  );
});
