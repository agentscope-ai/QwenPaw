import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MCPClientInfo } from "../../../../api/types";
import { MCPClientCard } from "./MCPClientCard";

vi.mock("@agentscope-ai/design", async () => {
  const React = await import("react");
  const wrap = (tag: string) =>
    ({ children, danger: _danger, autoSize: _autoSize, icon: _icon, loading: _loading, ...props }: any) =>
      React.createElement(tag, props, children);
  const Input = wrap("input") as any;
  Input.TextArea = wrap("textarea");
  Input.Password = wrap("input");
  return {
    Card: wrap("article"),
    Button: wrap("button"),
    Tooltip: ({ children }: any) => children,
    Input,
    Select: ({ options = [], ...props }: any) =>
      React.createElement(
        "select",
        props,
        options.map((option: any) =>
          React.createElement("option", { key: option.value }, option.label),
        ),
      ),
    Modal: ({ open, children, footer }: any) =>
      open ? React.createElement("div", {}, children, footer) : null,
  };
});

vi.mock("../../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("./MCPAccessModal", () => ({ MCPAccessModal: () => null }));
vi.mock("./MCPOAuthSection", () => ({
  MCPOAuthSection: ({ onAuthChanged }: { onAuthChanged: () => void }) => (
    <button data-testid="mock-oauth-success" onClick={onAuthChanged}>
      oauth-success
    </button>
  ),
}));

const client: MCPClientInfo = {
  key: "remote",
  name: "Remote",
  description: "safe",
  enabled: true,
  transport: "streamable_http",
  url: "https://example.test/mcp",
  headers: {},
  command: "",
  args: [],
  env: {},
  cwd: "",
  http_timeout: null,
  tools: null,
  oauth_status: null,
  access_summary: { default_effect: "ask", overrides_count: 0 },
  credential_fields: { headers: ["Authorization"], env: ["API_KEY"] },
  revision: 3,
};

const refresh = () => Promise.resolve();

describe("MCPClientCard governance", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps configuration actions hidden for a use-only member", () => {
    render(
      <MCPClientCard
        client={client}
        canEdit={false}
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onUpdate={vi.fn()}
        onUpdatePolicy={vi.fn()}
        onRefresh={refresh}
      />,
    );

    fireEvent.click(screen.getByTestId("mcp-client-card-remote"));

    expect(screen.queryByTestId("mcp-client-edit-remote")).toBeNull();
    expect(screen.queryByTestId("mcp-client-save-remote")).toBeNull();
    expect(screen.queryByTestId("mcp-oauth-start-remote")).toBeNull();
  });

  it("shows configured field names with keep as the initial edit action", () => {
    render(
      <MCPClientCard
        client={client}
        canEdit
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onUpdate={vi.fn()}
        onUpdatePolicy={vi.fn()}
        onRefresh={refresh}
      />,
    );

    fireEvent.click(screen.getByTestId("mcp-client-card-remote"));
    fireEvent.click(screen.getByTestId("mcp-client-edit-remote"));

    expect(
      screen.getByTestId("mcp-credential-row-headers-Authorization"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("mcp.credentialAction.keep")).toHaveLength(2);
    expect(screen.queryByDisplayValue(/Bearer|secret/i)).toBeNull();
  });

  it("keeps the editor open when a stale revision is rejected", async () => {
    const onUpdate = vi.fn().mockResolvedValue(false);
    render(
      <MCPClientCard
        client={client}
        canEdit
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onUpdate={onUpdate}
        onUpdatePolicy={vi.fn()}
        onRefresh={refresh}
      />,
    );
    fireEvent.click(screen.getByTestId("mcp-client-card-remote"));
    fireEvent.click(screen.getByTestId("mcp-client-edit-remote"));
    fireEvent.click(screen.getByTestId("mcp-client-save-remote"));

    await waitFor(() =>
      expect(onUpdate).toHaveBeenCalledWith(
        "remote",
        expect.any(Object),
        3,
      ),
    );
    expect(screen.getByTestId("mcp-client-save-remote")).toBeInTheDocument();
  });

  it("rejects raw secret maps added to JSON", async () => {
    const onUpdate = vi.fn();
    vi.spyOn(window, "alert").mockImplementation(() => undefined);
    render(
      <MCPClientCard client={client} canEdit onToggle={vi.fn()} onDelete={vi.fn()} onUpdate={onUpdate} onUpdatePolicy={vi.fn()} onRefresh={refresh} />,
    );
    fireEvent.click(screen.getByTestId("mcp-client-card-remote"));
    fireEvent.click(screen.getByTestId("mcp-client-edit-remote"));
    fireEvent.change(screen.getByTestId("mcp-client-json-remote"), {
      target: { value: '{"headers":{"Authorization":"secret"}}' },
    });
    fireEvent.click(screen.getByTestId("mcp-client-save-remote"));
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("drops an open draft when identity scope changes with the same client key", () => {
    const props = {
      client,
      canEdit: true,
      onToggle: vi.fn(),
      onDelete: vi.fn(),
      onUpdate: vi.fn(),
      onUpdatePolicy: vi.fn(),
      onRefresh: refresh,
    };
    const { rerender } = render(<MCPClientCard key="agent-a:remote" {...props} />);
    fireEvent.click(screen.getByTestId("mcp-client-card-remote"));
    fireEvent.click(screen.getByTestId("mcp-client-edit-remote"));
    expect(screen.getByTestId("mcp-client-save-remote")).toBeInTheDocument();

    rerender(<MCPClientCard key="agent-b:remote" {...props} />);
    expect(screen.queryByTestId("mcp-client-save-remote")).toBeNull();
  });

  it("blocks reopening OAuth until refresh supplies a new revision", async () => {
    let finishRefresh!: () => void;
    const onRefresh = vi.fn(() => new Promise<void>((resolve) => {
      finishRefresh = resolve;
    }));
    const { rerender } = render(
      <MCPClientCard
        client={client}
        canEdit
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onUpdate={vi.fn()}
        onUpdatePolicy={vi.fn()}
        onRefresh={onRefresh}
      />,
    );

    fireEvent.click(screen.getByText("mcp.oauth.authorize"));
    fireEvent.click(screen.getByTestId("mock-oauth-success"));

    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("mock-oauth-success")).toBeNull();

    fireEvent.click(screen.getByTestId("mcp-oauth-manage-remote"));
    expect(screen.queryByTestId("mock-oauth-success")).toBeNull();

    finishRefresh();
    rerender(
      <MCPClientCard
        client={{ ...client, revision: 4 }}
        canEdit
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onUpdate={vi.fn()}
        onUpdatePolicy={vi.fn()}
        onRefresh={onRefresh}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("mcp-oauth-manage-remote")).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByTestId("mcp-oauth-manage-remote"));
    expect(screen.getByTestId("mock-oauth-success")).toBeInTheDocument();
  });

  it("offers refresh retry without reopening OAuth after refresh fails", async () => {
    const onRefresh = vi.fn().mockRejectedValueOnce(new Error("offline"));
    render(
      <MCPClientCard
        client={client}
        canEdit
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onUpdate={vi.fn()}
        onUpdatePolicy={vi.fn()}
        onRefresh={onRefresh}
      />,
    );

    fireEvent.click(screen.getByTestId("mcp-oauth-manage-remote"));
    fireEvent.click(screen.getByTestId("mock-oauth-success"));
    await waitFor(() =>
      expect(screen.getByTestId("mcp-oauth-manage-remote")).not.toBeDisabled(),
    );
    expect(screen.getByText("common.retry")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("mcp-oauth-manage-remote"));
    expect(onRefresh).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("mock-oauth-success")).toBeNull();
  });
});
