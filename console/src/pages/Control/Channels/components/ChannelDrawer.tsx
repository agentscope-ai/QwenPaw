import {
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

// DingTalk doc URL
const dingtalkDocUrl = "https://copaw.agentscope.io/docs/channels";

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
      case "mqtt":
        return (
          <>
            <Form.Item name="host" label="MQTT Host">
              <Input placeholder="127.0.0.1" />
            </Form.Item>
            <Form.Item name="port" label="MQTT Port">
              <Input placeholder="1883" />
            </Form.Item>
            <Form.Item name="transport" label="Transport" initialValue="mqtt">
              <Select>
                <Select.Option value="tcp">MQTT (tcp)</Select.Option>
                <Select.Option value="websockets">WS (websockets)</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item name="username" label="MQTT Username">
              <Input placeholder="Leave blank to disable / not use" />
            </Form.Item>
            <Form.Item name="password" label="MQTT Password">
              <Input.Password placeholder="Leave blank to disable / not use" />
            </Form.Item>
            <Form.Item name="subscribe_topic" label="Subscribe Topic">
              <Input placeholder="server/+/up" />
            </Form.Item>
            <Form.Item name="publish_topic" label="Publish Topic">
              <Input placeholder="client/{client_id}/down" />
            </Form.Item>
            <Form.Item name="tls_enabled" label="TLS Enabled" valuePropName="checked">
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
          {activeKey === "dingtalk" && (
            <Button
              type="text"
              size="small"
              icon={<LinkOutlined />}
              onClick={() => window.open(dingtalkDocUrl, "_blank")}
              className={styles.dingtalkDocBtn}
            >
              DingTalk Doc
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