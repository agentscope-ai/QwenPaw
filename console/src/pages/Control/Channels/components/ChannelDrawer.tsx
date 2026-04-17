import {
  Drawer,
  Form,
  Input,
  InputNumber,
  Switch,
  Button,
  Select,
} from "@agentscope-ai/design";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { Alert, ConfigProvider, Spin } from "antd";
import { LinkOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { FormInstance } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { getChannelLabel, type ChannelKey } from "./constants";
import { useChannelQrcode } from "./useChannelQrcode";
import styles from "../index.module.less";
import { useTheme } from "../../../../contexts/ThemeContext";
import api from "../../../../api";

const CHANNELS_WITH_ACCESS_CONTROL: ChannelKey[] = [
  "telegram",
  "dingtalk",
  "discord",
  "feishu",
  "wecom",
  "mattermost",
  "matrix",
  "weixin",
  "imessage",
  "onebot",
  "signal",
];

// Doc EN URLs per channel (anchors on https://qwenpaw.agentscope.io/docs/channels)
const CHANNEL_DOC_EN_URLS: Partial<Record<ChannelKey, string>> = {
  dingtalk:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=en#DingTalk-recommended",
  feishu: "https://qwenpaw.agentscope.io/docs/channels/?lang=en#Feishu-Lark",
  imessage:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=en#iMessage-macOS-only",
  discord: "https://qwenpaw.agentscope.io/docs/channels/?lang=en#Discord",
  qq: "https://qwenpaw.agentscope.io/docs/channels/?lang=en#QQ",
  telegram: "https://qwenpaw.agentscope.io/docs/channels/?lang=en#Telegram",
  mqtt: "https://qwenpaw.agentscope.io/docs/channels/?lang=en#MQTT",
  mattermost: "https://qwenpaw.agentscope.io/docs/channels/?lang=en#Mattermost",
  matrix: "https://qwenpaw.agentscope.io/docs/channels/?lang=en#Matrix",
  wecom:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=en#WeCom-WeChat-Work",
  weixin:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=en#WeChat-Personal-iLink",
  xiaoyi:
    "https://developer.huawei.com/consumer/cn/doc/service/openclaw-0000002518410344",
  onebot:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=en#OneBot-v11-NapCat--QQ-full-protocol",
  signal: "https://qwenpaw.agentscope.io/docs/channels/?lang=en#Signal",
};

// Doc ZH URLs per channel (anchors on https://qwenpaw.agentscope.io/docs/channels)
const CHANNEL_DOC_ZH_URLS: Partial<Record<ChannelKey, string>> = {
  dingtalk: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#钉钉推荐",
  feishu: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#飞书",
  imessage:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#iMessage仅-macOS",
  discord: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#Discord",
  qq: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#QQ",
  telegram: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#Telegram",
  mqtt: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#MQTT",
  mattermost: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#Mattermost",
  matrix: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#Matrix",
  wecom: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#企业微信",
  weixin: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#微信个人iLink",
  xiaoyi:
    "https://developer.huawei.com/consumer/cn/doc/service/openclaw-0000002518410344",
  onebot:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#OneBot-v11NapCat--QQ-完整协议",
  signal: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#Signal",
};

const TWILIO_CONSOLE_URL = "https://console.twilio.com";

const BASE_FIELDS = [
  "enabled",
  "bot_prefix",
  "filter_tool_messages",
  "filter_thinking",
  "isBuiltin",
];

interface ChannelDrawerProps {
  open: boolean;
  activeKey: ChannelKey | null;
  activeLabel: string;
  form: FormInstance<Record<string, unknown>>;
  saving: boolean;
  initialValues: Record<string, unknown> | undefined;
  isBuiltin: boolean;
  onClose: () => void;
  onSubmit: (values: Record<string, unknown>) => void;
}

export function ChannelDrawer({
  open,
  activeKey,
  activeLabel,
  form,
  saving,
  initialValues,
  isBuiltin,
  onClose,
  onSubmit,
}: ChannelDrawerProps) {
  const { t, i18n } = useTranslation();
  const { isDark } = useTheme();
  const currentLang = i18n.language?.startsWith("zh") ? "zh" : "en";
  const label = activeKey ? getChannelLabel(activeKey, t) : activeLabel;
  const { message } = useAppMessage();

  // WeChat QR code hook
  const weixinQrcode = useChannelQrcode({
    channel: "weixin",
    successStatus: "confirmed",
    successCredentialKey: "bot_token",
    pollInterval: 2000,
    onSuccess: useCallback(
      (credentials: Record<string, string>) => {
        form.setFieldsValue({ bot_token: credentials.bot_token });
        message.success(t("channels.weixinLoginSuccess"));
      },
      [form, message, t],
    ),
    onError: useCallback(
      (type: "fetch" | "expired") => {
        if (type === "expired") {
          message.warning(t("channels.weixinQrcodeExpired"));
        } else {
          message.error(t("channels.weixinQrcodeFailed"));
        }
      },
      [message, t],
    ),
  });

  // DingTalk QR code hook
  const dingtalkQrcode = useChannelQrcode({
    channel: "dingtalk",
    successStatus: "success",
    successCredentialKey: "client_id",
    pollInterval: 5000,
    onSuccess: useCallback(
      (credentials: Record<string, string>) => {
        form.setFieldsValue({
          client_id: credentials.client_id,
          client_secret: credentials.client_secret,
        });
        message.success(t("channels.dingtalkAuthSuccess"));
      },
      [form, message, t],
    ),
    onExpired: useCallback(() => {
      message.warning(t("channels.dingtalkQrcodeExpired"));
    }, [message, t]),
    onError: useCallback(
      (type: "fetch" | "expired") => {
        if (type === "expired") {
          message.warning(t("channels.dingtalkQrcodeExpired"));
        } else {
          message.error(t("channels.dingtalkQrcodeFailed"));
        }
      },
      [message, t],
    ),
  });

  // WeCom QR code hook
  const wecomQrcode = useChannelQrcode({
    channel: "wecom",
    successStatus: "success",
    successCredentialKey: "bot_id",
    pollInterval: 3000,
    onSuccess: useCallback(
      (credentials: Record<string, string>) => {
        form.setFieldsValue({
          bot_id: credentials.bot_id,
          secret: credentials.secret,
        });
        message.success(t("channels.wecomAuthSuccess"));
      },
      [form, message, t],
    ),
    onError: useCallback(
      (_type: "fetch" | "expired") => {
        message.error(t("channels.wecomQrcodeFailed"));
      },
      [message, t],
    ),
  });

  // ── Signal link flow state ──────────────────────────────────────────
  // Parallels WhatsApp's waPhone / waQrImage / waPairStatus pattern but
  // with signal-cli subprocess semantics: no phone-number param (the
  // subprocess returns one), QR is the only path (no pair-code fallback).
  const [sigLinked, setSigLinked] = useState(false);
  const [sigPhone, setSigPhone] = useState<string>("");
  // UUID is not shown in the drawer but is stored on the form; the
  // setter is still useful for that purpose (hence the _ prefix — it
  // signals "intentionally unread state" to Copilot / strict-TS).
  const [, setSigUuid] = useState<string>("");
  const [sigQrImage, setSigQrImage] = useState<string>("");
  const [sigPairStatus, setSigPairStatus] = useState<string>("idle");
  const [sigPairLoading, setSigPairLoading] = useState(false);
  const [sigDeviceName, setSigDeviceName] = useState<string>("QwenPaw");
  const sigPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Directory options for the Signal drawer dropdowns. Populated from
  // backend /channels/signal/{contacts,groups} when linked.
  const [sigContacts, setSigContacts] = useState<
    Array<{ number: string; uuid: string; name: string }>
  >([]);
  const [sigGroups, setSigGroups] = useState<
    Array<{ id: string; blocked: boolean }>
  >([]);

  const stopSigPoll = useCallback(() => {
    if (sigPollRef.current) {
      clearInterval(sigPollRef.current);
      sigPollRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (activeKey === "signal") {
      api
        .getSignalStatus()
        .then((s) => {
          setSigLinked(Boolean(s.linked));
          if (s.linked) {
            setSigPairStatus("linked");
            if (s.phone) setSigPhone(s.phone);
            if (s.uuid) setSigUuid(s.uuid);
            // Auto-populate account / account_uuid from the authoritative
            // signal-cli account store. Users shouldn't have to type in the
            // phone number after linking — the backend already knows it.
            // Only fill when the form field is empty to avoid clobbering a
            // user-entered override.
            const currentAccount = form.getFieldValue("account");
            const currentUuid = form.getFieldValue("account_uuid");
            const patch: Record<string, string> = {};
            if (!currentAccount && s.phone) patch.account = s.phone;
            if (!currentUuid && s.uuid) patch.account_uuid = s.uuid;
            if (Object.keys(patch).length) form.setFieldsValue(patch);
            // Fetch contacts + groups to populate the allow_from /
            // group_allow_from / groups dropdowns so users don't have
            // to type raw phone numbers or base64 group ids.
            api
              .listSignalContacts()
              .then((r) => setSigContacts(r.contacts || []))
              .catch(() => setSigContacts([]));
            api
              .listSignalGroups()
              .then((r) => setSigGroups(r.groups || []))
              .catch(() => setSigGroups([]));
          } else {
            setSigContacts([]);
            setSigGroups([]);
          }
        })
        .catch(() => {
          /* ignore — endpoint may be 404 on older backends */
        });
    }
    return () => {
      stopSigPoll();
    };
  }, [activeKey, stopSigPoll, form]);

  const handleSignalLink = useCallback(async () => {
    stopSigPoll();
    setSigPairLoading(true);
    setSigQrImage("");
    setSigPairStatus("starting");
    try {
      const data = await api.startSignalLink(sigDeviceName || "QwenPaw");
      if (data.qr_image) {
        setSigQrImage(data.qr_image);
        setSigPairStatus(data.status || "waiting_qr");
      }
      // Poll for completion. Slightly longer interval than WhatsApp
      // (3s) because signal-cli link rarely confirms in under 10s.
      sigPollRef.current = setInterval(async () => {
        try {
          const s = await api.checkSignalLinkStatus();
          if (s.status === "linked") {
            stopSigPoll();
            setSigQrImage("");
            setSigPairStatus("linked");
            setSigLinked(true);
            if (s.phone) setSigPhone(s.phone);
            if (s.uuid) setSigUuid(s.uuid);
            setSigPairLoading(false);
            form.setFieldsValue({
              account: s.phone || "",
              account_uuid: s.uuid || "",
            });
            // Auto-persist account + account_uuid to agent config so the
            // Signal channel can start against the linked account without
            // the user having to click Save. Other form fields (enabled,
            // policies, etc.) still require explicit Save — we only push
            // the two values signal-cli itself just authoritative-told us.
            if (s.phone || s.uuid) {
              const allFields = form.getFieldsValue();
              const persisted: Record<string, unknown> = {
                ...allFields,
                account: s.phone || allFields.account || "",
                account_uuid: s.uuid || allFields.account_uuid || "",
                filter_tool_messages: !allFields.filter_tool_messages,
                filter_thinking: !allFields.filter_thinking,
              };
              api
                .updateChannelConfig(
                  "signal",
                  persisted as unknown as Parameters<
                    typeof api.updateChannelConfig
                  >[1],
                )
                .catch((err) => {
                  // Non-fatal: user can still click Save manually.
                  console.warn("signal: auto-persist after link failed:", err);
                });
            }
            message.success(t("channels.signalLinkSuccess"));
          } else if (s.status === "error") {
            stopSigPoll();
            setSigPairStatus("error");
            setSigPairLoading(false);
            message.error(s.error || t("channels.signalLinkFailed"));
          }
        } catch {
          /* transient — keep polling */
        }
      }, 3000);
    } catch (err) {
      const msg = (err as Error)?.message || t("channels.signalLinkFailed");
      message.error(msg);
      setSigPairStatus("error");
      // Error-path terminal state: clear loading immediately. The previous
      // unconditional `finally` fired right after the polling interval was
      // scheduled, which flipped the spinner off while the link flow was
      // still in progress. Loading now only clears on terminal states —
      // inline clears inside the poll loop (linked / error branches) handle
      // the happy path and the server-reported error.
      setSigPairLoading(false);
    }
  }, [sigDeviceName, stopSigPoll, form, message, t]);

  const handleSignalUnbind = useCallback(async () => {
    stopSigPoll();
    try {
      await api.unbindSignal();
      setSigLinked(false);
      setSigPhone("");
      setSigUuid("");
      setSigQrImage("");
      setSigPairStatus("idle");
      form.setFieldsValue({ account: "", account_uuid: "" });
      message.success(t("channels.signalUnlinkSuccess"));
    } catch (err) {
      const msg = (err as Error)?.message || t("channels.signalUnlinkFailed");
      message.error(msg);
    }
  }, [stopSigPoll, form, message, t]);

  // ── Access control fields (shared across multiple channels) ──────────────

  const renderAccessControlFields = () => (
    <>
      <Form.Item
        name="dm_policy"
        label={t("channels.dmPolicy")}
        tooltip={t("channels.dmPolicyTooltip")}
        initialValue="open"
      >
        <Select
          options={[
            { value: "open", label: t("channels.policyOpen") },
            { value: "allowlist", label: t("channels.policyAllowlist") },
          ]}
        />
      </Form.Item>
      <Form.Item
        name="group_policy"
        label={t("channels.groupPolicy")}
        tooltip={t("channels.groupPolicyTooltip")}
        initialValue="open"
      >
        <Select
          options={[
            { value: "open", label: t("channels.policyOpen") },
            { value: "allowlist", label: t("channels.policyAllowlist") },
          ]}
        />
      </Form.Item>
      <Form.Item
        name="require_mention"
        label={t("channels.requireMention")}
        valuePropName="checked"
        tooltip={t("channels.requireMentionTooltip")}
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="allow_from"
        label={t("channels.allowFrom")}
        tooltip={t("channels.allowFromTooltip")}
        initialValue={[]}
      >
        <Select
          mode="tags"
          placeholder={t("channels.allowFromPlaceholder")}
          tokenSeparators={[","]}
          // For Signal, populate with known contacts from
          // signal-cli's account.db — value is the phone (preferred,
          // since allowlist often matches on phone), with UUID shown in
          // the option label. Users can still type free-form to add
          // values not in the directory (e.g. uuid: prefix or unknown
          // phones).
          options={
            activeKey === "signal" && sigContacts.length
              ? sigContacts.map((c) => {
                  const value = c.number || (c.uuid ? `uuid:${c.uuid}` : "");
                  const label = [c.name, c.number, c.uuid && `uuid:${c.uuid.slice(0, 8)}…`]
                    .filter(Boolean)
                    .join(" · ");
                  return { value, label: label || value };
                })
              : undefined
          }
        />
      </Form.Item>
    </>
  );

  // ── Builtin channel-specific fields ─────────────────────────────────────

  const renderBuiltinExtraFields = (key: ChannelKey) => {
    switch (key) {
      case "matrix":
        return (
          <>
            <Form.Item
              name="homeserver"
              label="Homeserver URL"
              rules={[{ required: true }]}
            >
              <Input placeholder="https://matrix.org" />
            </Form.Item>
            <Form.Item
              name="user_id"
              label="User ID"
              rules={[{ required: true }]}
            >
              <Input placeholder="@bot:matrix.org" />
            </Form.Item>
            <Form.Item
              name="access_token"
              label="Access Token"
              rules={[{ required: true }]}
            >
              <Input.Password placeholder="syt_..." />
            </Form.Item>
          </>
        );

      case "imessage":
        return (
          <>
            <Form.Item
              name="db_path"
              label="DB Path"
              rules={[{ required: true, message: "Please input DB path" }]}
            >
              <Input placeholder="~/Library/Messages/chat.db" />
            </Form.Item>
            <Form.Item
              name="poll_sec"
              label="Poll Interval (sec)"
              rules={[
                { required: true, message: "Please input poll interval" },
              ]}
            >
              <InputNumber min={0.1} step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </>
        );

      case "discord":
        return (
          <>
            <Form.Item
              name="bot_token"
              label="Bot Token"
              rules={[{ required: true }]}
            >
              <Input.Password placeholder="Discord bot token" />
            </Form.Item>
            <Form.Item name="http_proxy" label="HTTP Proxy">
              <Input placeholder="http://127.0.0.1:18118" />
            </Form.Item>
            <Form.Item name="http_proxy_auth" label="HTTP Proxy Auth">
              <Input placeholder="user:password" />
            </Form.Item>
            <Form.Item
              name="accept_bot_messages"
              label={t("channels.acceptBotMessages")}
              valuePropName="checked"
              tooltip={t("channels.acceptBotMessagesTooltip")}
            >
              <Switch />
            </Form.Item>
          </>
        );

      case "dingtalk":
        return (
          <>
            <ConfigProvider prefixCls="ant">
              <Alert
                type="info"
                showIcon
                message={t("channels.dingtalkSetupGuide")}
                style={{ marginBottom: 16 }}
              />
            </ConfigProvider>
            <Form.Item label={t("channels.dingtalkScanAuth")}>
              <Button
                type="primary"
                block
                loading={dingtalkQrcode.loading}
                onClick={dingtalkQrcode.fetchQrcode}
              >
                {t("channels.dingtalkGetQrcode")}
              </Button>
              {dingtalkQrcode.loading && (
                <div style={{ textAlign: "center", marginTop: 12 }}>
                  <Spin />
                </div>
              )}
              {dingtalkQrcode.qrcodeImg && !dingtalkQrcode.loading && (
                <div style={{ textAlign: "center", marginTop: 12 }}>
                  <img
                    src={`data:image/png;base64,${dingtalkQrcode.qrcodeImg}`}
                    alt="DingTalk QR Code"
                    style={{ width: 200, height: 200 }}
                  />
                  <div
                    style={{
                      marginTop: 8,
                      fontSize: 12,
                      color: isDark
                        ? "rgba(255,255,255,0.45)"
                        : "rgba(0,0,0,0.45)",
                    }}
                  >
                    {t("channels.dingtalkScanHint")}
                  </div>
                </div>
              )}
            </Form.Item>
            <Form.Item
              name="client_id"
              label="Client ID"
              rules={[{ required: true }]}
            >
              <Input placeholder="dingxxxxx" />
            </Form.Item>
            <Form.Item
              name="client_secret"
              label="Client Secret"
              rules={[{ required: true }]}
            >
              <Input.Password />
            </Form.Item>
            <Form.Item
              name="message_type"
              label="Message Type"
              tooltip="markdown: regular messages; card: AI interactive card"
            >
              <Select
                options={[
                  { label: "markdown", value: "markdown" },
                  { label: "card", value: "card" },
                ]}
              />
            </Form.Item>
            <Form.Item
              noStyle
              shouldUpdate={(prev, cur) =>
                prev.message_type !== cur.message_type
              }
            >
              {({ getFieldValue }) => {
                if (getFieldValue("message_type") !== "card") return null;
                return (
                  <>
                    <Form.Item
                      name="card_template_id"
                      label="Card Template ID"
                      rules={[
                        {
                          required: true,
                          message:
                            "Please input card template id when message_type=card",
                        },
                      ]}
                    >
                      <Input placeholder="dt_card_template_xxx" />
                    </Form.Item>
                    <Form.Item
                      name="card_template_key"
                      label="Card Template Key"
                      tooltip="Must exactly match the template variable name"
                    >
                      <Input placeholder="content" />
                    </Form.Item>
                    <Form.Item
                      name="robot_code"
                      label="Robot Code"
                      tooltip="Recommended to configure explicitly for group chats"
                    >
                      <Input placeholder="robot code (default client_id)" />
                    </Form.Item>
                  </>
                );
              }}
            </Form.Item>
          </>
        );

      case "feishu":
        return (
          <>
            <Form.Item
              name="domain"
              label={t("channels.feishuRegion")}
              initialValue="feishu"
              tooltip={t("channels.feishuRegionTooltip")}
            >
              <Select>
                <Select.Option value="feishu">
                  {t("channels.feishuChina")}
                </Select.Option>
                <Select.Option value="lark">
                  {t("channels.feishuInternational")}
                </Select.Option>
              </Select>
            </Form.Item>
            <Form.Item
              name="app_id"
              label="App ID"
              rules={[{ required: true }]}
            >
              <Input placeholder="cli_xxx" />
            </Form.Item>
            <Form.Item
              name="app_secret"
              label="App Secret"
              rules={[{ required: true }]}
            >
              <Input.Password placeholder="App Secret" />
            </Form.Item>
            <Form.Item name="encrypt_key" label="Encrypt Key">
              <Input placeholder="Optional, for event encryption" />
            </Form.Item>
            <Form.Item name="verification_token" label="Verification Token">
              <Input placeholder="Optional" />
            </Form.Item>
            <Form.Item name="media_dir" label={t("channels.weixinMediaDir")}>
              <Input placeholder="~/.qwenpaw/media" />
            </Form.Item>
          </>
        );

      case "qq":
        return (
          <>
            <Form.Item
              name="app_id"
              label="App ID"
              rules={[{ required: true }]}
            >
              <Input />
            </Form.Item>
            <Form.Item
              name="client_secret"
              label="Client Secret"
              rules={[{ required: true }]}
            >
              <Input.Password />
            </Form.Item>
          </>
        );

      case "telegram":
        return (
          <>
            <Form.Item
              name="bot_token"
              label="Bot Token"
              rules={[{ required: true }]}
            >
              <Input.Password placeholder="Telegram bot token from BotFather" />
            </Form.Item>
            <Form.Item name="http_proxy" label="HTTP Proxy">
              <Input placeholder="http://127.0.0.1:18118" />
            </Form.Item>
            <Form.Item name="http_proxy_auth" label="HTTP Proxy Auth">
              <Input placeholder="user:password" />
            </Form.Item>
            <Form.Item
              name="show_typing"
              label="Show Typing"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
          </>
        );

      case "mqtt":
        return (
          <>
            <Form.Item
              name="host"
              label="MQTT Host"
              rules={[{ required: true }]}
            >
              <Input placeholder="127.0.0.1" />
            </Form.Item>
            <Form.Item
              name="port"
              label="MQTT Port"
              rules={[
                { required: true },
                {
                  type: "number",
                  min: 1,
                  max: 65535,
                  message: "Port must be between 1 and 65535",
                },
              ]}
            >
              <InputNumber
                min={1}
                max={65535}
                style={{ width: "100%" }}
                placeholder="1883"
              />
            </Form.Item>
            <Form.Item
              name="transport"
              label="Transport"
              initialValue="tcp"
              rules={[{ required: true }]}
            >
              <Select>
                <Select.Option value="tcp">MQTT (tcp)</Select.Option>
                <Select.Option value="websockets">
                  WS (websockets)
                </Select.Option>
              </Select>
            </Form.Item>
            <Form.Item
              name="clean_session"
              label="Clean Session"
              valuePropName="checked"
            >
              <Switch defaultChecked />
            </Form.Item>
            <Form.Item
              name="qos"
              label="QoS"
              initialValue="2"
              rules={[{ required: true }]}
            >
              <Select>
                <Select.Option value="0">At Most Once (0)</Select.Option>
                <Select.Option value="1">At Least Once (1)</Select.Option>
                <Select.Option value="2">Exactly Once (2)</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item name="username" label="MQTT Username">
              <Input placeholder="Leave blank to disable / not use" />
            </Form.Item>
            <Form.Item name="password" label="MQTT Password">
              <Input.Password placeholder="Leave blank to disable / not use" />
            </Form.Item>
            <Form.Item
              name="subscribe_topic"
              label="Subscribe Topic"
              rules={[{ required: true }]}
            >
              <Input placeholder="server/+/up" />
            </Form.Item>
            <Form.Item
              name="publish_topic"
              label="Publish Topic"
              rules={[{ required: true }]}
            >
              <Input placeholder="client/{client_id}/down" />
            </Form.Item>
            <Form.Item
              name="tls_enabled"
              label="TLS Enabled"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Form.Item name="tls_ca_certs" label="TLS CA Certs">
              <Input placeholder="Path to CA certificates file" />
            </Form.Item>
            <Form.Item name="tls_certfile" label="TLS Certfile">
              <Input placeholder="Path to client certificate file" />
            </Form.Item>
            <Form.Item name="tls_keyfile" label="TLS Keyfile">
              <Input placeholder="Path to client private key file" />
            </Form.Item>
          </>
        );

      case "mattermost":
        return (
          <>
            <Form.Item
              name="url"
              label="Mattermost URL"
              rules={[{ required: true }]}
            >
              <Input placeholder="https://mattermost.example.com" />
            </Form.Item>
            <Form.Item
              name="bot_token"
              label="Bot Token"
              rules={[{ required: true }]}
            >
              <Input.Password placeholder="Mattermost bot token" />
            </Form.Item>
            <Form.Item name="media_dir" label={t("channels.weixinMediaDir")}>
              <Input placeholder="~/.qwenpaw/media/mattermost" />
            </Form.Item>
            <Form.Item
              name="show_typing"
              label="Show Typing"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Form.Item
              name="thread_follow_without_mention"
              label="Thread Follow Without Mention"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
          </>
        );

      case "voice":
        return (
          <>
            <ConfigProvider prefixCls="ant">
              <Alert
                type="info"
                showIcon
                message={t("channels.voiceSetupGuide")}
                style={{ marginBottom: 16 }}
              />
            </ConfigProvider>
            <Form.Item
              name="twilio_account_sid"
              label={t("channels.twilioAccountSid")}
              rules={[{ required: true }]}
            >
              <Input placeholder="ACxxxxxxxx" />
            </Form.Item>
            <Form.Item
              name="twilio_auth_token"
              label={t("channels.twilioAuthToken")}
              rules={[{ required: true }]}
            >
              <Input.Password />
            </Form.Item>
            <Form.Item name="phone_number" label={t("channels.phoneNumber")}>
              <Input placeholder="+15551234567" />
            </Form.Item>
            <Form.Item
              name="phone_number_sid"
              label={t("channels.phoneNumberSid")}
              tooltip={t("channels.phoneNumberSidHelp")}
            >
              <Input placeholder="PNxxxxxxxx" />
            </Form.Item>
            <Form.Item name="tts_provider" label={t("channels.ttsProvider")}>
              <Input placeholder="google" />
            </Form.Item>
            <Form.Item name="tts_voice" label={t("channels.ttsVoice")}>
              <Input placeholder="en-US-Journey-D" />
            </Form.Item>
            <Form.Item name="stt_provider" label={t("channels.sttProvider")}>
              <Input placeholder="deepgram" />
            </Form.Item>
            <Form.Item name="language" label={t("channels.language")}>
              <Input placeholder="en-US" />
            </Form.Item>
            <Form.Item
              name="welcome_greeting"
              label={t("channels.welcomeGreeting")}
            >
              <Input.TextArea rows={2} />
            </Form.Item>
          </>
        );

      case "wecom":
        return (
          <>
            <ConfigProvider prefixCls="ant">
              <Alert
                type="warning"
                showIcon
                message={t("channels.wecomSetupGuide")}
                style={{ marginBottom: 16 }}
              />
            </ConfigProvider>
            <Form.Item label={t("channels.wecomScanAuth")}>
              <Button
                type="primary"
                block
                loading={wecomQrcode.loading}
                onClick={wecomQrcode.fetchQrcode}
              >
                {t("channels.loginWeCom")}
              </Button>
              {wecomQrcode.loading && (
                <div style={{ textAlign: "center", marginTop: 12 }}>
                  <Spin />
                </div>
              )}
              {wecomQrcode.qrcodeImg && !wecomQrcode.loading && (
                <div style={{ textAlign: "center", marginTop: 12 }}>
                  <img
                    src={`data:image/png;base64,${wecomQrcode.qrcodeImg}`}
                    alt="WeCom QR Code"
                    style={{ width: 200, height: 200 }}
                  />
                  <div
                    style={{
                      marginTop: 8,
                      fontSize: 12,
                      color: isDark
                        ? "rgba(255,255,255,0.45)"
                        : "rgba(0,0,0,0.45)",
                    }}
                  >
                    {t("channels.wecomAuthHint")}
                  </div>
                </div>
              )}
            </Form.Item>
            <Form.Item
              name="bot_id"
              label="Bot ID"
              rules={[{ required: true, message: "Please input Bot ID" }]}
            >
              <Input placeholder="Bot ID from WeCom backend" />
            </Form.Item>
            <Form.Item
              name="secret"
              label="Secret"
              rules={[{ required: true, message: "Please input Secret" }]}
            >
              <Input.Password placeholder="Secret from WeCom backend" />
            </Form.Item>
            <Form.Item name="media_dir" label={t("channels.weixinMediaDir")}>
              <Input placeholder="~/.qwenpaw/media" />
            </Form.Item>
            <Form.Item
              name="welcome_text"
              label={t("channels.welcomeText")}
              tooltip={t("channels.welcomeTextTooltip")}
            >
              <Input placeholder={t("channels.welcomeTextPlaceholder")} />
            </Form.Item>
          </>
        );

      case "xiaoyi":
        return (
          <>
            <ConfigProvider prefixCls="ant">
              <Alert
                type="info"
                showIcon
                message={t("channels.xiaoyiSetupGuide")}
                style={{ marginBottom: 16 }}
              />
            </ConfigProvider>
            <Form.Item
              name="ak"
              label="Access Key (AK)"
              rules={[{ required: true, message: "Please input Access Key" }]}
            >
              <Input placeholder="Access Key from Huawei Developer Platform" />
            </Form.Item>
            <Form.Item
              name="sk"
              label="Secret Key (SK)"
              rules={[{ required: true, message: "Please input Secret Key" }]}
            >
              <Input.Password placeholder="Secret Key from Huawei Developer Platform" />
            </Form.Item>
            <Form.Item
              name="agent_id"
              label="Agent ID"
              rules={[{ required: true, message: "Please input Agent ID" }]}
            >
              <Input placeholder="Agent ID from XiaoYi platform" />
            </Form.Item>
            <Form.Item name="ws_url" label="WebSocket URL">
              <Input placeholder="wss://hag.cloud.huawei.com/openclaw/v1/ws/link" />
            </Form.Item>
          </>
        );

      case "weixin":
        return (
          <>
            <ConfigProvider prefixCls="ant">
              <Alert
                type="info"
                showIcon
                message={t("channels.weixinSetupGuide")}
                style={{ marginBottom: 16 }}
              />
              <Alert
                type="warning"
                showIcon
                message={t("channels.weixinContextTokenLimit")}
                style={{ marginBottom: 16 }}
              />
            </ConfigProvider>
            <Form.Item label={t("channels.weixinScanLogin")}>
              <Button
                type="primary"
                block
                loading={weixinQrcode.loading}
                onClick={weixinQrcode.fetchQrcode}
              >
                {t("channels.weixinGetQrcode")}
              </Button>
              {weixinQrcode.loading && (
                <div style={{ textAlign: "center", marginTop: 12 }}>
                  <Spin />
                </div>
              )}
              {weixinQrcode.qrcodeImg && !weixinQrcode.loading && (
                <div style={{ textAlign: "center", marginTop: 12 }}>
                  <img
                    src={`data:image/png;base64,${weixinQrcode.qrcodeImg}`}
                    alt="WeChat QR Code"
                    style={{ width: 200, height: 200 }}
                  />
                  <div
                    style={{
                      marginTop: 8,
                      fontSize: 12,
                      color: isDark
                        ? "rgba(255,255,255,0.45)"
                        : "rgba(0,0,0,0.45)",
                    }}
                  >
                    {t("channels.weixinScanHint")}
                  </div>
                </div>
              )}
            </Form.Item>
            <Form.Item
              name="bot_token"
              label={t("channels.weixinBotToken")}
              tooltip={t("channels.weixinBotTokenTooltip")}
            >
              <Input.Password
                placeholder={t("channels.weixinBotTokenPlaceholder")}
              />
            </Form.Item>
            <Form.Item
              name="bot_token_file"
              label={t("channels.weixinBotTokenFile")}
              tooltip={t("channels.weixinBotTokenFileTooltip")}
            >
              <Input placeholder="~/.qwenpaw/weixin_bot_token" />
            </Form.Item>
            <Form.Item name="media_dir" label={t("channels.weixinMediaDir")}>
              <Input placeholder="~/.qwenpaw/media" />
            </Form.Item>
          </>
        );

      case "onebot":
        return (
          <>
            <Form.Item
              name="ws_host"
              label="WebSocket Host"
              rules={[{ required: true }]}
            >
              <Input placeholder="0.0.0.0" />
            </Form.Item>
            <Form.Item
              name="ws_port"
              label="WebSocket Port"
              rules={[
                { required: true },
                {
                  type: "number",
                  min: 1,
                  max: 65535,
                  message: "Port must be between 1 and 65535",
                },
              ]}
            >
              <InputNumber
                min={1}
                max={65535}
                style={{ width: "100%" }}
                placeholder="6199"
              />
            </Form.Item>
            <Form.Item name="access_token" label="Access Token">
              <Input.Password placeholder="Access token for authentication" />
            </Form.Item>
            <Form.Item
              name="share_session_in_group"
              label={t("channels.onebotShareSessionInGroup")}
              valuePropName="checked"
              tooltip={t("channels.onebotShareSessionInGroupTooltip")}
            >
              <Switch />
            </Form.Item>
          </>
        );

      case "signal":
        return (
          <>
            <Form.Item label={t("channels.signalConnection")}>
              {sigLinked || sigPairStatus === "linked" ? (
                <>
                  <Alert
                    type="success"
                    showIcon
                    message={t("channels.signalLinked")}
                    description={
                      sigPhone
                        ? `${t("channels.signalLinkedAs")}: ${sigPhone}`
                        : t("channels.signalSessionActive")
                    }
                    style={{ marginBottom: 12 }}
                  />
                  <Button
                    danger
                    block
                    loading={sigPairLoading}
                    onClick={handleSignalUnbind}
                  >
                    {t("channels.signalUnlinkDevice")}
                  </Button>
                </>
              ) : (
                <>
                  <Input
                    placeholder={t("channels.signalDeviceNamePlaceholder")}
                    value={sigDeviceName}
                    onChange={(e) => setSigDeviceName(e.target.value)}
                    style={{ marginBottom: 8 }}
                  />
                  <Button
                    type="primary"
                    block
                    loading={sigPairLoading}
                    onClick={handleSignalLink}
                  >
                    {t("channels.signalLinkDevice")}
                  </Button>
                  {sigQrImage && (
                    <div style={{ textAlign: "center", marginTop: 12 }}>
                      <img
                        src={`data:image/png;base64,${sigQrImage}`}
                        alt="Signal link QR"
                        style={{ width: 220, height: 220 }}
                      />
                      <div
                        style={{
                          marginTop: 8,
                          fontSize: 12,
                          opacity: 0.7,
                        }}
                      >
                        {t("channels.signalScanInstructions")}
                      </div>
                    </div>
                  )}
                  {sigPairStatus === "error" && (
                    <div style={{ marginTop: 8 }}>
                      <Alert
                        type="error"
                        showIcon
                        message={t("channels.signalLinkFailed")}
                      />
                    </div>
                  )}
                </>
              )}
            </Form.Item>
            {/*
              account + account_uuid are read-only: they're the identity
              signal-cli itself authoritative-told us (populated from the
              linked account store on drawer open, or from the link-device
              flow's success handler). Letting users type a different
              phone here would silently detach the channel config from
              the actual session data_dir — the channel would either fail
              to start ("User +XXX is not registered") or connect to a
              different account than the UI shows. Better to force users
              through the Link Device flow to change these.
            */}
            <Form.Item
              name="account"
              label={t("channels.signalAccount")}
              tooltip={t("channels.signalAccountTooltip")}
              rules={[{ required: true }]}
            >
              <Input placeholder="+85212345678" readOnly />
            </Form.Item>
            <Form.Item
              name="account_uuid"
              label={t("channels.signalAccountUuid")}
              tooltip={t("channels.signalAccountUuidTooltip")}
            >
              <Input
                placeholder="447e962a-0000-0000-0000-000000000000"
                readOnly
              />
            </Form.Item>
            <Form.Item
              name="signal_cli_path"
              label={t("channels.signalCliPath")}
              tooltip={t("channels.signalCliPathTooltip")}
            >
              <Input placeholder={t("channels.signalCliPathPlaceholder")} />
            </Form.Item>
            <Form.Item
              name="data_dir"
              label={t("channels.signalDataDir")}
              tooltip={t("channels.signalDataDirTooltip")}
            >
              <Input placeholder={t("channels.signalDataDirPlaceholder")} />
            </Form.Item>
            <Form.Item
              name="extra_args"
              label={t("channels.signalExtraArgs")}
              tooltip={t("channels.signalExtraArgsTooltip")}
              initialValue={[]}
            >
              <Select
                mode="tags"
                placeholder={t("channels.signalExtraArgsPlaceholder")}
                tokenSeparators={[","]}
              />
            </Form.Item>
            <Form.Item
              name="show_typing"
              label={t("channels.signalShowTyping")}
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Form.Item
              name="send_read_receipts"
              label={t("channels.signalSendReadReceipts")}
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Form.Item
              name="text_chunk_limit"
              label={t("channels.signalTextChunkLimit")}
              tooltip={t("channels.signalTextChunkLimitTooltip")}
            >
              <InputNumber
                min={100}
                max={10000}
                style={{ width: "100%" }}
                placeholder="4000"
              />
            </Form.Item>
            <Form.Item
              name="groups"
              label={t("channels.signalGroups")}
              tooltip={t("channels.signalGroupsTooltip")}
              initialValue={[]}
            >
              <Select
                mode="tags"
                placeholder={t("channels.signalGroupsPlaceholder")}
                tokenSeparators={[","]}
                // Populated from signal-cli's group_v2 table. Group names
                // are in a protobuf BLOB we don't decode yet, so the
                // label is just a truncated base64 id — still lets users
                // pick without typing 40-char strings. Free-form tag
                // input still works for custom entries.
                options={
                  sigGroups.length
                    ? sigGroups.map((g) => ({
                        value: g.id,
                        label: `${g.id.slice(0, 20)}…${g.blocked ? " (blocked)" : ""}`,
                      }))
                    : undefined
                }
              />
            </Form.Item>
            <Form.Item
              name="group_allow_from"
              label={t("channels.signalGroupAllowFrom")}
              tooltip={t("channels.signalGroupAllowFromTooltip")}
              initialValue={[]}
            >
              <Select
                mode="tags"
                placeholder={t("channels.signalGroupAllowFromPlaceholder")}
                tokenSeparators={[","]}
                options={
                  sigContacts.length
                    ? [
                        { value: "*", label: "* (everyone)" },
                        ...sigContacts.map((c) => {
                          const value = c.number || (c.uuid ? `uuid:${c.uuid}` : "");
                          const label = [c.name, c.number, c.uuid && `uuid:${c.uuid.slice(0, 8)}…`]
                            .filter(Boolean)
                            .join(" · ");
                          return { value, label: label || value };
                        }),
                      ]
                    : undefined
                }
              />
            </Form.Item>
            <Form.Item
              name="reply_to_trigger"
              label={t("channels.signalReplyToTrigger")}
              tooltip={t("channels.signalReplyToTriggerTooltip")}
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
          </>
        );

      default:
        return null;
    }
  };

  // ── Custom channel fields (key-value editor) ─────────────────────────────

  const renderCustomExtraFields = (
    values: Record<string, unknown> | undefined,
  ) => {
    if (!values) return null;
    const extraKeys = Object.keys(values).filter(
      (k) => !BASE_FIELDS.includes(k),
    );
    if (extraKeys.length === 0) return null;

    return (
      <>
        <div style={{ marginBottom: 8, fontWeight: 500 }}>Custom Fields</div>
        {extraKeys.map((fieldKey) => {
          const value = values[fieldKey];
          return (
            <Form.Item key={fieldKey} name={fieldKey} label={fieldKey}>
              {typeof value === "boolean" ? (
                <Switch />
              ) : typeof value === "number" ? (
                <InputNumber style={{ width: "100%" }} />
              ) : (
                <Input />
              )}
            </Form.Item>
          );
        })}
      </>
    );
  };

  // ── Drawer title ─────────────────────────────────────────────────────────

  const drawerTitle = (
    <div className={styles.drawerTitle}>
      <span>
        {label
          ? `${label} ${t("channels.settings")}`
          : t("channels.channelSettings")}
      </span>
      {activeKey &&
        CHANNEL_DOC_EN_URLS[activeKey] &&
        CHANNEL_DOC_ZH_URLS[activeKey] && (
          <Button
            type="text"
            size="small"
            icon={<LinkOutlined />}
            onClick={() => {
              const url =
                CHANNEL_DOC_EN_URLS[activeKey]! ||
                CHANNEL_DOC_ZH_URLS[activeKey]!;
              const isQwenPawDoc = url.includes(
                "qwenpaw.agentscope.io/docs/channels/",
              );
              const finalUrl =
                isQwenPawDoc && currentLang === "zh"
                  ? CHANNEL_DOC_ZH_URLS[activeKey]!
                  : CHANNEL_DOC_EN_URLS[activeKey]!;
              window.open(finalUrl, "_blank");
            }}
            className={styles.dingtalkDocBtn}
            style={{ color: "#FF7F16" }}
          >
            {label} Doc
          </Button>
        )}
      {activeKey === "voice" && (
        <Button
          type="text"
          size="small"
          icon={<LinkOutlined />}
          onClick={() =>
            window.open(TWILIO_CONSOLE_URL, "_blank", "noopener,noreferrer")
          }
          className={styles.dingtalkDocBtn}
          style={{ color: "#FF7F16" }}
        >
          {t("channels.voiceSetupLink")}
        </Button>
      )}
    </div>
  );

  // ── Render ───────────────────────────────────────────────────────────────

  const drawerFooter = (
    <div className={styles.formActions}>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button type="primary" loading={saving} onClick={() => form.submit()}>
        {t("common.save")}
      </Button>
    </div>
  );

  return (
    <Drawer
      width={420}
      placement="right"
      title={drawerTitle}
      open={open}
      onClose={onClose}
      destroyOnClose
      footer={drawerFooter}
    >
      {activeKey && (
        <Form
          form={form}
          layout="vertical"
          initialValues={initialValues}
          onFinish={onSubmit}
        >
          <Form.Item
            name="enabled"
            label={t("common.enabled")}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>

          {activeKey !== "voice" && (
            <Form.Item name="bot_prefix" label="Bot Prefix">
              <Input placeholder="@bot" />
            </Form.Item>
          )}

          {activeKey !== "console" && (
            <>
              <Form.Item
                name="filter_tool_messages"
                label={t("channels.filterToolMessages")}
                valuePropName="checked"
                tooltip={t("channels.filterToolMessagesTooltip")}
              >
                <Switch />
              </Form.Item>
              <Form.Item
                name="filter_thinking"
                label={t("channels.filterThinking")}
                valuePropName="checked"
                tooltip={t("channels.filterThinkingTooltip")}
              >
                <Switch />
              </Form.Item>
            </>
          )}

          {isBuiltin
            ? renderBuiltinExtraFields(activeKey)
            : renderCustomExtraFields(initialValues)}

          {CHANNELS_WITH_ACCESS_CONTROL.includes(activeKey) &&
            renderAccessControlFields()}
        </Form>
      )}
    </Drawer>
  );
}
