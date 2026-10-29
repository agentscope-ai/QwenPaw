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
import {
  act,
  render,
  screen,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { Form } from "antd";
import type { FormInstance } from "antd";
import type { ChannelSaveJob } from "../../../../api/modules/channel";
import type { ChannelQrcodeConfig } from "./useChannelQrcode";

// ---- Hoisted mocks ---------------------------------------------------------

const langRef = vi.hoisted(() => ({ current: "en" }));
const mockOpenExternalLink = vi.hoisted(() => vi.fn());
const mockConfirm = vi.hoisted(() => vi.fn());
const mockMessage = vi.hoisted(() => ({
  destroy: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
}));

// design re-exports antd components; swap the wrapper library for antd so
// Form.useWatch / Form.useForm behave as real antd under jsdom.
vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
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

vi.mock("../../../../stores/agentStore", async () => {
  const { create } = await import("zustand");
  return {
    useAgentStore: create(() => ({
      selectedAgent: "agent-a",
      agents: [{ id: "agent-a", workspace_dir: "/ws" }],
    })),
  };
});

vi.mock("../../../../utils/openExternalLink", () => ({
  openExternalLink: (url: string) => mockOpenExternalLink(url),
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: mockMessage,
    modal: { confirm: mockConfirm },
  }),
}));

// Capture QR-code auth callbacks so tests can drive success/error paths.
vi.mock("./QrcodeAuthBlock", () => ({
  QrcodeAuthBlock: (props: ChannelQrcodeConfig) => {
    const { channel } = props;
    return (
      <div data-testid={`qr-${channel}`}>
        <button
          data-testid={`qr-success-${channel}`}
          onClick={() => {
            let taken = false;
            let cancelled = false;
            props.onSuccess(
              {
                client_id: "cid",
                client_secret: "cs",
                app_id: "aid",
                app_secret: "as",
                bot_token: "bt",
                base_url: "https://wechat-auth.example.test",
                bot_id: "bid",
                secret: "sec",
              },
              { agentId: props.agentId, channel, token: `auth-${channel}` },
              {
                take: () => {
                  if (cancelled) return false;
                  taken = true;
                  return true;
                },
                cancel: () => {
                  if (!taken) cancelled = true;
                },
              },
            );
          }}
        >
          qr-ok
        </button>
        <button
          data-testid={`qr-expired-${channel}`}
          onClick={() => props.onError("expired")}
        >
          qr-expired
        </button>
        <button
          data-testid={`qr-failed-${channel}`}
          onClick={() => props.onError("fail")}
        >
          qr-failed
        </button>
      </div>
    );
  },
}));

import { ChannelDrawer } from "./ChannelDrawer";
import styles from "../index.module.less";

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
  onSubmitSnapshot?: (job: ChannelSaveJob) => Promise<void | boolean>;
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
        onSubmitSnapshot={props.onSubmitSnapshot}
      />
    );
  }
  const utils = render(<Harness />);
  return { ...utils, form: capturedForm };
}

