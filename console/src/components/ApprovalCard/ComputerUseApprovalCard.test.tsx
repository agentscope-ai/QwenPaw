import React from "react";
import * as antd from "antd";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const fetchMock = vi.fn();
const success = vi.fn();
let locale = "en";
let Card: React.ComponentType<{
  approval: {
    requestId: string;
    sessionId: string;
    createdAt?: number;
    timeoutSeconds?: number;
    toolParams: Record<string, unknown>;
  };
  onResolved: () => void;
}>;

beforeAll(async () => {
  Object.defineProperty(window, "QwenPaw", {
    configurable: true,
    value: {
      host: {
        React,
        antd: { ...antd, message: { success, error: vi.fn() } },
        antdIcons: {},
        getApiUrl: (path: string) => path,
        getApiToken: () => "",
        useLocale: () => locale,
        fetch: fetchMock,
      },
      chat: { approval: { render: vi.fn() } },
      registerRoutes: vi.fn(),
    },
  });
  // Import the plugin after its host runtime has been supplied. The literal
  // glob is resolved by Vite without adding the plugin source to the console
  // type-check program, which types the host stricter than the plugin does.
  const [loadCard] = Object.values(
    import.meta.glob<typeof Card>(
      "../../../../plugins/bundle/computer-use/frontend/src/index.tsx",
      { import: "ComputerUseApprovalCard" },
    ),
  );
  Card = await loadCard();
});
beforeEach(() => {
  locale = "en";
  fetchMock.mockReset();
  success.mockClear();
});
afterEach(() => vi.restoreAllMocks());

function mount(expired = false) {
  const onResolved = vi.fn();
  render(
    <Card
      approval={{
        requestId: "app-1",
        sessionId: "session-1",
        createdAt: Date.now() / 1000 - (expired ? 61 : 0),
        timeoutSeconds: 60,
        toolParams: {
          display_name: "Editor",
          canonical_app_id: "process:C:ApplicationsEditor.exe",
          warning: "Review application access.",
        },
      }}
      onResolved={onResolved}
    />,
  );
  return onResolved;
}
function response(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  };
}

describe("Computer-use approval card", () => {
  it.each([
    ["deny", "Deny app for this session"],
    ["session", "Allow app for this session"],
    ["always", "Always allow this app"],
  ])("submits %s with its actual session scope", async (decision, label) => {
    fetchMock.mockResolvedValue(response({ resolved: true, decision }));
    const onResolved = mount();
    expect(
      screen.getByRole("button", { name: "Allow app for this session" }),
    ).toHaveClass("ant-btn-primary");
    expect(
      screen.getByRole("button", { name: "Always allow this app" }),
    ).not.toHaveClass("ant-btn-primary");
    fireEvent.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/computer-use/session/pending/decision",
      expect.objectContaining({
        body: JSON.stringify({
          session_id: "session-1",
          request_id: "app-1",
          decision,
        }),
      }),
    );
    expect(success).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText(/all agents in this QwenPaw installation/),
    ).toBeVisible();
  });

  it.each([false, undefined])(
    "does not treat resolved=%s as success",
    async (resolved) => {
      fetchMock.mockResolvedValue(response({ resolved }));
      const onResolved = mount();
      fireEvent.click(
        screen.getByRole("button", { name: "Allow app for this session" }),
      );
      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(
          "Request already handled or expired",
        ),
      );
      expect(onResolved).not.toHaveBeenCalled();
      expect(success).not.toHaveBeenCalled();
      expect(
        screen.queryByRole("button", { name: "Always allow this app" }),
      ).not.toBeInTheDocument();
    },
  );

  it.each([404, 409, 500])(
    "keeps context on HTTP %s without a success message",
    async (status) => {
      fetchMock.mockResolvedValue(response({ detail: "Unavailable" }, status));
      const onResolved = mount();
      fireEvent.click(
        screen.getByRole("button", { name: "Deny app for this session" }),
      );
      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(
          status === 500 ? "Could not confirm" : "Request already handled",
        ),
      );
      expect(onResolved).not.toHaveBeenCalled();
      expect(success).not.toHaveBeenCalled();
      expect(screen.getByText("Editor")).toBeVisible();
    },
  );

  it.each([
    [
      400,
      { detail: "Pending application is invalid." },
      "Pending application is invalid.",
    ],
    [403, {}, "HTTP 403"],
  ])(
    "shows the server reason for an explicit HTTP %s rejection",
    async (status, body, reason) => {
      fetchMock.mockResolvedValue(response(body, status));
      const onResolved = mount();
      fireEvent.click(
        screen.getByRole("button", { name: "Always allow this app" }),
      );
      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(
          `The server rejected this decision: ${reason}`,
        ),
      );
      expect(onResolved).not.toHaveBeenCalled();
      expect(success).not.toHaveBeenCalled();
      expect(screen.getByText("Editor")).toBeVisible();
      expect(
        screen.queryByRole("button", { name: "Deny app for this session" }),
      ).not.toBeInTheDocument();
    },
  );

  it("blocks repeated and conflicting submissions", async () => {
    let resolve!: (value: unknown) => void;
    fetchMock.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const onResolved = mount();
    const allow = screen.getByRole("button", {
      name: "Allow app for this session",
    });
    act(() => {
      fireEvent.click(allow);
      fireEvent.click(allow);
      fireEvent.click(
        screen.getByRole("button", { name: "Deny app for this session" }),
      );
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status")).toHaveTextContent("Submitting decision");
    await act(async () => resolve(response({ resolved: true })));
    expect(onResolved).toHaveBeenCalledTimes(1);
  });

  it("does not submit expired requests", () => {
    mount(true);
    expect(screen.getByRole("status")).toHaveTextContent("Request expired");
    expect(
      screen.queryByRole("button", { name: "Allow app for this session" }),
    ).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uses Chinese scope labels", () => {
    locale = "zh";
    mount();
    expect(
      screen.getByRole("button", { name: "本会话允许此应用" }),
    ).toHaveClass("ant-btn-primary");
    expect(
      screen.getByRole("button", { name: "长期允许此应用" }),
    ).not.toHaveClass("ant-btn-primary");
    expect(
      screen.getByRole("button", { name: "本会话拒绝此应用" }),
    ).not.toHaveClass("ant-btn-dangerous");
  });
});
