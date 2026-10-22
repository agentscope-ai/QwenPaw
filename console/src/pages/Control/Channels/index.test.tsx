import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const confirm = vi.hoisted(() => vi.fn());
const updateChannelConfig = vi.hoisted(() => vi.fn());

vi.mock("@agentscope-ai/design", async () => vi.importActual("antd"));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "en" },
  }),
}));
vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { destroy: vi.fn(), error: vi.fn() },
    modal: { confirm },
  }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: Object.assign(
    () => ({ selectedAgent: "default", agents: [] }),
    { subscribe: () => () => {} },
  ),
}));
vi.mock("../../../api", () => ({
  default: {
    getAclAllPending: vi.fn().mockResolvedValue([]),
    updateChannelConfig,
  },
}));
vi.mock("./components", async () => {
  const { useState } = await import("react");
  const { ChannelDrawer } = await import("./components/ChannelDrawer");
  const ChannelButton = ({
    channelKey,
    onClick,
  }: {
    channelKey: string;
    onClick: () => void;
  }) => <button onClick={onClick}>{channelKey}</button>;
  return {
    ChannelDrawer,
    ChannelCard: ChannelButton,
    ChannelAvailableItem: ChannelButton,
    AccessControlDrawer: () => null,
    PendingApprovalsDrawer: () => null,
    getChannelLabel: (key: string) => key,
    useChannels: () => {
      const [channels, setChannels] = useState({
        telegram: { enabled: false, isBuiltin: true, bot_prefix: "" },
      });
      return {
        channels,
        setChannels,
        orderedKeys: ["telegram"],
        channelSchemas: {},
        isBuiltin: () => true,
        loading: false,
      };
    },
  };
});

import ChannelsPage from "./index";

beforeEach(() => {
  vi.clearAllMocks();
  updateChannelConfig.mockResolvedValue(undefined);
});

async function openTelegram() {
  fireEvent.click(screen.getByRole("button", { name: "telegram" }));
  await screen.findByRole("dialog");
}

async function discardDraft() {
  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  await act(async () => confirm.mock.calls[0][0].onOk());
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
}

describe("channel configuration drafts", () => {
  it("clears discarded optional values when reopening an unconfigured channel", async () => {
    render(<ChannelsPage />);
    await openTelegram();
    fireEvent.change(document.querySelector("input#http_proxy_auth")!, {
      target: { value: "discarded-auth" },
    });
    await discardDraft();
    await openTelegram();
    expect(document.querySelector("input#http_proxy_auth")).toHaveValue("");
    expect(updateChannelConfig).not.toHaveBeenCalled();
  });

  it("retains saved values when a later incomplete edit is discarded", async () => {
    render(<ChannelsPage />);
    await openTelegram();
    fireEvent.change(document.querySelector("input#bot_token")!, {
      target: { value: "saved-token" },
    });
    fireEvent.change(document.querySelector("input#http_proxy_auth")!, {
      target: { value: "saved-auth" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(updateChannelConfig).toHaveBeenCalledOnce();
    await openTelegram();
    fireEvent.change(document.querySelector("input#bot_token")!, {
      target: { value: "" },
    });
    fireEvent.change(document.querySelector("input#http_proxy_auth")!, {
      target: { value: "discarded-auth" },
    });
    await discardDraft();
    await openTelegram();
    expect(document.querySelector("input#bot_token")).toHaveValue(
      "saved-token",
    );
    expect(document.querySelector("input#http_proxy_auth")).toHaveValue(
      "saved-auth",
    );
    expect(updateChannelConfig).toHaveBeenCalledOnce();
  });
});
