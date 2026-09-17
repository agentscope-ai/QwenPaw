// @vitest-environment jsdom
/**
 * ChannelDrawer render + submit tests.
 *
 * Covers: builtin channel field branches (matrix/imessage/discord/dingtalk/
 * feishu/qq/telegram/slack/mqtt/mattermost/voice/sip/wecom/xiaoyi/wechat/
 * yuanbao/onebot), plugin-schema driven fields with localized labels
 * (resolveLocalized fallback chain), legacy custom-field fallback, matrix
 * auth-method submit branching, tool-call length gating, access control
 * gating, and the doc-link button (builtin EN/ZH + plugin schema doc_url).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Form } from "antd";
import type { FormInstance } from "antd";

// ---- Hoisted mocks ---------------------------------------------------------

const langRef = vi.hoisted(() => ({ current: "en" }));
const mockOpenExternalLink = vi.hoisted(() => vi.fn());
const mockMessage = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
}));

// design re-exports antd components; swap the wrapper library for antd so
// Form.useWatch / Form.useForm behave as real antd under jsdom.
vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) => {
      if (typeof fallback === "string") return fallback;
      if (
        fallback &&
        typeof fallback === "object" &&
        "defaultValue" in (fallback as Record<string, unknown>)
      ) {
        return (fallback as { defaultValue: string }).defaultValue;
      }
      return key;
    },
    i18n: {
      get language() {
        return langRef.current;
      },
    },
  }),
}));

vi.mock("../../../../stores/agentStore", () => ({
  useAgentStore: () => ({
    selectedAgent: "agent-a",
    agents: [{ id: "agent-a", workspace_dir: "/ws" }],
  }),
}));

vi.mock("../../../../utils/openExternalLink", () => ({
  openExternalLink: (url: string) => mockOpenExternalLink(url),
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));

// Capture QR-code auth callbacks so tests can drive success/error paths.
vi.mock("./QrcodeAuthBlock", () => ({
  QrcodeAuthBlock: (props: Record<string, unknown>) => {
    const channel = props.channel as string;
    return (
      <div data-testid={`qr-${channel}`}>
        <button
          data-testid={`qr-success-${channel}`}
          onClick={() =>
            (props.onSuccess as (c: Record<string, string>) => void)({
              client_id: "cid",
              client_secret: "cs",
              app_id: "aid",
              app_secret: "as",
              bot_token: "bt",
              bot_id: "bid",
              secret: "sec",
            })
          }
        >
          qr-ok
        </button>
        <button
          data-testid={`qr-expired-${channel}`}
          onClick={() => (props.onError as (t: string) => void)("expired")}
        >
          qr-expired
        </button>
        <button
          data-testid={`qr-failed-${channel}`}
          onClick={() => (props.onError as (t: string) => void)("failed")}
        >
          qr-failed
        </button>
      </div>
    );
  },
}));

import { ChannelDrawer } from "./ChannelDrawer";

// ---- Harness ---------------------------------------------------------------

interface DrawerProps {
  open?: boolean;
  activeKey?: string | null;
  activeLabel?: string;
  saving?: boolean;
  initialValues?: Record<string, unknown>;
  isBuiltin?: boolean;
  channelSchema?: unknown;
  onClose?: () => void;
  onSubmit?: (values: Record<string, unknown>) => void;
}

function renderDrawer(
  props: DrawerProps = {},
): { form: FormInstance } & ReturnType<typeof render> {
  let capturedForm!: FormInstance;
  function Harness() {
    const [form] = Form.useForm();
    capturedForm = form;
    return (
      <ChannelDrawer
        open={props.open ?? true}
        activeKey={props.activeKey === undefined ? "telegram" : props.activeKey}
        activeLabel={props.activeLabel ?? ""}
        form={form}
        saving={props.saving ?? false}
        initialValues={props.initialValues}
        isBuiltin={props.isBuiltin ?? true}
        channelSchema={props.channelSchema as never}
        onClose={props.onClose ?? (() => {})}
        onSubmit={props.onSubmit ?? (() => {})}
      />
    );
  }
  const utils = render(<Harness />);
  return { ...utils, form: capturedForm };
}

beforeEach(() => {
  langRef.current = "en";
  mockOpenExternalLink.mockClear();
  mockMessage.success.mockClear();
  mockMessage.error.mockClear();
  mockMessage.warning.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---- Builtin channel field branches ---------------------------------------

describe("ChannelDrawer builtin channel rendering", () => {
  it("renders matrix fields and switches to password auth when a password exists", async () => {
    renderDrawer({
      activeKey: "matrix",
      initialValues: { password: "secret-pw" },
    });
    await waitFor(() => {
      expect(screen.getByText("Homeserver URL")).toBeTruthy();
    });
    // The password-auth effect re-applies auth_method after mount, so the
    // password input becomes visible while access token is hidden.
    await waitFor(() => {
      const pw = screen.getByPlaceholderText("Account password for login");
      expect(pw).toBeTruthy();
    });
  });

  it("renders imessage, discord and slack fields", () => {
    const { unmount } = renderDrawer({ activeKey: "imessage" });
    expect(screen.getByText("DB Path")).toBeTruthy();
    expect(screen.getByText("Poll Interval (sec)")).toBeTruthy();
    unmount();

    const u2 = renderDrawer({ activeKey: "discord" });
    expect(screen.getAllByText("Bot Token").length).toBeGreaterThan(0);
    expect(screen.getByText("HTTP Proxy")).toBeTruthy();
    u2.unmount();

    renderDrawer({ activeKey: "slack" });
    expect(screen.getByText("App Token")).toBeTruthy();
  });

  it("renders dingtalk fields and the card-template block when message_type=card", () => {
    const { unmount } = renderDrawer({ activeKey: "dingtalk" });
    expect(screen.getByText("Client ID")).toBeTruthy();
    expect(screen.queryByText("Card Template ID")).toBeNull();
    unmount();

    renderDrawer({
      activeKey: "dingtalk",
      initialValues: { message_type: "card" },
    });
    expect(screen.getByText("Card Template ID")).toBeTruthy();
    expect(screen.getByText("Card Template Key")).toBeTruthy();
    expect(screen.getByText("Robot Code")).toBeTruthy();
  });

  it("renders feishu, qq, telegram and mqtt fields", () => {
    const { unmount } = renderDrawer({ activeKey: "feishu" });
    expect(screen.getByText("App ID")).toBeTruthy();
    expect(screen.getByText("Encrypt Key")).toBeTruthy();
    unmount();

    const u2 = renderDrawer({ activeKey: "qq" });
    expect(screen.getByText("Client Secret")).toBeTruthy();
    u2.unmount();

    const u3 = renderDrawer({ activeKey: "telegram" });
    expect(screen.getByText("API Base URL")).toBeTruthy();
    u3.unmount();

    renderDrawer({ activeKey: "mqtt" });
    expect(screen.getByText("MQTT Host")).toBeTruthy();
    expect(screen.getByText("MQTT Port")).toBeTruthy();
  });

  it("renders mattermost, voice, wecom, xiaoyi, wechat and yuanbao fields", () => {
    const { unmount } = renderDrawer({ activeKey: "mattermost" });
    expect(screen.getByText("Mattermost URL")).toBeTruthy();
    unmount();

    const u2 = renderDrawer({ activeKey: "voice" });
    expect(screen.getByText("channels.twilioAccountSid")).toBeTruthy();
    // voice hides the bot prefix field
    expect(screen.queryByText("Bot Prefix")).toBeNull();
    u2.unmount();

    const u3 = renderDrawer({ activeKey: "wecom" });
    expect(screen.getByText("Bot ID")).toBeTruthy();
    u3.unmount();

    const u4 = renderDrawer({ activeKey: "xiaoyi" });
    expect(screen.getByText("Access Key (AK)")).toBeTruthy();
    u4.unmount();

    const u5 = renderDrawer({ activeKey: "wechat" });
    expect(screen.getByText("channels.wechatBotToken")).toBeTruthy();
    u5.unmount();

    renderDrawer({ activeKey: "yuanbao" });
    expect(screen.getByText("API Domain")).toBeTruthy();
  });

  it("renders sip fields and the livekit block when sip_mode=livekit", () => {
    const { unmount } = renderDrawer({ activeKey: "sip" });
    expect(screen.getByText("channels.sipMode")).toBeTruthy();
    expect(screen.queryByText("channels.livekitUrl")).toBeNull();
    unmount();

    renderDrawer({ activeKey: "sip", initialValues: { sip_mode: "livekit" } });
    expect(screen.getByText("channels.livekitUrl")).toBeTruthy();
    expect(screen.getByText("channels.livekitApiKey")).toBeTruthy();
  });

  it("renders onebot fields and gates the base64 size field on media_base64", () => {
    const { unmount } = renderDrawer({
      activeKey: "onebot",
      initialValues: { ws_host: "127.0.0.1" },
    });
    expect(screen.getByText("WebSocket Host")).toBeTruthy();
    expect(screen.queryByText("channels.onebotMediaBase64MaxMb")).toBeNull();
    unmount();

    renderDrawer({
      activeKey: "onebot",
      initialValues: { media_base64: true, ws_host: "0.0.0.0" },
    });
    expect(screen.getByText("channels.onebotMediaBase64MaxMb")).toBeTruthy();
  });

  it("renders console without show_thinking/debounce and with a disabled enable switch", () => {
    renderDrawer({ activeKey: "console" });
    expect(screen.queryByText("channels.showThinking")).toBeNull();
    expect(screen.queryByText("channels.noTextDebounce")).toBeNull();
    // console is not in the access-control list
    expect(screen.queryByText("channels.accessControlDm")).toBeNull();
  });

  it("shows access control fields only for controlled channels", () => {
    const { unmount } = renderDrawer({ activeKey: "telegram" });
    expect(screen.getByText("channels.accessControlDm")).toBeTruthy();
    expect(screen.getByText("channels.requireMention")).toBeTruthy();
    unmount();

    renderDrawer({ activeKey: "sip" });
    expect(screen.queryByText("channels.accessControlDm")).toBeNull();
  });

  it("shows streaming_enabled only for streaming-capable channels", () => {
    const { unmount } = renderDrawer({ activeKey: "telegram" });
    expect(screen.getByText("channels.streamingEnabled")).toBeTruthy();
    unmount();

    renderDrawer({ activeKey: "qq" });
    expect(screen.queryByText("channels.streamingEnabled")).toBeNull();
  });

  it("hides tool-call/result length inputs when the toggles are off", () => {
    const { unmount } = renderDrawer({ activeKey: "telegram" });
    // default: both toggles on, length fields present
    expect(screen.getByText("channels.toolCallMaxLength")).toBeTruthy();
    expect(screen.getByText("channels.toolResultMaxLength")).toBeTruthy();
    unmount();

    renderDrawer({
      activeKey: "telegram",
      initialValues: { show_tool_calls: false, show_tool_results: false },
    });
    expect(screen.queryByText("channels.toolCallMaxLength")).toBeNull();
    expect(screen.queryByText("channels.toolResultMaxLength")).toBeNull();
  });
});

// ---- QR-code auth callbacks ------------------------------------------------

describe("ChannelDrawer qrcode auth callbacks", () => {
  it("dingtalk success fills credentials and reports error states", () => {
    const { form } = renderDrawer({ activeKey: "dingtalk" });
    fireEvent.click(screen.getByTestId("qr-success-dingtalk"));
    expect(form.getFieldValue("client_id")).toBe("cid");
    expect(form.getFieldValue("client_secret")).toBe("cs");
    expect(mockMessage.success).toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("qr-expired-dingtalk"));
    expect(mockMessage.warning).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("qr-failed-dingtalk"));
    expect(mockMessage.error).toHaveBeenCalled();
  });

  it("feishu success fills app credentials", () => {
    const { form } = renderDrawer({ activeKey: "feishu" });
    fireEvent.click(screen.getByTestId("qr-success-feishu"));
    expect(form.getFieldValue("app_id")).toBe("aid");
    expect(form.getFieldValue("app_secret")).toBe("as");
    expect(mockMessage.success).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("qr-expired-feishu"));
    expect(mockMessage.warning).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("qr-failed-feishu"));
    expect(mockMessage.error).toHaveBeenCalled();
  });

  it("wechat success fills bot token and reports failures", () => {
    const { form } = renderDrawer({ activeKey: "wechat" });
    fireEvent.click(screen.getByTestId("qr-success-wechat"));
    expect(form.getFieldValue("bot_token")).toBe("bt");
    expect(mockMessage.success).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("qr-expired-wechat"));
    expect(mockMessage.warning).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("qr-failed-wechat"));
    expect(mockMessage.error).toHaveBeenCalled();
  });

  it("qq success fills credentials and reports failures", () => {
    const { form } = renderDrawer({ activeKey: "qq" });
    fireEvent.click(screen.getByTestId("qr-success-qq"));
    expect(form.getFieldValue("app_id")).toBe("aid");
    expect(form.getFieldValue("client_secret")).toBe("cs");
    expect(mockMessage.success).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("qr-expired-qq"));
    expect(mockMessage.warning).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("qr-failed-qq"));
    expect(mockMessage.error).toHaveBeenCalled();
  });

  it("wecom success fills bot credentials and any error reports failure", () => {
    const { form } = renderDrawer({ activeKey: "wecom" });
    fireEvent.click(screen.getByTestId("qr-success-wecom"));
    expect(form.getFieldValue("bot_id")).toBe("bid");
    expect(form.getFieldValue("secret")).toBe("sec");
    expect(mockMessage.success).toHaveBeenCalled();
    // wecom uses a single onError handler for every failure type
    fireEvent.click(screen.getByTestId("qr-expired-wecom"));
    expect(mockMessage.error).toHaveBeenCalled();
    mockMessage.error.mockClear();
    fireEvent.click(screen.getByTestId("qr-failed-wecom"));
    expect(mockMessage.error).toHaveBeenCalled();
  });
});

// ---- Plugin schema fields + resolveLocalized --------------------------------

describe("ChannelDrawer plugin schema rendering", () => {
  it("renders all schema field types with localized labels", () => {
    const schema = {
      description: "Plugin description",
      doc_url: "https://example.com/docs",
      config_fields: [
        {
          name: "api_key",
          label: { en: "API Key" },
          help: { en: "help en" },
          placeholder: "pk-...",
          type: "password",
          required: true,
          default: "dflt",
        },
        { name: "max_retries", label: "Max Retries", type: "number" },
        { name: "verbose", label: "Verbose", type: "switch" },
        {
          name: "mode",
          label: "Mode",
          type: "select",
          options: ["fast", "safe"],
        },
        { name: "note", label: "Note", type: "text" },
      ],
    };
    renderDrawer({
      activeKey: "myplugin",
      isBuiltin: false,
      channelSchema: schema,
      initialValues: {},
    });

    expect(screen.getByText("Plugin description")).toBeTruthy();
    expect(screen.getByText("API Key")).toBeTruthy();
    expect(screen.getByText("Max Retries")).toBeTruthy();
    expect(screen.getByText("Verbose")).toBeTruthy();
    expect(screen.getByText("Mode")).toBeTruthy();
    expect(screen.getByText("Note")).toBeTruthy();
  });

  it("falls back through the localization chain for dict labels", () => {
    const schema = {
      config_fields: [
        // no exact "en", no short "en", prefix "en-US" matches via prefix rule
        { name: "a", label: { "en-US": "Prefix Match" }, type: "text" },
        // no english at all → chinese fallback
        { name: "b", label: { "zh-CN": "中文回退" }, type: "text" },
        // unknown locale only → any non-empty value
        { name: "c", label: { fr: "Bonjour" }, type: "text" },
        // non-string non-object → String()
        { name: "d", label: 42, type: "text" },
        // null → empty label
        { name: "e", label: null, type: "text" },
      ],
    };
    renderDrawer({
      activeKey: "myplugin",
      isBuiltin: false,
      channelSchema: schema,
      initialValues: {},
    });

    expect(screen.getByText("Prefix Match")).toBeTruthy();
    expect(screen.getByText("中文回退")).toBeTruthy();
    expect(screen.getByText("Bonjour")).toBeTruthy();
    expect(screen.getByText("42")).toBeTruthy();
  });

  it("renders legacy custom fields inferred from initial values", () => {
    renderDrawer({
      activeKey: "legacy",
      isBuiltin: false,
      initialValues: {
        enabled: true,
        bot_prefix: "@x",
        custom_str: "v",
        custom_num: 5,
        custom_bool: true,
      },
    });
    expect(screen.getByText("Custom Fields")).toBeTruthy();
    expect(screen.getByText("custom_str")).toBeTruthy();
    expect(screen.getByText("custom_num")).toBeTruthy();
    expect(screen.getByText("custom_bool")).toBeTruthy();
    // BASE_FIELDS are not re-rendered as custom fields
    expect(screen.queryByText("bot_prefix")).toBeNull();
  });

  it("renders no extra fields when a custom channel has neither schema nor values", () => {
    renderDrawer({
      activeKey: "empty",
      isBuiltin: false,
      initialValues: undefined,
    });
    expect(screen.queryByText("Custom Fields")).toBeNull();
  });

  it("validates the wechat message merge delay validator", async () => {
    // valid integer passes
    const ok = renderDrawer({
      activeKey: "wechat",
      initialValues: { message_merge_enabled: true },
    });
    expect(screen.getByText("channels.wechatMessageMergeDelayMs")).toBeTruthy();
    await ok.form.validateFields(["message_merge_delay_ms"]);

    // empty string also passes (no-op branch)
    ok.form.setFieldsValue({ message_merge_delay_ms: "" });
    await ok.form.validateFields(["message_merge_delay_ms"]);

    // negative / non-integer rejects
    ok.form.setFieldsValue({ message_merge_delay_ms: -5 });
    await expect(
      ok.form.validateFields(["message_merge_delay_ms"]),
    ).rejects.toBeTruthy();
    ok.unmount();

    const bad = renderDrawer({
      activeKey: "wechat",
      initialValues: {
        message_merge_enabled: true,
        message_merge_delay_ms: 1.5,
      },
    });
    await expect(
      bad.form.validateFields(["message_merge_delay_ms"]),
    ).rejects.toBeTruthy();
  });

  it("renders the generic settings title when no channel is active", async () => {
    renderDrawer({ activeKey: null, activeLabel: "" });
    await screen.findByText("channels.channelSettings");
    // no form body is rendered without an active channel
    expect(screen.queryByText("channels.showToolCalls")).toBeNull();
  });
});

// ---- Doc link button ---------------------------------------------------------

describe("ChannelDrawer doc link", () => {
  it("opens the EN doc URL for builtin channels under the EN UI", () => {
    renderDrawer({ activeKey: "dingtalk" });
    fireEvent.click(screen.getByText("DingTalk Doc"));
    expect(mockOpenExternalLink).toHaveBeenCalledWith(
      expect.stringContaining("?lang=en#DingTalk"),
    );
  });

  it("opens the ZH doc URL for builtin channels under the ZH UI", () => {
    langRef.current = "zh-CN";
    renderDrawer({ activeKey: "dingtalk" });
    fireEvent.click(screen.getByText("DingTalk Doc"));
    expect(mockOpenExternalLink).toHaveBeenCalledWith(
      expect.stringContaining("?lang=zh#"),
    );
  });

  it("renders a schema doc_url button for plugin channels", () => {
    renderDrawer({
      activeKey: "myplugin",
      isBuiltin: false,
      channelSchema: {
        doc_url: "https://example.com/docs",
        config_fields: [],
      },
      initialValues: {},
    });
    fireEvent.click(screen.getByText("Myplugin Doc"));
    expect(mockOpenExternalLink).toHaveBeenCalledWith(
      "https://example.com/docs",
    );
  });

  it("hides the plugin doc button when doc_url is not an http URL", () => {
    renderDrawer({
      activeKey: "myplugin",
      isBuiltin: false,
      channelSchema: { doc_url: "not-a-url", config_fields: [] },
      initialValues: {},
    });
    expect(screen.queryByText("Myplugin Doc")).toBeNull();
  });

  it("voice links to the Twilio console", () => {
    renderDrawer({ activeKey: "voice" });
    fireEvent.click(screen.getByText("channels.voiceSetupLink"));
    expect(mockOpenExternalLink).toHaveBeenCalledWith(
      "https://console.twilio.com",
    );
  });
});

// ---- Matrix submit branching ------------------------------------------------

describe("ChannelDrawer matrix submit", () => {
  it("token auth submits with password cleared and encryption disabled", async () => {
    const onSubmit = vi.fn();
    renderDrawer({
      activeKey: "matrix",
      onSubmit,
      initialValues: {
        homeserver: "https://matrix.org",
        user_id: "@bot:matrix.org",
        access_token: "syt_token",
      },
    });
    fireEvent.click(screen.getByText("common.save"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const values = onSubmit.mock.calls[0][0];
    expect(values.password).toBe("");
    expect(values.encryption).toBe(false);
    expect(values.access_token).toBe("syt_token");
    expect("auth_method" in values).toBe(false);
  });

  it("password auth submits with access_token cleared", async () => {
    const onSubmit = vi.fn();
    renderDrawer({
      activeKey: "matrix",
      onSubmit,
      initialValues: {
        homeserver: "https://matrix.org",
        user_id: "@bot:matrix.org",
        password: "pw-secret",
      },
    });
    // wait for the password-auth effect to flip auth_method
    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Account password for login"),
      ).toBeTruthy();
    });
    fireEvent.click(screen.getByText("common.save"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const values = onSubmit.mock.calls[0][0];
    expect(values.access_token).toBe("");
    expect(values.password).toBe("pw-secret");
  });

  it("non-matrix channels submit values untouched", async () => {
    const onSubmit = vi.fn();
    renderDrawer({
      activeKey: "slack",
      onSubmit,
      initialValues: { bot_token: "xoxb-1", app_token: "xapp-1" },
    });
    fireEvent.click(screen.getByText("common.save"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const values = onSubmit.mock.calls[0][0];
    expect(values.bot_token).toBe("xoxb-1");
    expect(values.app_token).toBe("xapp-1");
  });

  it("cancel button closes the drawer without submitting", () => {
    const onClose = vi.fn();
    const onSubmit = vi.fn();
    renderDrawer({ activeKey: "slack", onClose, onSubmit });
    fireEvent.click(screen.getByText("common.cancel"));
    expect(onClose).toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
