import { render, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { MCPClientInfo } from "../../../../api/types";
import { MCPAccessModal } from "./MCPAccessModal";

const api = vi.hoisted(() => ({
  listMCPTools: vi.fn().mockResolvedValue([]),
  getMCPPolicy: vi.fn(),
  listMCPAccessPrincipals: vi.fn(),
}));
const scope = vi.hoisted(() => ({
  agentId: "agent-a",
  signal: new AbortController().signal,
  current: () => true,
}));
const translate = vi.hoisted(() => (key: string) => key);
vi.mock("../../../../api", () => ({ default: api }));
vi.mock("../../../../api/skillScope", () => ({
  useSkillScope: () => scope,
}));
vi.mock("../../../../hooks/useAppMessage", () => ({ useAppMessage: () => ({ message: { error: vi.fn(), warning: vi.fn() } }) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));
vi.mock("@agentscope-ai/design", async () => {
  const React = await import("react");
  return {
    Modal: ({ open, children }: any) => open ? React.createElement("div", {}, children) : null,
    Button: ({ children }: any) => React.createElement("button", {}, children),
    Empty: () => React.createElement("div"),
  };
});

it("loads only tool discovery data for a use-only member", async () => {
  const client = { key: "remote", enabled: true } as MCPClientInfo;
  render(<MCPAccessModal client={client} open canEdit={false} onClose={vi.fn()} onSave={vi.fn()} />);
  await waitFor(() => expect(api.listMCPTools).toHaveBeenCalled());
  expect(api.getMCPPolicy).not.toHaveBeenCalled();
  expect(api.listMCPAccessPrincipals).not.toHaveBeenCalled();
});
