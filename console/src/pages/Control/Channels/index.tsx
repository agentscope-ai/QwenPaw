import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import {
  ChannelCard,
  ChannelDrawer,
  AccessControlDrawer,
  PendingApprovalsDrawer,
  useChannels,
  getChannelLabel,
  type ChannelKey,
} from "./components";
import type { ChannelFormProxy } from "./components/ChannelDrawer";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type FilterType = "all" | "builtin" | "custom";

function ChannelsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { channels, orderedKeys, isBuiltin, loading, fetchChannels } =
    useChannels();
  const [filter, setFilter] = useState<FilterType>("all");
  const [saving, setSaving] = useState(false);
  const [activeKey, setActiveKey] = useState<ChannelKey | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [aclDrawerOpen, setAclDrawerOpen] = useState(false);
  const [pendingDrawerOpen, setPendingDrawerOpen] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);

  // Form proxy — ChannelDrawer wires up its methods internally via useEffect
  const form = useRef<ChannelFormProxy>({
    getFieldValue: (_name: string) => undefined,
    setFieldsValue: (_values: Record<string, any>) => {},
    resetFields: () => {},
    submit: () => {},
  });

  const fetchPendingCount = useCallback(async () => {
    try {
      const data = await api.getAclAllPending();
      setPendingCount(data.length);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchPendingCount();
  }, [fetchPendingCount]);

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
    const accessControlDm =
      channelConfig.access_control_dm ||
      channelConfig.dm_policy === "allowlist";
    const accessControlGroup =
      channelConfig.access_control_group ||
      channelConfig.group_policy === "allowlist";
    form.current.setFieldsValue({
      ...channelConfig,
      access_control_dm: accessControlDm,
      access_control_group: accessControlGroup,
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
      filter_tool_messages: !values.filter_tool_messages,
      filter_thinking: !values.filter_thinking,
    };

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
      console.error("Failed to update channel config:", error);
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
    <div className="flex flex-col h-full">
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("channels.title") }]}
        center={
          <div className="flex border rounded-md overflow-hidden">
            {FILTER_TABS.map(({ key, label }) => (
              <button
                key={key}
                className={cn(
                  "px-4 py-1.5 text-sm transition-colors",
                  filter === key
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted",
                )}
                onClick={() => setFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>
        }
        extra={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className={pendingCount > 0 ? "relative" : ""}
              onClick={() => setPendingDrawerOpen(true)}
            >
              {pendingCount > 0 && (
                <span className="absolute -top-1 -right-1 w-2 h-2 bg-destructive rounded-full" />
              )}
              {t("channels.pendingApprovals")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAclDrawerOpen(true)}
            >
              {t("channels.manageAccessControl")}
            </Button>
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {loading ? (
          <div className="flex justify-center items-center h-32">
            <Loader2 className="animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {cards.map(({ key, config }) => (
              <ChannelCard
                key={key}
                channelKey={key}
                config={config}
                onClick={() => handleCardClick(key)}
              />
            ))}
          </div>
        )}
      </div>

      <ChannelDrawer
        open={drawerOpen}
        activeKey={activeKey}
        activeLabel={activeLabel}
        form={form.current}
        saving={saving}
        initialValues={activeKey ? channels[activeKey] : undefined}
        isBuiltin={activeKey ? isBuiltin(activeKey) : true}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />

      <AccessControlDrawer
        open={aclDrawerOpen}
        onClose={() => setAclDrawerOpen(false)}
      />

      <PendingApprovalsDrawer
        open={pendingDrawerOpen}
        onClose={() => {
          setPendingDrawerOpen(false);
          fetchPendingCount();
        }}
      />
    </div>
  );
}

export default ChannelsPage;
