import { useMemo, useState } from "react";
import { Form, message } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";

import api from "../../../api";
import type { SingleChannelConfig } from "../../../api/types";
import {
  ChannelCard,
  ChannelDrawer,
  useChannels,
  CHANNEL_LABELS,
  type ChannelKey,
} from "./components";
import styles from "./index.module.less";

function ChannelsPage() {
  const { t } = useTranslation();
  const { channels, loading, fetchChannels } = useChannels();
  const [saving, setSaving] = useState(false);
  const [hoverKey, setHoverKey] = useState<ChannelKey | null>(null);
  const [activeKey, setActiveKey] = useState<ChannelKey | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [form] = Form.useForm<SingleChannelConfig>();

  const cards = useMemo(() => {
    const entries: { key: ChannelKey; config: SingleChannelConfig }[] = [];

    const channelOrder: ChannelKey[] = [
      "console",
      "dingtalk",
      "feishu",
      "imessage",
      "discord",
      "telegram",
      "qq",
    ];

    channelOrder.forEach((key) => {
      if (channels[key] && channels[key].enabled) {
        entries.push({ key, config: channels[key] });
      }
    });

    channelOrder.forEach((key) => {
      if (channels[key] && !channels[key].enabled) {
        entries.push({ key, config: channels[key] });
      }
    });

    return entries;
  }, [channels]);

  const handleCardClick = (key: ChannelKey) => {
    setActiveKey(key);
    setDrawerOpen(true);
    const channelConfig = channels[key];
    form.setFieldsValue({
      ...channelConfig,
      filter_tool_messages: !channelConfig.filter_tool_messages,
    });
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setActiveKey(null);
  };

  const handleSubmit = async (values: SingleChannelConfig) => {
    if (!activeKey) return;

    const updatedChannel: SingleChannelConfig = {
      ...channels[activeKey],
      ...values,
      filter_tool_messages: !values.filter_tool_messages,
    };

    setSaving(true);
    try {
      await api.updateChannelConfig(activeKey, updatedChannel);
      await fetchChannels();

      setDrawerOpen(false);
      message.success(t("channels.configSaved"));
    } catch (error) {
      console.error("❌ Failed to update channel config:", error);
      message.error(t("channels.configFailed"));
    } finally {
      setSaving(false);
    }
  };

  const activeLabel = activeKey ? CHANNEL_LABELS[activeKey] : "";

  return (
    <div className={styles.channelsPage}>
      <h1 className={styles.title}>{t("channels.title")}</h1>
      <p className={styles.description}>{t("channels.description")}</p>

      {loading ? (
        <div className={styles.loading}>
          <span className={styles.loadingText}>{t("channels.loading")}</span>
        </div>
      ) : (
        <div className={styles.channelsGrid}>
          {cards.map(({ key, config }) => (
            <ChannelCard
              key={key}
              channelKey={key}
              config={config}
              isHover={hoverKey === key}
              onClick={() => handleCardClick(key)}
              onMouseEnter={() => setHoverKey(key)}
              onMouseLeave={() => setHoverKey(null)}
            />
          ))}
        </div>
      )}

      <ChannelDrawer
        open={drawerOpen}
        activeKey={activeKey}
        activeLabel={activeLabel}
        form={form}
        saving={saving}
        initialValues={activeKey ? channels[activeKey] : undefined}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />
    </div>
  );
}

export default ChannelsPage;
