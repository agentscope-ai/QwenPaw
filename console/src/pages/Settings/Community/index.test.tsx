// @vitest-environment jsdom
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CommunityConnectionStatus } from "@/api/modules/community";
import CommunitySettings from "./index";

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  start: vi.fn(),
  cancel: vi.fn(),
  disconnect: vi.fn(),
  setSync: vi.fn(),
  setMessageTypes: vi.fn(),
  sync: vi.fn(),
  notify: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
  external: vi.fn(),
}));
vi.mock("@/api/modules/community", () => ({ communityConnectionApi: mocks }));
vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: mocks.error },
    modal: { confirm: mocks.confirm },
  }),
}));
vi.mock("@/utils/inboxEvents", () => ({ notifyInboxChanged: mocks.notify }));
vi.mock("@/utils/openExternalLink", () => ({
  isDesktopTauriRuntime: () => false,
  openExternalLinkChecked: mocks.external,
}));
vi.mock("@/utils/pywebview", () => ({ getPyWebViewApi: () => undefined }));
vi.mock("@/components/PageHeader", () => ({ PageHeader: () => null }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const disconnected: CommunityConnectionStatus = {
  status: "disconnected",
  sync_enabled: false,
  messages_enabled: true,
};
const connected: CommunityConnectionStatus = {
  ...disconnected,
  status: "connected",
  sync_enabled: true,
  account: { id: "alice", display_name: "Alice" },
};
const flow = {
  flow_id: "flow-1",
  authorize_url:
    "https://platform.agentscope.io/cli/login?client_id=agentscope-platform-cli",
  expires_at: 9999999999,
};
let poll: () => void;

beforeEach(() => {
  vi.clearAllMocks();
  mocks.status.mockResolvedValue(disconnected);
  mocks.start.mockResolvedValue(flow);
  mocks.external.mockResolvedValue(undefined);
  mocks.cancel.mockResolvedValue(undefined);
  mocks.disconnect.mockResolvedValue(undefined);
  mocks.setSync.mockResolvedValue(undefined);
  const intervals = vi.spyOn(window, "setInterval");
  poll = () => {
    const callback = intervals.mock.calls.find(
      ([, delay]) => delay === 3000,
    )?.[0];
    if (typeof callback === "function") callback();
  };
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});
afterEach(() => vi.restoreAllMocks());

describe("community account settings", () => {
  it("disables login until a supported connection is configured", async () => {
    mocks.status.mockResolvedValue({
      ...disconnected,
      status: "not_configured",
    });
    render(<CommunitySettings />);
    await screen.findByText("community.not_configured");
    expect(
      screen.getByRole("button", { name: "community.connect" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("switch", { name: "community.syncTitle" }),
    ).toBeDisabled();
  });

  it("pauses sync while retaining the connected account", async () => {
    mocks.status
      .mockResolvedValueOnce(connected)
      .mockResolvedValue({ ...connected, sync_enabled: false });
    render(<CommunitySettings />);
    await screen.findByText("Alice");
    fireEvent.click(
      screen.getByRole("switch", { name: "community.syncTitle" }),
    );
    await waitFor(() => expect(mocks.setSync).toHaveBeenCalledWith(false));
    await waitFor(() =>
      expect(
        screen.getByRole("switch", { name: "community.syncTitle" }),
      ).not.toBeChecked(),
    );
    expect(screen.getByText("Alice")).toBeInTheDocument();
  });

  it("ignores a stale polling response after disconnect and clears old notices", async () => {
    mocks.status.mockResolvedValue(connected);
    render(<CommunitySettings />);
    await screen.findByText("Alice");
    let finish!: (status: CommunityConnectionStatus) => void;
    mocks.status.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    act(() => poll());
    const staleSignal = mocks.status.mock.calls[
      mocks.status.mock.calls.length - 1
    ]?.[0] as AbortSignal;
    mocks.status.mockResolvedValue(disconnected);
    fireEvent.click(
      screen.getByRole("button", { name: "community.disconnect" }),
    );
    await act(async () => mocks.confirm.mock.calls[0][0].onOk());
    expect(staleSignal.aborted).toBe(true);
    expect(mocks.notify).toHaveBeenCalledWith({ clearSources: ["community"] });
    await act(async () => finish(connected));
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();
    expect(screen.getByText("community.disconnected")).toBeInTheDocument();
  });

  it("clears account-scoped notices when authorization switches accounts", async () => {
    mocks.status.mockResolvedValueOnce(connected).mockResolvedValue({
      ...connected,
      account: { id: "bob", display_name: "Bob" },
    });
    render(<CommunitySettings />);
    await screen.findByText("Alice");
    act(() => poll());
    await screen.findByText("Bob");
    expect(mocks.notify).toHaveBeenCalledWith({ clearSources: ["community"] });
  });

  it("rejects an untrusted authorization URL when reopening a flow", async () => {
    mocks.status.mockResolvedValue({
      ...disconnected,
      status: "authorizing",
      authorization: {
        ...flow,
        authorize_url: "https://user:secret@platform.agentscope.io/cli/login",
      },
    });
    render(<CommunitySettings />);
    fireEvent.click(
      await screen.findByRole("button", { name: "community.reopen" }),
    );
    expect(mocks.external).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(mocks.error).toHaveBeenCalledWith(
        "communityErrors.invalidAuthorization",
      ),
    );
  });

  it("does not start authorization when a popup is blocked", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    render(<CommunitySettings />);
    fireEvent.click(
      await screen.findByRole("button", { name: "community.connect" }),
    );
    expect(mocks.start).not.toHaveBeenCalled();
    expect(mocks.error).toHaveBeenCalledWith("communityErrors.popupBlocked");
  });

  it("retains the authorization popup so explicit cancellation closes it", async () => {
    const popup = {
      opener: null,
      document: document.implementation.createHTMLDocument(),
      location: { replace: vi.fn() },
      close: vi.fn(),
    };
    vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    mocks.status.mockResolvedValueOnce(disconnected).mockResolvedValue({
      ...disconnected,
      status: "authorizing",
      authorization: flow,
    });
    render(<CommunitySettings />);
    fireEvent.click(
      await screen.findByRole("button", { name: "community.connect" }),
    );
    await waitFor(() =>
      expect(popup.location.replace).toHaveBeenCalledWith(flow.authorize_url),
    );
    const cancel = await screen.findByRole("button", { name: /common.cancel/ });
    mocks.status.mockResolvedValue(disconnected);
    fireEvent.click(cancel);
    await waitFor(() => expect(mocks.cancel).toHaveBeenCalledWith("flow-1"));
    expect(popup.close).toHaveBeenCalled();
  });
});

it("saves message type selections independently of the master switch", async () => {
  mocks.status.mockResolvedValue(connected);
  mocks.setMessageTypes.mockResolvedValue(undefined);
  render(<CommunitySettings />);
  fireEvent.click(
    await screen.findByRole("switch", {
      name: "community.messageTypes.interactions",
    }),
  );
  await waitFor(() =>
    expect(mocks.setMessageTypes).toHaveBeenCalledWith([
      "comments",
      "mentions",
      "feedback",
      "notifications",
    ]),
  );
  expect(mocks.setSync).not.toHaveBeenCalled();
});

it("shows network failures without exposing backend responses or losing the account", async () => {
  mocks.status.mockResolvedValue({
    ...connected,
    last_error: "network_unavailable",
  });
  render(<CommunitySettings />);
  expect(
    await screen.findByText("communityErrors.network"),
  ).toBeInTheDocument();
  expect(screen.getByText("Alice")).toBeInTheDocument();
  expect(screen.queryByText("community.messagesUnavailable")).toBeNull();
  expect(
    screen.getByRole("switch", { name: "community.syncTitle" }),
  ).toBeEnabled();
});
