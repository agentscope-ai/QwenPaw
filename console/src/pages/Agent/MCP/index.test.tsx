import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MCPClientInfo } from "../../../api/types";

const mocks = vi.hoisted(() => ({
  useMCP: vi.fn(),
  createClient: vi.fn(),
  updateClient: vi.fn(),
  updatePolicy: vi.fn(),
  toggleEnabled: vi.fn(),
  deleteClient: vi.fn(),
  refreshClients: vi.fn(),
  latestSubmit: null as null | (() => void | Promise<void>),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@agentscope-ai/design", () => {
  const Input = Object.assign(
    (props: React.InputHTMLAttributes<HTMLInputElement>) => (
      <input {...props} />
    ),
    {
      TextArea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
        <textarea {...props} />
      ),
    },
  );
  return {
    Button: ({
      children,
      onClick,
      ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
      <button
        type="button"
        {...props}
        onClick={(event) => {
          onClick?.(event);
        }}
        ref={() => {
          if (children === "common.create" && onClick) {
            mocks.latestSubmit = () =>
              onClick({} as React.MouseEvent<HTMLButtonElement>);
          }
        }}
      >
        {children}
      </button>
    ),
    Empty: ({ description }: { description: React.ReactNode }) => (
      <div>{description}</div>
    ),
    Input,
    Select: () => null,
  };
});
vi.mock("antd", () => ({
  Alert: ({
    message,
    action,
  }: {
    message: React.ReactNode;
    action?: React.ReactNode;
  }) => (
    <div role="alert">
      {message}
      {action}
    </div>
  ),
  Segmented: () => null,
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Tabs: ({
    activeKey,
    items,
  }: {
    activeKey: string;
    items: Array<{ key: string; children: React.ReactNode }>;
  }) => <>{items.find((item) => item.key === activeKey)?.children}</>,
}));
vi.mock("./useMCP", () => ({ useMCP: mocks.useMCP }));
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
vi.mock("@/components/interaction/Cascade", () => ({
  Cascade: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/interaction/SharedModal", () => ({
  SharedModal: ({
    children,
    footer,
    open,
    title,
  }: {
    children: React.ReactNode;
    footer: React.ReactNode;
    open: boolean;
    title: React.ReactNode;
  }) =>
    open ? (
      <section role="dialog" aria-label={String(title)}>
        {children}
        {footer}
      </section>
    ) : null,
}));
vi.mock("./components", () => ({
  MCPClientCard: ({
    client,
    onToggle,
  }: {
    client: MCPClientInfo;
    onToggle: (client: MCPClientInfo) => void;
  }) => (
    <article>
      <span>{client.name}</span>
      <button type="button" onClick={() => onToggle(client)}>
        toggle {client.name}
      </button>
    </article>
  ),
}));

import MCPPage from ".";

const client: MCPClientInfo = {
  key: "client-1",
  name: "Client One",
  description: "",
  command: "run",
  enabled: true,
  transport: "stdio",
} as MCPClientInfo;

function state(
  overrides: Partial<ReturnType<typeof baseState>> = {},
): ReturnType<typeof baseState> {
  return { ...baseState(), ...overrides };
}

function baseState() {
  return {
    agentId: "agent-a",
    clients: [] as MCPClientInfo[],
    providerServers: [],
    loading: false,
    error: null as string | null,
    ready: true,
    createClient: mocks.createClient,
    updateClient: mocks.updateClient,
    updatePolicy: mocks.updatePolicy,
    toggleEnabled: mocks.toggleEnabled,
    deleteClient: mocks.deleteClient,
    refreshClients: mocks.refreshClients,
  };
}

describe("MCPPage load recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.refreshClients.mockResolvedValue(undefined);
    mocks.createClient.mockResolvedValue(true);
    mocks.latestSubmit = null;
  });

  it.each([
    ["empty", []],
    ["populated", [client]],
  ] as const)(
    "blocks mutations after an initial failure and recovers to %s",
    async (_stateName, clients) => {
      mocks.useMCP.mockReturnValue(
        state({ ready: false, error: "mcp.loadError" }),
      );
      const user = userEvent.setup();
      const view = render(<MCPPage />);

      expect(screen.getByRole("alert")).toHaveTextContent("mcp.loadError");
      expect(screen.queryByRole("button", { name: "mcp.create" })).toBeNull();
      expect(screen.queryByText("mcp.emptyState")).toBeNull();
      expect(mocks.createClient).not.toHaveBeenCalled();
      expect(mocks.updateClient).not.toHaveBeenCalled();
      expect(mocks.toggleEnabled).not.toHaveBeenCalled();
      expect(mocks.deleteClient).not.toHaveBeenCalled();

      await user.click(screen.getByRole("button", { name: "common.retry" }));
      expect(mocks.refreshClients).toHaveBeenCalledTimes(1);
      expect(mocks.createClient).not.toHaveBeenCalled();
      expect(mocks.updateClient).not.toHaveBeenCalled();
      expect(mocks.toggleEnabled).not.toHaveBeenCalled();
      expect(mocks.deleteClient).not.toHaveBeenCalled();

      mocks.useMCP.mockReturnValue(state({ clients: [...clients] }));
      view.rerender(<MCPPage />);

      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByRole("button", { name: "mcp.create" })).toBeEnabled();
      if (clients.length) {
        expect(screen.getByText("Client One")).toBeVisible();
      } else {
        expect(screen.getByText("mcp.emptyState")).toBeVisible();
      }
    },
  );

  it("keeps stale clients and CRUD available after a refresh failure", async () => {
    mocks.useMCP.mockReturnValue(
      state({ clients: [client], error: "mcp.loadError" }),
    );
    const user = userEvent.setup();
    render(<MCPPage />);

    expect(screen.getByRole("alert")).toHaveTextContent("mcp.loadError");
    expect(screen.getByText("Client One")).toBeVisible();
    expect(screen.getByRole("button", { name: "mcp.create" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "toggle Client One" }));
    expect(mocks.toggleEnabled).toHaveBeenCalledWith(client);
  });

  it("clears agent A's create draft before agent B becomes ready", async () => {
    mocks.useMCP.mockReturnValue(state({ agentId: "agent-a" }));
    const user = userEvent.setup();
    const view = render(<MCPPage />);

    await user.click(screen.getByRole("button", { name: "mcp.create" }));
    const agentADialog = screen.getByRole("dialog", { name: "mcp.create" });
    await user.type(
      within(agentADialog).getByPlaceholderText("mcp.form.keyPlaceholder"),
      "agent-a-client",
    );
    await user.type(
      within(agentADialog).getByPlaceholderText("mcp.form.namePlaceholder"),
      "Agent A Client",
    );
    await user.type(
      within(agentADialog).getByPlaceholderText("https://mcp.example.com/mcp"),
      "https://agent-a.example/mcp",
    );
    const staleAgentASubmit = mocks.latestSubmit;
    expect(staleAgentASubmit).not.toBeNull();

    mocks.useMCP.mockReturnValue(
      state({ agentId: "agent-b", loading: true, ready: false }),
    );
    view.rerender(<MCPPage />);
    expect(screen.queryByRole("dialog")).toBeNull();

    mocks.useMCP.mockReturnValue(state({ agentId: "agent-b" }));
    view.rerender(<MCPPage />);
    expect(screen.queryByRole("dialog")).toBeNull();

    await act(async () => {
      await staleAgentASubmit?.();
    });
    expect(mocks.createClient).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "mcp.create" }));
    const agentBDialog = screen.getByRole("dialog", { name: "mcp.create" });
    const keyInput = within(agentBDialog).getByPlaceholderText(
      "mcp.form.keyPlaceholder",
    );
    const nameInput = within(agentBDialog).getByPlaceholderText(
      "mcp.form.namePlaceholder",
    );
    const urlInput = within(agentBDialog).getByPlaceholderText(
      "https://mcp.example.com/mcp",
    );
    expect(keyInput).toHaveValue("");
    expect(nameInput).toHaveValue("");
    expect(urlInput).toHaveValue("");

    await user.type(keyInput, "agent-b-client");
    await user.type(nameInput, "Agent B Client");
    await user.type(urlInput, "https://agent-b.example/mcp");
    await user.click(
      within(agentBDialog).getByRole("button", { name: "common.create" }),
    );

    expect(mocks.createClient).toHaveBeenCalledTimes(1);
    expect(mocks.createClient).toHaveBeenCalledWith(
      "agent-b-client",
      expect.objectContaining({
        name: "Agent B Client",
        url: "https://agent-b.example/mcp",
      }),
    );
  });
});
