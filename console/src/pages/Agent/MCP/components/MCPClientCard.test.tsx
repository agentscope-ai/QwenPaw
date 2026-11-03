import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MCPClientInfo } from "@/api/types";
import { MCPClientCard } from "./MCPClientCard";

const confirm = vi.hoisted(() => vi.fn());
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@agentscope-ai/design", async () => vi.importActual("antd"));
vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { destroy: vi.fn(), error: vi.fn() },
    modal: { confirm },
  }),
}));
vi.mock("@/components/interaction/ServiceCard", () => ({
  ServiceCard: ({ onConfigure }: { onConfigure: () => void }) => (
    <button onClick={onConfigure}>Configure connection</button>
  ),
}));
vi.mock("./MCPAccessModal", () => ({ MCPAccessModal: () => null }));
vi.mock("./MCPOAuthSection", () => ({ MCPOAuthSection: () => null }));

const client: MCPClientInfo = {
  key: "filesystem",
  name: "Filesystem",
  description: "",
  enabled: false,
  transport: "stdio",
  url: "",
  headers: {},
  command: "node",
  args: [],
  env: {},
  cwd: "",
  http_timeout: null,
  tools: null,
  oauth_status: null,
  access_summary: { default_effect: "deny", overrides_count: 0 },
};

describe("MCP connection draft dismissal", () => {
  it("can discard invalid JSON and reopen the saved connection", async () => {
    const onUpdate = vi.fn().mockResolvedValue(true);
    render(
      <MCPClientCard
        client={client}
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onUpdate={onUpdate}
        onUpdatePolicy={vi.fn().mockResolvedValue(true)}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Configure connection" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "common.advancedSettings" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "JSON" }), {
      target: { value: "{" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
    expect(onUpdate).not.toHaveBeenCalled();
    await act(async () => confirm.mock.calls[0][0].onCancel());
    expect(screen.getByRole("textbox", { name: "JSON" })).toHaveValue("{");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2));
    await act(async () => confirm.mock.calls[1][0].onOk());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(
      screen.getByRole("button", { name: "Configure connection" }),
    );
    expect(screen.getByLabelText("mcp.form.name")).toHaveValue(client.name);
    expect(screen.getByLabelText("mcp.form.command")).toHaveValue(
      client.command,
    );
    expect(onUpdate).not.toHaveBeenCalled();
  });
});
