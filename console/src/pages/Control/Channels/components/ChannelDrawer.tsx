import { useEffect, useState } from "react";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import { getChannelLabel, type ChannelKey } from "./constants";
import { QrcodeAuthBlock } from "./QrcodeAuthBlock";
import { useAgentStore } from "../../../../stores/agentStore";
import { openExternalLink } from "../../../../utils/openExternalLink";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Loader2,
  ExternalLink,
  AlertCircle,
  AlertTriangle,
} from "lucide-react";

const CHANNELS_WITH_ACCESS_CONTROL: ChannelKey[] = [
  "telegram",
  "dingtalk",
  "discord",
  "feishu",
  "wecom",
  "mattermost",
  "matrix",
  "wechat",
  "imessage",
  "onebot",
  "qq",
  "mqtt",
  "xiaoyi",
  "yuanbao",
];

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
  sip: "https://qwenpaw.agentscope.io/docs/channels/?lang=en#SIP",
  wecom:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=en#WeCom-WeChat-Work",
  wechat:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=en#WeChat-Personal-iLink",
  xiaoyi:
    "https://developer.huawei.com/consumer/cn/doc/service/openclaw-0000002518410344",
  yuanbao: "https://qwenpaw.agentscope.io/docs/channels/?lang=en#Yuanbao",
  onebot:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=en#OneBot-v11-NapCat--QQ-full-protocol",
};

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
  sip: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#SIP",
  wecom: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#企业微信",
  wechat: "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#微信个人iLink",
  xiaoyi:
    "https://developer.huawei.com/consumer/cn/doc/service/openclaw-0000002518410344",
  yuanbao:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#腾讯元宝Yuanbao",
  onebot:
    "https://qwenpaw.agentscope.io/docs/channels/?lang=zh#OneBot-v11NapCat--QQ-完整协议",
};

const TWILIO_CONSOLE_URL = "https://console.twilio.com";

const BASE_FIELDS = [
  "enabled",
  "bot_prefix",
  "filter_tool_messages",
  "filter_thinking",
  "isBuiltin",
];

// Channel form proxy interface (same as JobDrawer pattern)
export interface ChannelFormProxy {
  getFieldValue: (name: string) => any;
  setFieldsValue: (values: Record<string, any>) => void;
  resetFields: () => void;
  submit: () => void;
}

interface ChannelDrawerProps {
  open: boolean;
  activeKey: ChannelKey | null;
  activeLabel: string;
  form: ChannelFormProxy;
  saving: boolean;
  initialValues: Record<string, unknown> | undefined;
  isBuiltin: boolean;
  onClose: () => void;
  onSubmit: (values: Record<string, unknown>) => void;
}

// Labelled form row
function Field({
  label,
  required,
  tooltip,
  hidden,
  children,
}: {
  label: string;
  required?: boolean;
  tooltip?: string;
  hidden?: boolean;
  children: React.ReactNode;
}) {
  if (hidden) return null;
  return (
    <div className="flex flex-col gap-1.5 mb-4">
      <Label title={tooltip}>
        {required && <span className="text-destructive mr-1">*</span>}
        {label}
        {tooltip && (
          <span className="text-muted-foreground text-xs ml-1" title={tooltip}>
            (?)
          </span>
        )}
      </Label>
      {children}
    </div>
  );
}

