// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAgentStore } from "../../../stores/agentStore";

vi.mock("@agentscope-ai/design", async () => vi.importActual("antd"));
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      destroy: vi.fn(),
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
    },
    modal: { confirm: vi.fn() },
  }),
}));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "en" },
  }),
}));
vi.mock("../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));
vi.mock("@/components/interaction/Cascade", () => ({
  Cascade: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/PageHeader", () => ({ PageHeader: () => null }));
// Presentation boundaries only: page, data hook, drawer, QR block and API are real.
vi.mock("./components", async () => ({
  ChannelDrawer: (await import("./components/ChannelDrawer")).ChannelDrawer,
  useChannels: (await import("./useChannels")).useChannels,
  getChannelLabel: (key: string) => key,
  ChannelCard: ({
    channelKey,
    onClick,
  }: {
    channelKey: string;
    onClick: () => void;
  }) => <button onClick={onClick}>open-{channelKey}</button>,
  ChannelAvailableItem: ({
    channelKey,
    onClick,
  }: {
    channelKey: string;
    onClick: () => void;
  }) => <button onClick={onClick}>open-{channelKey}</button>,
  AccessControlDrawer: () => null,
  PendingApprovalsDrawer: () => null,
}));

import ChannelsPage from "./index";

const schemaRequests: {
  agent: string | null;
  resolve: (response: Response) => void;
}[] = [];
const counts = { channels: 0, types: 0, qr: 0 };
function json(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
function rows(available: boolean) {
  return {
    wechat: {
      label: "WeChat",
      description: "",
      plugin_id: "wechat",
      config_fields: [],
      availability: available ? "validated" : "running",
      qrcode_available: available,
    },
  };
}
async function resolveSchema(index: number, value: unknown) {
  await act(async () => schemaRequests[index].resolve(json(value)));
}
beforeEach(() => {
  schemaRequests.length = 0;
  counts.channels = counts.types = counts.qr = 0;
  useAgentStore.setState({ selectedAgent: "A", agents: [] });
  vi.stubGlobal(
    "fetch",
    async (input: string | URL | Request, init: RequestInit = {}) => {
      const path = new URL(String(input), "https://console.test").pathname;
      const agent = new Headers(init.headers).get("X-Agent-Id");
      if (init.method === "DELETE") return new Response(null, { status: 204 });
      if (path.endsWith("/schemas"))
        return new Promise<Response>((resolve) =>
          schemaRequests.push({ agent, resolve }),
        );
      if (path.endsWith("/channels")) {
        counts.channels += 1;
        return json({
          wechat: { enabled: false, bot_token: "saved-token", bot_prefix: "" },
        });
      }
      if (path.endsWith("/types")) {
        counts.types += 1;
        return json(["wechat"]);
      }
      if (path.endsWith("/qrcode")) {
        counts.qr += 1;
        return json({ qrcode_img: "cXI=", poll_token: "page-token" });
      }
      if (path.endsWith("/qrcode/status"))
        return json({ status: "waiting", credentials: {} });
      return json([]);
    },
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

it("refreshes QR availability each time the drawer opens and hides stale scan actions until the reply", async () => {
  render(<ChannelsPage />);
  await waitFor(() => expect(schemaRequests).toHaveLength(1));
  await resolveSchema(0, rows(false));
  fireEvent.click(screen.getByRole("button", { name: "open-wechat" }));
  await waitFor(() => expect(schemaRequests).toHaveLength(2));
  expect(
    screen.queryByRole("button", { name: "channels.wechatGetQrcode" }),
  ).toBeNull();
  await resolveSchema(1, rows(false));
  expect(
    screen.queryByRole("button", { name: "channels.wechatGetQrcode" }),
  ).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  fireEvent.click(await screen.findByRole("button", { name: "open-wechat" }));
  await waitFor(() => expect(schemaRequests).toHaveLength(3));
  expect(
    screen.queryByRole("button", { name: "channels.wechatGetQrcode" }),
  ).toBeNull();
  await resolveSchema(2, rows(true));
  fireEvent.click(
    screen.getByRole("button", { name: "channels.wechatGetQrcode" }),
  );
  expect(
    await screen.findByRole("img", { name: "WeChat QR Code" }),
  ).toBeTruthy();
  expect(counts).toEqual({ channels: 1, types: 1, qr: 1 });
  expect(schemaRequests.map((request) => request.agent)).toEqual([
    "A",
    "A",
    "A",
  ]);
});

it("hides a previously ready scan action while the reopened drawer refreshes", async () => {
  render(<ChannelsPage />);
  await waitFor(() => expect(schemaRequests).toHaveLength(1));
  await resolveSchema(0, rows(true));
  fireEvent.click(screen.getByRole("button", { name: "open-wechat" }));
  await waitFor(() => expect(schemaRequests).toHaveLength(2));
  expect(
    screen.queryByRole("button", { name: "channels.wechatGetQrcode" }),
  ).toBeNull();
  await resolveSchema(1, rows(true));
  expect(
    screen.getByRole("button", { name: "channels.wechatGetQrcode" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  fireEvent.click(await screen.findByRole("button", { name: "open-wechat" }));
  await waitFor(() => expect(schemaRequests).toHaveLength(3));
  expect(
    screen.queryByRole("button", { name: "channels.wechatGetQrcode" }),
  ).toBeNull();
  await resolveSchema(2, rows(false));
  expect(
    screen.queryByRole("button", { name: "channels.wechatGetQrcode" }),
  ).toBeNull();
  expect(counts.qr).toBe(0);
});

it.each(["http-failure", "missing-row"])(
  "keeps QR hidden when the initial schema request returns %s",
  async (outcome) => {
    render(<ChannelsPage />);
    await waitFor(() => expect(schemaRequests).toHaveLength(1));
    await act(async () =>
      schemaRequests[0].resolve(
        outcome === "http-failure"
          ? new Response("unavailable", { status: 503 })
          : json({}),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "open-wechat" }));
    await waitFor(() => expect(schemaRequests).toHaveLength(2));
    await act(async () =>
      schemaRequests[1].resolve(
        outcome === "http-failure"
          ? new Response("unavailable", { status: 503 })
          : json({}),
      ),
    );
    expect(
      screen.queryByRole("button", { name: "channels.wechatGetQrcode" }),
    ).toBeNull();
    expect(counts.qr).toBe(0);
  },
);

it("keeps stale ready QR hidden when the reopen refresh fails", async () => {
  render(<ChannelsPage />);
  await waitFor(() => expect(schemaRequests).toHaveLength(1));
  await resolveSchema(0, rows(true));
  fireEvent.click(screen.getByRole("button", { name: "open-wechat" }));
  await waitFor(() => expect(schemaRequests).toHaveLength(2));
  await resolveSchema(1, rows(true));
  expect(
    screen.getByRole("button", { name: "channels.wechatGetQrcode" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  fireEvent.click(await screen.findByRole("button", { name: "open-wechat" }));
  await waitFor(() => expect(schemaRequests).toHaveLength(3));
  await act(async () =>
    schemaRequests[2].resolve(new Response("unavailable", { status: 503 })),
  );
  expect(
    screen.queryByRole("button", { name: "channels.wechatGetQrcode" }),
  ).toBeNull();
  expect(counts.qr).toBe(0);
});