beforeEach(() => {
  langRef.current = "en";
  mockOpenExternalLink.mockClear();
  mockConfirm.mockClear();
  mockMessage.success.mockClear();
  mockMessage.error.mockClear();
  mockMessage.warning.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---- Builtin channel field branches ---------------------------------------

describe("ChannelDrawer builtin channel rendering", () => {
  it.each([
    {
      activeKey: "sip",
      adjacentValues: { sip_mode: "dev", sip_transport: "UDP" },
    },
    {
      activeKey: "mqtt",
      adjacentValues: { transport: "tcp", qos: "2" },
    },
  ])(
    "binds the $activeKey no-text switch to its narrow-container layout without touching adjacent values",
    async ({ activeKey, adjacentValues }) => {
      const { form } = renderDrawer({ activeKey });
      fireEvent.click(
        screen.getByRole("button", { name: "collapsed Advanced settings" }),
      );
      const noTextSwitch = screen.getByRole("switch", {
        name: /channels\.noTextDebounce/,
      });
      const formItem = noTextSwitch.closest(".ant-form-item");

      expect(formItem).toHaveClass(styles.noTextDebounceItem);
      fireEvent.click(noTextSwitch);
      await waitFor(() => {
        expect(form.getFieldValue("no_text_debounce")).toBe(false);
      });
      expect(form.getFieldsValue(true)).toMatchObject(adjacentValues);
    },
  );

  it("keeps SIP defaults and explicit values without duplicate initial-value warnings", async () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    const defaults = renderDrawer({ activeKey: "sip" });

    await waitFor(() => {
      expect(defaults.form.getFieldsValue(true)).toMatchObject({
        sip_mode: "dev",
        sip_transport: "UDP",
        no_text_debounce: true,
      });
    });
    defaults.unmount();

    const explicit = renderDrawer({
      activeKey: "sip",
      initialValues: {
        sip_mode: "livekit",
        sip_transport: "TLS",
        no_text_debounce: false,
      },
    });
    await waitFor(() => {
      expect(explicit.form.getFieldsValue(true)).toMatchObject({
        sip_mode: "livekit",
        sip_transport: "TLS",
        no_text_debounce: false,
      });
      expect(screen.getByText("channels.livekitUrl")).toBeTruthy();
    });
    expect(
      consoleError.mock.calls.some((call) =>
        call.some((value) =>
          String(value).includes("Form already set 'initialValues'"),
        ),
      ),
    ).toBe(false);
  });

  it("preserves the unsaved LiveKit draft while SIP mode toggles", async () => {
    const onSubmit = vi.fn();
    const view = renderDrawer({
      activeKey: "sip",
      initialValues: {
        sip_mode: "livekit",
        livekit_url: "wss://draft.example.test",
        livekit_api_key: "draft-key",
        livekit_api_secret: "draft-secret",
      },
      onSubmit,
    });

    await waitFor(() =>
      expect(view.form.getFieldValue("livekit_api_secret")).toBe(
        "draft-secret",
      ),
    );
    act(() => view.form.setFieldValue("sip_mode", "dev"));
    await waitFor(() =>
      expect(screen.queryByText("channels.livekitUrl")).toBeNull(),
    );
    expect(view.form.getFieldValue("livekit_api_secret")).toBe("draft-secret");

    act(() => view.form.setFieldValue("sip_mode", "livekit"));
    await screen.findByText("channels.livekitUrl");
    expect(view.form.getFieldValue("livekit_url")).toBe(
      "wss://draft.example.test",
    );
    expect(view.form.getFieldValue("livekit_api_key")).toBe("draft-key");
    expect(view.form.getFieldValue("livekit_api_secret")).toBe("draft-secret");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps MQTT defaults and explicit values in the submitted payload", async () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    const defaults = renderDrawer({ activeKey: "mqtt" });

    await waitFor(() => {
      expect(defaults.form.getFieldsValue(true)).toMatchObject({
        transport: "tcp",
        qos: "2",
        no_text_debounce: true,
      });
    });
    defaults.unmount();

    const onSubmit = vi.fn();
    const explicit = renderDrawer({
      activeKey: "mqtt",
      initialValues: {
        host: "broker.example.test",
        port: 1883,
        subscribe_topic: "server/+/up",
        publish_topic: "client/{client_id}/down",
        transport: "websockets",
        qos: "1",
        no_text_debounce: false,
      },
      onSubmit,
    });
    const botPrefixInputs =
      document.querySelectorAll<HTMLInputElement>("input#bot_prefix");
    fireEvent.change(botPrefixInputs.item(botPrefixInputs.length - 1), {
      target: { value: "@sentinel" },
    });
    await waitFor(() =>
      expect(explicit.form.getFieldValue("bot_prefix")).toBe("@sentinel"),
    );
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      host: "broker.example.test",
      transport: "websockets",
      qos: "1",
      no_text_debounce: false,
      bot_prefix: "@sentinel",
    });
    expect(explicit.form.getFieldValue("transport")).toBe("websockets");
    expect(
      consoleError.mock.calls.some((call) =>
        call.some((value) =>
          String(value).includes("Form already set 'initialValues'"),
        ),
      ),
    ).toBe(false);
  });

  it("renders matrix fields and switches to password auth when a password exists", async () => {
    renderDrawer({
      activeKey: "matrix",
      initialValues: { password: "secret-pw" },
    });
    await waitFor(() => {
      expect(screen.getByText("channels.fieldHomeserverURL")).toBeTruthy();
    });
    // The password-auth effect re-applies auth_method after mount, so the
    // password input becomes visible while access token is hidden.
    await waitFor(() => {
      const pw = screen.getByPlaceholderText("channels.fieldPassword");
      expect(pw).toBeTruthy();
    });
  });

  it("renders imessage, discord and slack fields", () => {
    const { unmount } = renderDrawer({ activeKey: "imessage" });
    expect(screen.getByText("channels.fieldDBPath")).toBeTruthy();
    expect(screen.getByText("channels.fieldPollIntervalsec")).toBeTruthy();
    unmount();

    const u2 = renderDrawer({ activeKey: "discord" });
    expect(
      screen.getAllByText("channels.wechatBotToken").length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("channels.fieldHTTPProxy")).toBeTruthy();
    u2.unmount();

    renderDrawer({ activeKey: "slack" });
    expect(screen.getByText("channels.slackAppToken")).toBeTruthy();
  });

  it("renders dingtalk fields and the card-template block when message_type=card", () => {
    const { unmount } = renderDrawer({ activeKey: "dingtalk" });
    expect(screen.getByText("channels.fieldClientID")).toBeTruthy();
    expect(screen.queryByText("channels.fieldCardTemplateID")).toBeNull();
    unmount();

    renderDrawer({
      activeKey: "dingtalk",
      initialValues: { message_type: "card" },
    });
    expect(screen.getByText("channels.fieldCardTemplateID")).toBeTruthy();
    expect(screen.getByText("channels.fieldCardTemplateKey")).toBeTruthy();
    expect(screen.getByText("channels.fieldRobotCode")).toBeTruthy();
  });

  it("renders feishu, qq, telegram and mqtt fields", () => {
    const { unmount } = renderDrawer({ activeKey: "feishu" });
    expect(screen.getByText("channels.fieldAppID")).toBeTruthy();
    expect(screen.getByText("channels.fieldEncryptKey")).toBeTruthy();
    unmount();

    const u2 = renderDrawer({ activeKey: "qq" });
    expect(screen.getByText("channels.fieldClientSecret")).toBeTruthy();
    u2.unmount();

    const u3 = renderDrawer({ activeKey: "telegram" });
    expect(screen.getByText("channels.fieldAPIBaseURL")).toBeTruthy();
    u3.unmount();

    renderDrawer({ activeKey: "mqtt" });
    expect(screen.getByText("channels.fieldMQTTHost")).toBeTruthy();
    expect(screen.getByText("channels.fieldMQTTPort")).toBeTruthy();
  });

  it("renders mattermost, voice, wecom, xiaoyi, wechat and yuanbao fields", () => {
    const { unmount } = renderDrawer({ activeKey: "mattermost" });
    expect(screen.getByText("channels.fieldMattermostURL")).toBeTruthy();
    unmount();

    const u2 = renderDrawer({ activeKey: "voice" });
    expect(screen.getByText("channels.twilioAccountSid")).toBeTruthy();
    // voice hides the bot prefix field
    expect(screen.queryByText("Bot Prefix")).toBeNull();
    u2.unmount();

    const u3 = renderDrawer({ activeKey: "wecom" });
    expect(screen.getByText("channels.fieldBotID")).toBeTruthy();
    u3.unmount();

    const u4 = renderDrawer({ activeKey: "xiaoyi" });
    expect(screen.getByText("channels.fieldAccessKeyAK")).toBeTruthy();
    u4.unmount();

    const u5 = renderDrawer({ activeKey: "wechat" });
    expect(screen.getByText("channels.wechatBotToken")).toBeTruthy();
    u5.unmount();

    renderDrawer({ activeKey: "yuanbao" });
    expect(screen.getByText("channels.fieldAPIDomain")).toBeTruthy();
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
    expect(screen.getByText("channels.fieldWebSocketHost")).toBeTruthy();
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

  it("shows auto-collapse thinking only for Feishu with streaming on", () => {
    const { unmount } = renderDrawer({
      activeKey: "feishu",
      initialValues: { streaming_enabled: true },
    });
    expect(screen.getByText("channels.autoCollapseThinking")).toBeTruthy();
    unmount();

    // Hidden while streaming output is disabled.
    const off = renderDrawer({
      activeKey: "feishu",
      initialValues: { streaming_enabled: false },
    });
    expect(screen.queryByText("channels.autoCollapseThinking")).toBeNull();
    off.unmount();

    // Not offered on other streaming channels: only Feishu renders a
    // collapsible reasoning panel.
    renderDrawer({
      activeKey: "dingtalk",
      initialValues: { streaming_enabled: true },
    });
    expect(screen.queryByText("channels.autoCollapseThinking")).toBeNull();
  });

  it.each([
    ["show_tool_calls", "toolCallMaxLength"],
    ["show_tool_results", "toolResultMaxLength"],
  ])("saves %s when its length field unmounts", async (field, length) => {
    const onSubmit = vi.fn();
    renderDrawer({
      activeKey: "console",
      onSubmit,
      initialValues: {
        show_tool_calls: true,
        show_tool_results: true,
        tool_call_max_length: 200,
        tool_result_max_length: 500,
      },
    });
    expect(screen.getByText(`channels.${length}`)).toBeTruthy();
    fireEvent.click(document.getElementById(field)!);
    expect(screen.queryByText(`channels.${length}`)).toBeNull();
    await waitFor(
      () =>
        expect(onSubmit).toHaveBeenCalledWith(
          expect.objectContaining({ [field]: false }),
        ),
      { timeout: 2000 },
    );
  });
});

// ---- QR-code auth callbacks ------------------------------------------------

describe("ChannelDrawer qrcode auth callbacks", () => {
  it.each([
    {
      channel: "dingtalk",
      credentials: { client_id: "cid", client_secret: "cs" },
      expired: "warning",
    },
    {
      channel: "feishu",
      credentials: { app_id: "aid", app_secret: "as" },
      expired: "warning",
    },
    {
      channel: "wechat",
      credentials: {
        bot_token: "bt",
        base_url: "https://wechat-auth.example.test",
      },
      expired: "warning",
    },
    {
      channel: "qq",
      credentials: { app_id: "aid", client_secret: "cs" },
      expired: "warning",
    },
    {
      channel: "wecom",
      credentials: { bot_id: "bid", secret: "sec" },
      expired: "error",
    },
  ] as const)(
    "$channel fills and saves authorized credentials",
    async ({ channel, credentials, expired }) => {
      const onSubmit = vi.fn();
      const onSubmitSnapshot = vi.fn().mockResolvedValue(true);
      const { form } = renderDrawer({
        activeKey: channel,
        isBuiltin: false,
        onSubmit,
        onSubmitSnapshot,
      });
      fireEvent.click(screen.getByTestId(`qr-success-${channel}`));
      for (const [field, value] of Object.entries(credentials)) {
        expect(form.getFieldValue(field)).toBe(value);
      }
      expect(mockMessage.success).toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "common.close" }));
      await waitFor(() => expect(onSubmitSnapshot).toHaveBeenCalledOnce());
      expect(onSubmitSnapshot).toHaveBeenCalledWith(
        expect.objectContaining({
          agentId: "agent-a",
          channel,
          authSession: `auth-${channel}`,
          body: expect.objectContaining(credentials),
        }),
      );
      expect(onSubmit).not.toHaveBeenCalled();
      fireEvent.click(screen.getByTestId(`qr-expired-${channel}`));
      expect(mockMessage[expired]).toHaveBeenCalled();
      mockMessage.error.mockClear();
      fireEvent.click(screen.getByTestId(`qr-failed-${channel}`));
      expect(mockMessage.error).toHaveBeenCalled();
    },
  );
});

