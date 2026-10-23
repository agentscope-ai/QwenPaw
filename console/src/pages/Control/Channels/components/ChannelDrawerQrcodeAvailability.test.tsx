// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Form } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChannelSchema } from "../../../../api/modules/channel";
import zh from "../../../../locales/zh.json";

const h = vi.hoisted(() => ({
  fetch: vi.fn(),
  poll: vi.fn(),
  cancel: vi.fn(),
  message: {
    destroy: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));
vi.mock("@agentscope-ai/design", async () => vi.importActual("antd"));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      key === "channels.qrcodeInstallRequired"
        ? (zh.channels as Record<string, unknown>).qrcodeInstallRequired ?? key
        : typeof fallback === "string"
        ? fallback
        : key,
    i18n: { language: "zh" },
  }),
}));
vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: h.message }),
}));
vi.mock("../../../../api", () => ({
  api: {
    getChannelQrcode: h.fetch,
    getChannelQrcodeStatus: h.poll,
    cancelChannelQrcode: h.cancel,
  },
}));
vi.mock("../../../../stores/agentStore", async () => {
  const { create } = await import("zustand");
  return {
    useAgentStore: create(() => ({
      selectedAgent: "qr-agent",
      agents: [{ id: "qr-agent", workspace_dir: "/fixture" }],
    })),
  };
});

// Keep the real drawer, QR component and hook. Only the HTTP boundary is fake.
import { ChannelDrawer } from "./ChannelDrawer";

const channels = [
  ["feishu", "channels.feishuGetQrcode", "Feishu QR Code"],
  ["dingtalk", "channels.dingtalkGetQrcode", "DingTalk QR Code"],
  ["qq", "channels.qqGetQrcode", "QQ QR Code"],
  ["wecom", "channels.loginWeCom", "WeCom QR Code"],
  ["wechat", "channels.wechatGetQrcode", "WeChat QR Code"],
] as const;
type Schema = ChannelSchema & { qrcode_available?: boolean };

function schema(availability: string, available?: boolean): Schema {
  return {
    label: "Official QR channel",
    description: "",
    plugin_id: "fixture",
    config_fields: [],
    availability,
    ...(available === undefined ? {} : { qrcode_available: available }),
  };
}

function Harness({
  channel,
  value,
  open = true,
}: {
  channel: string;
  value: Schema;
  open?: boolean;
}) {
  const [form] = Form.useForm();
  return (
    <ChannelDrawer
      open={open}
      activeKey={channel}
      activeLabel={channel}
      form={form}
      saving={false}
      isBuiltin={false}
      initialValues={{ enabled: true }}
      channelSchema={value}
      onClose={() => {}}
      onSubmit={() => {}}
    />
  );
}

beforeEach(() => {
  h.fetch.mockReset().mockResolvedValue({
    qrcode_img: "fixture-png",
    poll_token: "fixture-token",
  });
  h.poll.mockReset().mockResolvedValue({ status: "waiting", credentials: {} });
  h.cancel.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

describe("official QR availability in the real channel drawer", () => {
  it.each(channels)(
    "%s shows only the install hint when code is missing",
    (channel, button, alt) => {
      render(
        <Harness channel={channel} value={schema("missing_code", false)} />,
      );
      expect(screen.getByText("安装插件后可扫码")).toBeTruthy();
      expect(screen.queryByRole("button", { name: button })).toBeNull();
      expect(screen.queryByRole("img", { name: alt })).toBeNull();
      expect(
        screen.queryByRole("button", { name: /安装|install/i }),
      ).toBeNull();
      expect(h.fetch).not.toHaveBeenCalled();
    },
  );

  it.each(channels)(
    "%s hides the QR entry for a retained lease even with stale validated status",
    (channel, button, alt) => {
      render(<Harness channel={channel} value={schema("validated", false)} />);
      expect(screen.queryByRole("button", { name: button })).toBeNull();
      expect(screen.queryByRole("img", { name: alt })).toBeNull();
      expect(screen.queryByText("安装插件后可扫码")).toBeNull();
    },
  );

  it.each(channels)(
    "%s removes an active QR image on stop and restores scanning after lease release",
    async (channel, button, alt) => {
      const view = render(
        <Harness channel={channel} value={schema("validated", true)} />,
      );
      fireEvent.click(screen.getByRole("button", { name: button }));
      expect(await screen.findByRole("img", { name: alt })).toBeTruthy();
      expect(h.fetch).toHaveBeenCalledWith(
        channel,
        channel === "feishu" ? { domain: "feishu" } : undefined,
        expect.objectContaining({
          agentId: "qr-agent",
          signal: expect.any(AbortSignal),
        }),
      );
      view.rerender(
        <Harness channel={channel} value={schema("stopping", false)} />,
      );
      expect(screen.queryByRole("button", { name: button })).toBeNull();
      expect(screen.queryByRole("img", { name: alt })).toBeNull();
      await waitFor(() =>
        expect(h.cancel).toHaveBeenCalledWith(channel, "fixture-token", {
          agentId: "qr-agent",
        }),
      );
      view.rerender(
        <Harness channel={channel} value={schema("validated", true)} />,
      );
      expect(screen.getByRole("button", { name: button })).toBeTruthy();
      expect(screen.queryByRole("img", { name: alt })).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: button }));
      expect(await screen.findByRole("img", { name: alt })).toBeTruthy();
      expect(h.fetch).toHaveBeenCalledTimes(2);
    },
  );

  it.each(["running", "stopping"])(
    "hides legacy %s availability without requiring the new optional field",
    (state) => {
      render(<Harness channel="wechat" value={schema(state)} />);
      expect(
        screen.queryByRole("button", { name: "channels.wechatGetQrcode" }),
      ).toBeNull();
    },
  );

  it("keeps existing fixtures scannable when the optional field is absent", async () => {
    render(<Harness channel="wechat" value={schema("validated")} />);
    fireEvent.click(
      screen.getByRole("button", { name: "channels.wechatGetQrcode" }),
    );
    expect(
      await screen.findByRole("img", { name: "WeChat QR Code" }),
    ).toBeTruthy();
  });
});