function InfoAlert({
  message,
  variant = "info",
}: {
  message: string;
  variant?: "info" | "warning";
}) {
  return (
    <div
      className={`flex items-start gap-2 rounded-md p-3 mb-4 text-sm ${
        variant === "warning"
          ? "bg-yellow-500/10 text-yellow-700 dark-mode:text-yellow-400 border border-yellow-500/20"
          : "bg-blue-500/10 text-blue-700 dark-mode:text-blue-400 border border-blue-500/20"
      }`}
    >
      {variant === "warning" ? (
        <AlertTriangle size={16} className="shrink-0 mt-0.5" />
      ) : (
        <AlertCircle size={16} className="shrink-0 mt-0.5" />
      )}
      <span>{message}</span>
    </div>
  );
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
  const { selectedAgent, agents } = useAgentStore();
  const currentAgent = agents.find((a) => a.id === selectedAgent);
  const defaultMediaDir = currentAgent?.workspace_dir
    ? `${currentAgent.workspace_dir}/media`
    : "~/.qwenpaw/media";
  const currentLang = i18n.language?.startsWith("zh") ? "zh" : "en";
  const label = activeKey ? getChannelLabel(activeKey, t) : activeLabel;
  const { message } = useAppMessage();

  // Controlled form state
  const [values, setValues] = useState<Record<string, any>>({});

  const get = (key: string) => values[key];
  const set = (key: string, value: any) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  // Wire up form proxy
  useEffect(() => {
    form.getFieldValue = get;
    form.setFieldsValue = (v) => setValues((prev) => ({ ...prev, ...v }));
    form.resetFields = () => setValues({});
    form.submit = handleSubmit;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values]);

  // Re-apply auth_method for matrix after open
  useEffect(() => {
    if (!open || activeKey !== "matrix") return;
    const pw = initialValues?.password;
    if (typeof pw === "string" && pw.trim().length > 0) {
      set("auth_method", "password");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, activeKey]);

  const isMatrixPasswordAuth = get("auth_method") === "password";
  const feishuDomain = (get("domain") as string) || "feishu";

  const handleSubmit = () => {
    if (!activeKey) return;
    if (activeKey !== "matrix") {
      onSubmit(values);
      return;
    }
    const { auth_method, ...rest } = values;
    if (auth_method === "password") {
      onSubmit({ ...rest, access_token: "" });
    } else {
      onSubmit({ ...rest, password: "", encryption: false });
    }
  };

  // Input helpers
  const textInput = (
    name: string,
    placeholder?: string,
    type: string = "text",
  ) => (
    <Input
      type={type}
      placeholder={placeholder}
      value={get(name) ?? ""}
      onChange={(e) => set(name, e.target.value)}
    />
  );

  const numInput = (
    name: string,
    placeholder?: string,
    min?: number,
    max?: number,
    step?: number,
  ) => (
    <Input
      type="number"
      placeholder={placeholder}
      value={get(name) ?? ""}
      min={min}
      max={max}
      step={step}
      onChange={(e) =>
        set(name, e.target.value === "" ? "" : Number(e.target.value))
      }
    />
  );

  const switchInput = (name: string) => (
    <Switch
      checked={Boolean(get(name))}
      onCheckedChange={(checked) => set(name, checked)}
    />
  );

  const selectInput = (
    name: string,
    options: { value: string; label: string }[],
    defaultValue?: string,
  ) => (
    <Select
      value={(get(name) as string) ?? defaultValue ?? ""}
      onValueChange={(v) => set(name, v)}
    >
      <SelectTrigger>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  // ── Access control fields ─────────────────────────────────────────────────

  const renderAccessControlFields = () => (
    <>
      <Field
        label={t("channels.accessControlDm")}
        tooltip={t("channels.accessControlDmTooltip")}
      >
        {switchInput("access_control_dm")}
      </Field>
      <Field
        label={t("channels.accessControlGroup")}
        tooltip={t("channels.accessControlGroupTooltip")}
      >
        {switchInput("access_control_group")}
      </Field>
      <Field
        label={t("channels.requireMention")}
        tooltip={t("channels.requireMentionTooltip")}
      >
        {switchInput("require_mention")}
      </Field>
    </>
  );

  // ── Channel-specific fields ───────────────────────────────────────────────

  const renderBuiltinExtraFields = (key: ChannelKey) => {
    switch (key) {
      case "matrix":
        return (
          <>
            <Field label="Homeserver URL" required>
              {textInput("homeserver", "https://matrix.org")}
            </Field>
            <Field
              label="User ID"
              required
              tooltip="Accepts a full MXID (e.g. @bot:matrix.org) or just the localpart."
            >
              {textInput("user_id", "@bot:matrix.org")}
            </Field>
            <Field label="Auth Method">
              {selectInput(
                "auth_method",
                [
                  { value: "token", label: "Token" },
                  { value: "password", label: "Password" },
                ],
                "token",
              )}
            </Field>
            <Field
              label="Access Token"
              required={!isMatrixPasswordAuth}
              hidden={isMatrixPasswordAuth}
            >
              {textInput("access_token", "syt_...", "password")}
            </Field>
            <Field
              label="Password"
              required={isMatrixPasswordAuth}
              hidden={!isMatrixPasswordAuth}
            >
              {textInput("password", "Account password for login", "password")}
            </Field>
            <Field
              label="Enable End-to-End Encryption"
              tooltip="After enabling, you must verify the device in a Matrix client. E2EE requires matrix-nio[e2e]."
              hidden={!isMatrixPasswordAuth}
            >
              {switchInput("encryption")}
            </Field>
            <Field
              label="Device Name"
              tooltip="A stable device identity. Defaults to 'qwenpaw-worker'."
            >
              {textInput("device_name", "qwenpaw-worker")}
            </Field>
            <Field
              label={t("channels.dmDisabled")}
              tooltip={t("channels.dmDisabledTooltip")}
            >
              {switchInput("dm_disabled")}
            </Field>
            <Field
              label={t("channels.groupDisabled")}
              tooltip={t("channels.groupDisabledTooltip")}
            >
              {switchInput("group_disabled")}
            </Field>
          </>
        );

      case "imessage":
        return (
          <>
            <Field label="DB Path" required>
              {textInput("db_path", "~/Library/Messages/chat.db")}
            </Field>
            <Field label="Poll Interval (sec)" required>
              {numInput("poll_sec", "1", 0.1, undefined, 0.1)}
            </Field>
          </>
        );

      case "discord":
        return (
          <>
            <Field label="Bot Token" required>
              {textInput("bot_token", "Discord bot token", "password")}
            </Field>
            <Field label="HTTP Proxy">
              {textInput("http_proxy", "http://127.0.0.1:18118")}
            </Field>
            <Field label="HTTP Proxy Auth">
              {textInput("http_proxy_auth", "user:password")}
            </Field>
            <Field
              label={t("channels.acceptBotMessages")}
              tooltip={t("channels.acceptBotMessagesTooltip")}
            >
              {switchInput("accept_bot_messages")}
            </Field>
          </>
        );

      case "dingtalk":
        return (
          <>
            <InfoAlert message={t("channels.dingtalkSetupGuide")} />
            <QrcodeAuthBlock
              label={t("channels.dingtalkScanAuth")}
              buttonText={t("channels.dingtalkGetQrcode")}
              imageAlt="DingTalk QR Code"
              hintText={t("channels.dingtalkScanHint")}
              channel="dingtalk"
              successStatus="success"
              successCredentialKey="client_id"
              pollInterval={5000}
              onSuccess={(credentials) => {
                form.setFieldsValue({
                  client_id: credentials.client_id,
                  client_secret: credentials.client_secret,
                });
                message.success(t("channels.dingtalkAuthSuccess"));
              }}
              onError={(type) => {
                if (type === "expired")
                  message.warning(t("channels.dingtalkQrcodeExpired"));
                else message.error(t("channels.dingtalkQrcodeFailed"));
              }}
            />
            <Field label="Client ID" required>
              {textInput("client_id", "dingxxxxx")}
            </Field>
            <Field label="Client Secret" required>
              {textInput("client_secret", "", "password")}
            </Field>
            <Field
              label="Message Type"
              tooltip="markdown: regular messages; card: AI interactive card"
            >
              {selectInput("message_type", [
                { value: "markdown", label: "markdown" },
                { value: "card", label: "card" },
              ])}
            </Field>
            <Field
              label="Cron Message Type"
              tooltip="Message type for cron/scheduled task sends."
            >
              {selectInput("cron_message_type", [
                { value: "markdown", label: "markdown" },
                { value: "card", label: "card" },
              ])}
            </Field>
            {(get("message_type") === "card" ||
              get("cron_message_type") === "card") && (
              <>
                <Field label="Card Template ID" required>
                  {textInput("card_template_id", "dt_card_template_xxx")}
                </Field>
                <Field
                  label="Card Template Key"
                  tooltip="Must exactly match the template variable name"
                >
                  {textInput("card_template_key", "content")}
                </Field>
                <Field
                  label="Robot Code"
                  tooltip="Recommended to configure explicitly for group chats"
                >
                  {textInput("robot_code", "robot code (default client_id)")}
                </Field>
              </>
            )}
            <Field
              label={t("channels.atSenderOnReply")}
              tooltip={t("channels.atSenderOnReplyTooltip")}
            >
              {switchInput("at_sender_on_reply")}
            </Field>
          </>
        );

      case "feishu":
        return (
          <>
            <Field
              label={t("channels.feishuRegion")}
              tooltip={t("channels.feishuRegionTooltip")}
            >
              {selectInput(
                "domain",
                [
                  { value: "feishu", label: t("channels.feishuChina") },
                  { value: "lark", label: t("channels.feishuInternational") },
                ],
                "feishu",
              )}
            </Field>
            <InfoAlert message={t("channels.feishuScanGuide")} />
            <QrcodeAuthBlock
              label={t("channels.feishuScanLogin")}
              buttonText={t("channels.feishuGetQrcode")}
              imageAlt="Feishu QR Code"
              hintText={t("channels.feishuScanHint")}
              channel="feishu"
              successStatus="success"
              successCredentialKey="app_id"
              pollInterval={2000}
              params={{ domain: feishuDomain }}
              onSuccess={(credentials) => {
                form.setFieldsValue({
                  app_id: credentials.app_id,
                  app_secret: credentials.app_secret,
                });
                message.success(t("channels.feishuAuthSuccess"));
              }}
              onError={(type) => {
                if (type === "expired")
                  message.warning(t("channels.feishuQrcodeExpired"));
                else message.error(t("channels.feishuQrcodeFailed"));
              }}
            />
            <Field label="App ID" required>
              {textInput("app_id", "cli_xxx")}
            </Field>
            <Field label="App Secret" required>
              {textInput("app_secret", "App Secret", "password")}
            </Field>
            <Field label="Encrypt Key">
              {textInput("encrypt_key", "Optional, for event encryption")}
            </Field>
            <Field label="Verification Token">
              {textInput("verification_token", "Optional")}
            </Field>
            <Field label={t("channels.wechatMediaDir")}>
              {textInput("media_dir", defaultMediaDir)}
            </Field>
            <Field
              label={t("channels.shareSessionInGroup")}
              tooltip={t("channels.shareSessionInGroupTooltip")}
            >
              {switchInput("share_session_in_group")}
            </Field>
          </>
        );

      case "qq":
        return (
          <>
            <InfoAlert message={t("channels.qqSetupGuide")} />
            <QrcodeAuthBlock
              label={t("channels.qqScanAuth")}
              buttonText={t("channels.qqGetQrcode")}
              imageAlt="QQ QR Code"
              hintText={t("channels.qqScanHint")}
              channel="qq"
              successStatus="success"
              successCredentialKey="app_id"
              pollInterval={2000}
              pollTimeout={300000}
              maxPollCount={180}
              onSuccess={(credentials) => {
                form.setFieldsValue({
                  app_id: credentials.app_id,
                  client_secret: credentials.client_secret,
                  user_openid: credentials.user_openid,
                });
                message.success(t("channels.qqAuthSuccess"));
              }}
              onError={(type) => {
                if (type === "expired")
                  message.warning(t("channels.qqQrcodeExpired"));
                else message.error(t("channels.qqQrcodeFailed"));
              }}
            />
            <Field label="App ID" required>
              {textInput("app_id")}
            </Field>
            <Field label="Client Secret" required>
              {textInput("client_secret", "", "password")}
            </Field>
            <Field
              label={t("channels.ackMessage")}
              tooltip={t("channels.ackMessageTooltip")}
            >
              {textInput("ack_message", t("channels.ackMessagePlaceholder"))}
            </Field>
          </>
        );

      case "telegram":
        return (
          <>
            <Field label="Bot Token" required>
              {textInput(
                "bot_token",
                "Telegram bot token from BotFather",
                "password",
              )}
            </Field>
            <Field label="HTTP Proxy">
              {textInput("http_proxy", "http://127.0.0.1:18118")}
            </Field>
            <Field label="HTTP Proxy Auth">
              {textInput("http_proxy_auth", "user:password")}
            </Field>
            <Field label="Show Typing">{switchInput("show_typing")}</Field>
          </>
        );

      case "mqtt":
        return (
          <>
            <Field label="MQTT Host" required>
              {textInput("host", "127.0.0.1")}
            </Field>
            <Field label="MQTT Port" required>
              {numInput("port", "1883", 1, 65535)}
            </Field>
            <Field label="Transport" required>
              {selectInput(
                "transport",
                [
                  { value: "tcp", label: "MQTT (tcp)" },
                  { value: "websockets", label: "WS (websockets)" },
                ],
                "tcp",
              )}
            </Field>
            <Field label="Clean Session">{switchInput("clean_session")}</Field>
            <Field label="QoS" required>
              {selectInput(
                "qos",
                [
                  { value: "0", label: "At Most Once (0)" },
                  { value: "1", label: "At Least Once (1)" },
                  { value: "2", label: "Exactly Once (2)" },
                ],
                "2",
              )}
            </Field>
            <Field label="MQTT Username">
              {textInput("username", "Leave blank to disable / not use")}
            </Field>
            <Field label="MQTT Password">
              {textInput(
                "password",
                "Leave blank to disable / not use",
                "password",
              )}
            </Field>
            <Field label="Subscribe Topic" required>
              {textInput("subscribe_topic", "server/+/up")}
            </Field>
            <Field label="Publish Topic" required>
              {textInput("publish_topic", "client/{client_id}/down")}
            </Field>
            <Field label="TLS Enabled">{switchInput("tls_enabled")}</Field>
            <Field label="TLS CA Certs">
              {textInput("tls_ca_certs", "Path to CA certificates file")}
            </Field>
            <Field label="TLS Certfile">
              {textInput("tls_certfile", "Path to client certificate file")}
            </Field>
            <Field label="TLS Keyfile">
              {textInput("tls_keyfile", "Path to client private key file")}
            </Field>
          </>
        );

      case "mattermost":
        return (
          <>
            <Field label="Mattermost URL" required>
              {textInput("url", "https://mattermost.example.com")}
            </Field>
            <Field label="Bot Token" required>
              {textInput("bot_token", "Mattermost bot token", "password")}
            </Field>
            <Field label={t("channels.wechatMediaDir")}>
              {textInput("media_dir", defaultMediaDir)}
            </Field>
            <Field label="Show Typing">{switchInput("show_typing")}</Field>
            <Field label="Thread Follow Without Mention">
              {switchInput("thread_follow_without_mention")}
            </Field>
          </>
        );

      case "voice":
        return (
          <>
            <InfoAlert message={t("channels.voiceSetupGuide")} />
            <Field label={t("channels.twilioAccountSid")} required>
              {textInput("twilio_account_sid", "ACxxxxxxxx")}
            </Field>
            <Field label={t("channels.twilioAuthToken")} required>
              {textInput("twilio_auth_token", "", "password")}
            </Field>
            <Field label={t("channels.phoneNumber")}>
              {textInput("phone_number", "+15551234567")}
            </Field>
            <Field
              label={t("channels.phoneNumberSid")}
              tooltip={t("channels.phoneNumberSidHelp")}
            >
              {textInput("phone_number_sid", "PNxxxxxxxx")}
            </Field>
            <Field label={t("channels.ttsProvider")}>
              {textInput("tts_provider", "google")}
            </Field>
            <Field label={t("channels.ttsVoice")}>
              {textInput("tts_voice", "en-US-Journey-D")}
            </Field>
            <Field label={t("channels.sttProvider")}>
              {textInput("stt_provider", "deepgram")}
            </Field>
            <Field label={t("channels.language")}>
              {textInput("language", "en-US")}
            </Field>
            <Field label={t("channels.welcomeGreeting")}>
              <Textarea
                rows={2}
                value={get("welcome_greeting") ?? ""}
                onChange={(e) => set("welcome_greeting", e.target.value)}
              />
            </Field>
          </>
        );

      case "sip":
        return (
          <>
            <InfoAlert message={t("channels.sipSetupGuide")} />
            <Field
              label={t("channels.sipMode")}
              tooltip={t("channels.sipModeTooltip")}
            >
              {selectInput(
                "sip_mode",
                [
                  { value: "dev", label: "Dev (pyVoIP)" },
                  { value: "livekit", label: "Production (LiveKit)" },
                ],
                "dev",
              )}
            </Field>
            <Field label={t("channels.sipServer")}>
              {textInput(
                "sip_server",
                get("sip_mode") === "livekit"
                  ? t("channels.sipServerPlaceholderLivekit")
                  : t("channels.sipServerPlaceholder"),
              )}
            </Field>
            <Field label={t("channels.sipUsername")}>
              {textInput("sip_username", "1001")}
            </Field>
            <Field label={t("channels.sipPassword")}>
              {textInput("sip_password", "", "password")}
            </Field>
            <Field label={t("channels.sipPort")}>
              {numInput("sip_port", "5061", 1, 65535)}
            </Field>
            <Field label={t("channels.sipTransport")}>
              {selectInput(
                "sip_transport",
                [
                  { value: "UDP", label: "UDP" },
                  { value: "TCP", label: "TCP" },
                  { value: "TLS", label: "TLS" },
                ],
                "UDP",
              )}
            </Field>
            <Field
              label={t("channels.sipDashscopeApiKey")}
              tooltip={t("channels.sipDashscopeApiKeyTooltip")}
            >
              {textInput("dashscope_api_key", "sk-...", "password")}
            </Field>
            <Field label={t("channels.ttsProvider")}>
              {textInput("tts_provider", "aliyun")}
            </Field>
            <Field label={t("channels.ttsVoice")}>
              {textInput("tts_voice", "longxiaochun")}
            </Field>
            <Field label={t("channels.sttProvider")}>
              {textInput("stt_provider", "aliyun")}
            </Field>
            <Field label={t("channels.language")}>
              {textInput("language", "zh-CN")}
            </Field>
            <Field label={t("channels.welcomeGreeting")}>
              <Textarea
                rows={2}
                value={get("welcome_greeting") ?? ""}
                onChange={(e) => set("welcome_greeting", e.target.value)}
              />
            </Field>
            {get("sip_mode") === "livekit" && (
              <>
                <Field label={t("channels.livekitUrl")} required>
                  {textInput("livekit_url", "ws://localhost:7880")}
                </Field>
                <Field label={t("channels.livekitApiKey")} required>
                  {textInput("livekit_api_key")}
                </Field>
                <Field label={t("channels.livekitApiSecret")} required>
                  {textInput("livekit_api_secret", "", "password")}
                </Field>
                <Field label={t("channels.livekitSipTrunkId")}>
                  {textInput("livekit_sip_trunk_id", "ST_xxxx")}
                </Field>
                <Field
                  label={t("channels.livekitRoomName")}
                  tooltip={t("channels.livekitRoomNameTooltip")}
                >
                  {textInput("livekit_room_name", "sip-inbound")}
                </Field>
              </>
            )}
          </>
        );

      case "wecom":
        return (
          <>
            <InfoAlert
              message={t("channels.wecomSetupGuide")}
              variant="warning"
            />
            <QrcodeAuthBlock
              label={t("channels.wecomScanAuth")}
              buttonText={t("channels.loginWeCom")}
              imageAlt="WeCom QR Code"
              hintText={t("channels.wecomAuthHint")}
              channel="wecom"
              successStatus="success"
              successCredentialKey="bot_id"
              pollInterval={3000}
              onSuccess={(credentials) => {
                form.setFieldsValue({
                  bot_id: credentials.bot_id,
                  secret: credentials.secret,
                });
                message.success(t("channels.wecomAuthSuccess"));
              }}
              onError={() => message.error(t("channels.wecomQrcodeFailed"))}
            />
            <Field label="Bot ID" required>
              {textInput("bot_id", "Bot ID from WeCom backend")}
            </Field>
            <Field label="Secret" required>
              {textInput("secret", "Secret from WeCom backend", "password")}
            </Field>
            <Field label={t("channels.wechatMediaDir")}>
              {textInput("media_dir", defaultMediaDir)}
            </Field>
            <Field
              label={t("channels.welcomeText")}
              tooltip={t("channels.welcomeTextTooltip")}
            >
              {textInput("welcome_text", t("channels.welcomeTextPlaceholder"))}
            </Field>
            <Field
              label={t("channels.shareSessionInGroup")}
              tooltip={t("channels.shareSessionInGroupTooltip")}
            >
              {switchInput("share_session_in_group")}
            </Field>
          </>
        );

      case "xiaoyi":
        return (
          <>
            <InfoAlert message={t("channels.xiaoyiSetupGuide")} />
            <Field label="Access Key (AK)" required>
              {textInput("ak", "Access Key from Huawei Developer Platform")}
            </Field>
            <Field label="Secret Key (SK)" required>
              {textInput(
                "sk",
                "Secret Key from Huawei Developer Platform",
                "password",
              )}
            </Field>
            <Field label="Agent ID" required>
              {textInput("agent_id", "Agent ID from XiaoYi platform")}
            </Field>
            <Field label="WebSocket URL">
              {textInput(
                "ws_url",
                "wss://hag.cloud.huawei.com/openclaw/v1/ws/link",
              )}
            </Field>
          </>
        );

      case "wechat":
        return (
          <>
            <InfoAlert message={t("channels.wechatSetupGuide")} />
            <InfoAlert
              message={t("channels.wechatContextTokenLimit")}
              variant="warning"
            />
            <QrcodeAuthBlock
              label={t("channels.wechatScanLogin")}
              buttonText={t("channels.wechatGetQrcode")}
              imageAlt="WeChat QR Code"
              hintText={t("channels.wechatScanHint")}
              channel="wechat"
              successStatus="confirmed"
              successCredentialKey="bot_token"
              pollInterval={2000}
              onSuccess={(credentials) => {
                form.setFieldsValue({ bot_token: credentials.bot_token });
                message.success(t("channels.wechatLoginSuccess"));
              }}
              onError={(type) => {
                if (type === "expired")
                  message.warning(t("channels.wechatQrcodeExpired"));
                else message.error(t("channels.wechatQrcodeFailed"));
              }}
            />
            <Field
              label={t("channels.wechatBotToken")}
              tooltip={t("channels.wechatBotTokenTooltip")}
            >
              {textInput(
                "bot_token",
                t("channels.wechatBotTokenPlaceholder"),
                "password",
              )}
            </Field>
            <Field
              label={t("channels.wechatBotTokenFile")}
              tooltip={t("channels.wechatBotTokenFileTooltip")}
            >
              {textInput("bot_token_file", "~/.qwenpaw/wechat_bot_token")}
            </Field>
            <Field label={t("channels.wechatMediaDir")}>
              {textInput("media_dir", defaultMediaDir)}
            </Field>
            <Field
              label={t("channels.wechatMessageMerge")}
              tooltip={t("channels.wechatMessageMergeTooltip")}
            >
              {switchInput("message_merge_enabled")}
            </Field>
            {get("message_merge_enabled") && (
              <Field
                label={t("channels.wechatMessageMergeDelayMs")}
                tooltip={t("channels.wechatMessageMergeDelayMsTooltip")}
              >
                {numInput("message_merge_delay_ms", "0", 0, undefined, 100)}
              </Field>
            )}
          </>
        );

      case "yuanbao":
        return (
          <>
            <Field label="App ID" required>
              {textInput("app_id", "App ID from Yuanbao platform")}
            </Field>
            <Field label="App Secret" required>
              {textInput(
                "app_secret",
                "App Secret from Yuanbao platform",
                "password",
              )}
            </Field>
            <Field
              label="API Domain"
              tooltip="REST API domain for sign-token auth"
            >
              {textInput("api_domain", "bot.yuanbao.tencent.com")}
            </Field>
            <Field label={t("channels.wechatMediaDir")}>
              {textInput("media_dir", defaultMediaDir)}
            </Field>
          </>
        );

      case "onebot":
        return (
          <>
            <Field label="WebSocket Host" required>
              {textInput("ws_host", "0.0.0.0")}
            </Field>
            <Field label="WebSocket Port" required>
              {numInput("ws_port", "6199", 1, 65535)}
            </Field>
            <Field label="Access Token">
              {textInput(
                "access_token",
                "Access token for authentication",
                "password",
              )}
            </Field>
            <Field
              label={t("channels.shareSessionInGroup")}
              tooltip={t("channels.shareSessionInGroupTooltip")}
            >
              {switchInput("share_session_in_group")}
            </Field>
          </>
        );

      default:
        return null;
    }
  };

  // ── Custom channel extra fields ───────────────────────────────────────────

  const renderCustomExtraFields = (
    vals: Record<string, unknown> | undefined,
  ) => {
    if (!vals) return null;
    const extraKeys = Object.keys(vals).filter((k) => !BASE_FIELDS.includes(k));
    if (extraKeys.length === 0) return null;

    return (
      <>
        <div className="mb-2 font-medium text-sm">Custom Fields</div>
        {extraKeys.map((fieldKey) => {
          const value = vals[fieldKey];
          return (
            <Field key={fieldKey} label={fieldKey}>
              {typeof value === "boolean"
                ? switchInput(fieldKey)
                : typeof value === "number"
                ? numInput(fieldKey)
                : textInput(fieldKey)}
            </Field>
          );
        })}
      </>
    );
  };

  const docUrl = activeKey
    ? currentLang === "zh"
      ? CHANNEL_DOC_ZH_URLS[activeKey]
      : CHANNEL_DOC_EN_URLS[activeKey]
    : undefined;

  return (
    <Sheet key={activeKey} open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-[420px] flex flex-col p-0">
        <SheetHeader className="px-6 py-4 border-b">
          <SheetTitle className="flex items-center justify-between">
            <span>
              {label
                ? `${label} ${t("channels.settings")}`
                : t("channels.channelSettings")}
            </span>
            <div className="flex items-center gap-1">
              {docUrl && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-primary text-xs px-2"
                  onClick={() => openExternalLink(docUrl)}
                >
                  <ExternalLink size={12} className="mr-1" />
                  {label} Doc
                </Button>
              )}
              {activeKey === "voice" && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-primary text-xs px-2"
                  onClick={() => openExternalLink(TWILIO_CONSOLE_URL)}
                >
                  <ExternalLink size={12} className="mr-1" />
                  {t("channels.voiceSetupLink")}
                </Button>
              )}
            </div>
          </SheetTitle>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {activeKey && (
            <div className="flex flex-col">
              <Field label={t("common.enabled")}>
                {switchInput("enabled")}
              </Field>

              {activeKey !== "voice" && (
                <Field label="Bot Prefix">
                  {textInput("bot_prefix", "@bot")}
                </Field>
              )}

              {activeKey !== "console" && (
                <>
                  <Field
                    label={t("channels.filterToolMessages")}
                    tooltip={t("channels.filterToolMessagesTooltip")}
                  >
                    {switchInput("filter_tool_messages")}
                  </Field>
                  <Field
                    label={t("channels.filterThinking")}
                    tooltip={t("channels.filterThinkingTooltip")}
                  >
                    {switchInput("filter_thinking")}
                  </Field>
                </>
              )}

              {(activeKey === "wecom" ||
                activeKey === "telegram" ||
                activeKey === "dingtalk" ||
                activeKey === "feishu") && (
                <Field
                  label={t("channels.streamingEnabled")}
                  tooltip={
                    activeKey === "dingtalk"
                      ? t("channels.streamingEnabledDingtalkHint")
                      : activeKey === "feishu"
                      ? t("channels.streamingEnabledFeishuHint")
                      : undefined
                  }
                >
                  {switchInput("streaming_enabled")}
                </Field>
              )}

              {isBuiltin
                ? renderBuiltinExtraFields(activeKey)
                : renderCustomExtraFields(initialValues)}

              {CHANNELS_WITH_ACCESS_CONTROL.includes(activeKey) &&
                renderAccessControlFields()}
            </div>
          )}
        </div>

        <SheetFooter className="px-6 py-4 border-t flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving && <Loader2 size={14} className="animate-spin mr-2" />}
            {t("common.save")}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
