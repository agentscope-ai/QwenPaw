import { useMemo, useState } from "react";
import { Form } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import {
  ChannelCard,
  ChannelDrawer,
  useChannels,
  getChannelLabel,
  type ChannelKey,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import styles from "./index.module.less";

type FilterType = "all" | "builtin" | "custom";

function ChannelsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { channels, orderedKeys, isBuiltin, loading, fetchChannels } =
    useChannels();
  const [filter, setFilter] = useState<FilterType>("all");
  const [saving, setSaving] = useState(false);
  const [hoverKey, setHoverKey] = useState<ChannelKey | null>(null);
  const [activeKey, setActiveKey] = useState<ChannelKey | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [form] = Form.useForm<any>();

  // Sort cards: enabled first, then disabled (preserve orderedKeys order within each group)
  const cards = useMemo(() => {
    const enabledCards: { key: ChannelKey; config: Record<string, unknown> }[] =
      [];
    const disabledCards: {
      key: ChannelKey;
      config: Record<string, unknown>;
    }[] = [];

    orderedKeys.forEach((key) => {
      const config = channels[key] || { enabled: false, bot_prefix: "" };
      const builtin = isBuiltin(key);
      if (filter === "builtin" && !builtin) return;
      if (filter === "custom" && builtin) return;
      if (config.enabled) {
        enabledCards.push({ key, config });
      } else {
        disabledCards.push({ key, config });
      }
    });

    return [...enabledCards, ...disabledCards];
  }, [channels, orderedKeys, filter, isBuiltin]);

  const handleCardClick = (key: ChannelKey) => {
    setActiveKey(key);
    setDrawerOpen(true);
    const channelConfig = channels[key] || { enabled: false, bot_prefix: "" };
    form.setFieldsValue({
      ...channelConfig,
      filter_tool_messages: !channelConfig.filter_tool_messages,
      filter_thinking: !channelConfig.filter_thinking,
    });
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setActiveKey(null);
  };

  const handleSubmit = async (values: Record<string, unknown>) => {
    if (!activeKey) return;

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { isBuiltin: _isBuiltin, ...savedConfig } = channels[activeKey] || {};
    const updatedChannel: Record<string, unknown> = {
      ...savedConfig,
      ...values,
    };

    if (typeof values.filter_tool_messages === "boolean") {
      updatedChannel.filter_tool_messages = !values.filter_tool_messages;
    }
    if (typeof values.filter_thinking === "boolean") {
      updatedChannel.filter_thinking = !values.filter_thinking;
    }

    setSaving(true);
    try {
      await api.updateChannelConfig(
        activeKey,
        updatedChannel as unknown as Parameters<
          typeof api.updateChannelConfig
        >[1],
      );
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

  const activeLabel = activeKey ? getChannelLabel(activeKey, t) : "";

  const FILTER_TABS: { key: FilterType; label: string }[] = [
    { key: "all", label: t("channels.filterAll") },
    { key: "builtin", label: t("channels.builtin") },
    { key: "custom", label: t("channels.custom") },
  ];

  return (
    <div className={styles.channelsPage}>
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("channels.title") }]}
        center={
          <div className={styles.filterTabs}>
            {FILTER_TABS.map(({ key, label }) => (
              <button
                key={key}
                className={`${styles.filterTab} ${
                  filter === key ? styles.filterTabActive : ""
                }`}
                onClick={() => setFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>
        }
      />
      <div className={styles.channelsContainer}>
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
      </div>
      <ChannelDrawer
        open={drawerOpen}
        activeKey={activeKey}
        activeLabel={activeLabel}
        form={form}
        saving={saving}
        initialValues={activeKey ? channels[activeKey] : undefined}
        isBuiltin={activeKey ? isBuiltin(activeKey) : true}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />
    </div>
  );
}

export default ChannelsPage;
