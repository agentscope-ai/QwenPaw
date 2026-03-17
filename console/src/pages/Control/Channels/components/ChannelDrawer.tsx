import {
  Alert,
  Drawer,
  Form,
  Input,
  InputNumber,
  Switch,
  Button,
  Select,
} from "@agentscope-ai/design";
import { LinkOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { FormInstance } from "antd";
import { getChannelLabel, type ChannelKey } from "./constants";
import styles from "../index.module.less";

const CHANNELS_WITH_ACCESS_CONTROL: ChannelKey[] = [
  "telegram",
  "dingtalk",
  "discord",
  "feishu",
  "wecom",
  "mattermost",
  "matrix",
  "xiaoyi",
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

// Doc URLs per channel (anchors on https://copaw.agentscope.io/docs/channels)
const CHANNEL_DOC_URLS: Partial<Record<ChannelKey, string>> = {
  dingtalk:
    "https://copaw.agentscope.io/docs/channels/#%E9%92%89%E9%92%89%E6%8E%A8%E8%8D%90",
  feishu: "https://copaw.agentscope.io/docs/channels/#%E9%A3%9E%E4%B9%A6",
  imessage:
    "https://copaw.agentscope.io/docs/channels/#iMessage%E4%BB%85-macOS",
  discord: "https://copaw.agentscope.io/docs/channels/#Discord",
  qq: "https://copaw.agentscope.io/docs/channels/#QQ",
  telegram: "https://copaw.agentscope.io/docs/channels/#Telegram",
  mqtt: "https://copaw.agentscope.io/docs/channels/#MQTT",
  mattermost: "https://copaw.agentscope.io/docs/channels/#Mattermost",
  matrix: "https://copaw.agentscope.io/docs/channels/#Matrix",
  wecom:
    "https://copaw.agentscope.io/docs/channels/#%E4%BC%81%E4%B8%9A%E5%BE%AE%E4%BF%A1",
  xiaoyi:
    "https://developer.huawei.com/consumer/cn/doc/service/openclaw-0000002518410344",
};
const twilioConsoleUrl = "https://console.twilio.com";

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
  const { t } = useTranslation();
  const label = activeKey ? getChannelLabel(activeKey) : activeLabel;

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
        />
      </Form.Item>
    </>
  );

  // Renders builtin channel-specific fields
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
            <Form.Item name="bot_token" label="Bot Token">
              <Input.Password placeholder="Discord bot token" />
            </Form.Item>
            <Form.Item name="http_proxy" label="HTTP Proxy">
              <Input placeholder="http://127.0.0.1:18118" />
            </Form.Item>
            <Form.Item name="http_proxy_auth" label="HTTP Proxy Auth">
              <Input placeholder="user:password" />
            </Form.Item>
          </>
        );
      case "dingtalk":
        return (
          <>
            <Form.Item name="client_id" label="Client ID">
              <Input />
            </Form.Item>
            <Form.Item name="client_secret" label="Client Secret">
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
                const isCard = getFieldValue("message_type") === "card";
                if (!isCard) return null;
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
            <Form.Item name="media_dir" label="Media Dir">
              <Input placeholder="~/.copaw/media" />
            </Form.Item>
          </>
        );
      case "qq":
        return (
          <>
            <Form.Item name="app_id" label="App ID">
              <Input />
            </Form.Item>
            <Form.Item name="client_secret" label="Client Secret">
              <Input.Password />
            </Form.Item>
          </>
        );
      case "telegram":
        return (
          <>
            <Form.Item name="bot_token" label="Bot Token">
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
            <Form.Item name="bot_token" label="Bot Token">
              <Input.Password placeholder="Mattermost bot token" />
            </Form.Item>
            <Form.Item name="media_dir" label="Media Dir">
              <Input placeholder="~/.copaw/media/mattermost" />
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
            <Alert
              type="info"
              showIcon
              message={t("channels.voiceSetupGuide")}
              style={{ marginBottom: 16 }}
            />
            <Form.Item
              name="twilio_account_sid"
              label={t("channels.twilioAccountSid")}
            >
              <Input placeholder="ACxxxxxxxx" />
            </Form.Item>
            <Form.Item
              name="twilio_auth_token"
              label={t("channels.twilioAuthToken")}
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
            <Form.Item name="media_dir" label="Media Dir">
              <Input placeholder="~/.copaw/media" />
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
            <Alert
              type="info"
              showIcon
              message={t("channels.xiaoyiSetupGuide")}
              style={{ marginBottom: 16 }}
            />
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
      default:
        return null;
    }
  };

  // Renders custom channel fields as key-value editor
  const renderCustomExtraFields = (
    initialValues: Record<string, unknown> | undefined,
  ) => {
    if (!initialValues) return null;

    // Get extra fields (exclude base fields)
    const baseFields = [
      "enabled",
      "bot_prefix",
      "filter_tool_messages",
      "filter_thinking",
      "isBuiltin",
    ];
    const extraKeys = Object.keys(initialValues).filter(
      (k) => !baseFields.includes(k),
    );

    if (extraKeys.length === 0) return null;

    return (
      <>
        <div style={{ marginBottom: 8, fontWeight: 500 }}>Custom Fields</div>
        {extraKeys.map((fieldKey) => {
          const value = initialValues[fieldKey];
          const isBoolean = typeof value === "boolean";
          const isNumber = typeof value === "number";

          return (
            <Form.Item key={fieldKey} name={fieldKey} label={fieldKey}>
              {isBoolean ? (
                <Switch />
              ) : isNumber ? (
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

  return (
    <Drawer
      width={420}
      placement="right"
      title={
        <div className={styles.drawerTitle}>
          <span>
            {label
              ? `${label} ${t("channels.settings")}`
              : t("channels.channelSettings")}
          </span>
          {activeKey && CHANNEL_DOC_URLS[activeKey] && (
            <Button
              type="text"
              size="small"
              icon={<LinkOutlined />}
              onClick={() => window.open(CHANNEL_DOC_URLS[activeKey], "_blank")}
              className={styles.dingtalkDocBtn}
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
                window.open(twilioConsoleUrl, "_blank", "noopener,noreferrer")
              }
              className={styles.dingtalkDocBtn}
            >
              {t("channels.voiceSetupLink")}
            </Button>
          )}
        </div>
      }
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {activeKey && (
        <Form
          form={form}
          layout="vertical"
          initialValues={initialValues}
          onFinish={onSubmit}
        >
          <Form.Item name="enabled" label="Enabled" valuePropName="checked">
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

          <Form.Item>
            <div className={styles.formActions}>
              <Button onClick={onClose}>{t("common.cancel")}</Button>
              <Button type="primary" htmlType="submit" loading={saving}>
                {t("common.save")}
              </Button>
            </div>
          </Form.Item>
        </Form>
      )}
    </Drawer>
  );
}