// ---- Plugin schema fields + resolveLocalized --------------------------------

describe("ChannelDrawer plugin schema rendering", () => {
  it("renders the official form declared by a channel schema", () => {
    renderDrawer({
      activeKey: "renamed-dingtalk",
      isBuiltin: false,
      channelSchema: {
        form_kind: "dingtalk",
        config_fields: [],
      },
    });
    expect(screen.getByText("channels.fieldClientID")).toBeTruthy();
    expect(screen.getByText("channels.fieldClientSecret")).toBeTruthy();
  });
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
      isBuiltin: false,
      onSubmit,
      initialValues: {
        homeserver: "https://matrix.org",
        user_id: "@bot:matrix.org",
        access_token: "syt_token",
        auth_method: "token",
      },
    });
    fireEvent.change(document.querySelector("input#bot_prefix")!, {
      target: { value: "@new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
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
      isBuiltin: false,
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
        screen.getByPlaceholderText("channels.fieldPassword"),
      ).toBeTruthy();
    });
    fireEvent.change(document.querySelector("input#bot_prefix")!, {
      target: { value: "@new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
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
    fireEvent.change(document.querySelector("input#bot_prefix")!, {
      target: { value: "@new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const values = onSubmit.mock.calls[0][0];
    expect(values.bot_token).toBe("xoxb-1");
    expect(values.app_token).toBe("xapp-1");
  });

  it("closing an unchanged drawer does not submit", async () => {
    const onClose = vi.fn();
    const onSubmit = vi.fn();
    renderDrawer({ activeKey: "slack", onClose, onSubmit });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("lets users continue or discard a Telegram draft without its required token", async () => {
    const onClose = vi.fn();
    const onSubmit = vi.fn();
    renderDrawer({
      activeKey: "telegram",
      initialValues: { enabled: false, bot_token: "" },
      onClose,
      onSubmit,
    });
    fireEvent.change(document.querySelector("input#http_proxy_auth")!, {
      target: { value: "1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(mockConfirm).toHaveBeenCalledOnce());
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => mockConfirm.mock.calls[0][0].onCancel());
    expect(document.querySelector("input#http_proxy_auth")).toHaveValue("1");
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(mockConfirm).toHaveBeenCalledTimes(2));
    await act(async () => mockConfirm.mock.calls[1][0].onOk());
    expect(onClose).toHaveBeenCalledOnce();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("offers to discard a valid draft when the save request fails", async () => {
    const onClose = vi.fn();
    const onSubmit = vi.fn().mockRejectedValue(new Error("offline"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const view = renderDrawer({
      activeKey: "telegram",
      initialValues: { enabled: false, bot_token: "test-token" },
      onClose,
      onSubmit,
    });
    fireEvent.change(document.querySelector("input#http_proxy_auth")!, {
      target: { value: "draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(mockConfirm).toHaveBeenCalledOnce());
    await act(async () => mockConfirm.mock.calls[0][0].onOk());
    expect(onClose).toHaveBeenCalledOnce();
    view.unmount();
    await act(async () => {});
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("offers to discard when submission reports an unsuccessful save", async () => {
    const onClose = vi.fn();
    const onSubmit = vi.fn().mockResolvedValue(false);
    renderDrawer({
      activeKey: "telegram",
      initialValues: { bot_token: "test-token" },
      onClose,
      onSubmit,
    });
    fireEvent.change(document.querySelector("input#http_proxy_auth")!, {
      target: { value: "draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(mockConfirm).toHaveBeenCalledOnce());
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => mockConfirm.mock.calls[0][0].onOk());
    expect(onClose).toHaveBeenCalledOnce();
  });
});
