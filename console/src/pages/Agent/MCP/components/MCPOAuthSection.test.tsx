import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MCPOAuthSection } from "./MCPOAuthSection";

const api = vi.hoisted(() => ({
  startOAuth: vi.fn(),
  getOAuthStatus: vi.fn(),
  revokeOAuth: vi.fn(),
}));
const scope = vi.hoisted(() => ({
  agentId: "agent-a",
  signal: new AbortController().signal,
  current: () => true,
}));
vi.mock("../../../../api", () => ({ default: api }));
vi.mock("../../../../api/skillScope", () => ({ useSkillScope: () => scope }));
vi.mock("../../../../utils/openExternalLink", () => ({ openExternalLink: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("antd", async () => {
  const React = await import("react");
  return { Switch: (props: any) => React.createElement("input", { type: "checkbox", ...props }) };
});
vi.mock("@agentscope-ai/design", async () => {
  const React = await import("react");
  const Input = (props: any) => React.createElement("input", props) as any;
  return {
    Button: ({ children, loading, ...props }: any) =>
      React.createElement("button", { ...props, "data-loading": String(Boolean(loading)) }, children),
    Input,
    Tooltip: ({ children }: any) => children,
  };
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe.each([
  ["failed", true, "mcp.oauth.failed"],
  ["expired", false, "mcp.oauth.expired"],
  ["completed", false, "mcp.oauth.failed"],
] as const)("OAuth terminal %s", (status, authorized, label) => {
  it("stops waiting and enables retry", async () => {
    vi.useFakeTimers();
    api.startOAuth.mockResolvedValue({ auth_url: "https://auth", session_id: "session-1" });
    api.getOAuthStatus.mockResolvedValue({
      session_id: "session-1",
      status,
      authorized,
      expires_at: 0,
      scope: "",
    });
    render(
      <MCPOAuthSection
        url="https://mcp"
        clientKey="remote"
        oauthEnabled
        revision={4}
      />,
    );
    fireEvent.click(screen.getByTestId("mcp-oauth-start-remote"));
    await act(async () => Promise.resolve());
    await act(async () => vi.advanceTimersByTimeAsync(2000));

    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByTestId("mcp-oauth-start-remote")).toHaveAttribute(
      "data-loading",
      "false",
    );
  });
});
