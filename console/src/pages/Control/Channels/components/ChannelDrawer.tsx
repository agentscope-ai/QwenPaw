import {
  Drawer,
  Form,
  Input,
  InputNumber,
  Switch,
  Button,
} from "@agentscope-ai/design";
import { LinkOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { FormInstance } from "antd";
import type { SingleChannelConfig } from "../../../../api/types";
import type { ChannelKey } from "./constants";
import styles from "../index.module.less";

interface ChannelDrawerProps {
  open: boolean;
  activeKey: ChannelKey | null;
  activeLabel: string;
  form: FormInstance<SingleChannelConfig>;
  saving: boolean;
  initialValues: SingleChannelConfig | undefined;
  onClose: () => void;
  onSubmit: (values: SingleChannelConfig) => void;
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
};

export function ChannelDrawer({
  open,
  activeKey,
  activeLabel,
  form,
  saving,
  initialValues,
  onClose,
  onSubmit,
}: ChannelDrawerProps) {
  const { t } = useTranslation();

  const renderExtraFields = (key: ChannelKey) => {
    switch (key) {
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
      default:
        return null;
    }
  };

  return (
    <Drawer
      width={420}
      placement="right"
      title={
        <div className={styles.drawerTitle}>
          <span>
            {activeLabel
              ? `${activeLabel} ${t("channels.settings")}`
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
              {activeLabel} Doc
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

          <Form.Item name="bot_prefix" label="Bot Prefix">
            <Input placeholder="@bot" />
          </Form.Item>

          {activeKey !== "console" && (
            <Form.Item
              name="filter_tool_messages"
              label={t("channels.filterToolMessages")}
              valuePropName="checked"
              tooltip={t("channels.filterToolMessagesTooltip")}
            >
              <Switch />
            </Form.Item>
          )}

          {renderExtraFields(activeKey)}

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
