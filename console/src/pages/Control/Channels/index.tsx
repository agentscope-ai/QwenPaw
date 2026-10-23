import { useAgentStore } from "@/stores/agentStore";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { Cascade } from "@/components/interaction/Cascade";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Form } from "@agentscope-ai/design";
import { Badge, Button, Space } from "antd";
import {
  ShieldCheck as SafetyOutlined,
  ClipboardCheck as AuditOutlined,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import {
  ChannelCard,
  ChannelDrawer,
  AccessControlDrawer,
  PendingApprovalsDrawer,
  useChannels,
  getChannelLabel,
  ChannelAvailableItem,
  type ChannelKey,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import {
  captureChannelSaveJob,
  keepConsoleEnabled,
} from "./components/channelConfig";
import type { ChannelSaveJob } from "../../../api/modules/channel";
import styles from "./index.module.less";

type FilterType = "all" | "builtin" | "custom";

function ChannelsPage() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const { modal } = useAppMessage();
  const {
    channels,
    orderedKeys,
    channelSchemas,
    schemasLoading,
    isBuiltin,
    loading,
    setChannels,
    fetchChannels,
  } = useChannels();
  const [filter, setFilter] = useState<FilterType>("all");
  const [saving, setSaving] = useState(false);
  const [activeKey, setActiveKey] = useState<ChannelKey | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [aclDrawerOpen, setAclDrawerOpen] = useState(false);
  const [pendingDrawerOpen, setPendingDrawerOpen] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [form] = Form.useForm<any>();
  const scopeGeneration = useRef(0);
  const mounted = useRef(true);
  useLayoutEffect(() => {
    scopeGeneration.current += 1;
    setDrawerOpen(false);
    setActiveKey(null);
    setSaving(false);
    form.resetFields();
  }, [selectedAgent, form]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useLayoutEffect(
    () =>
      useAgentStore.subscribe((next, previous) => {
        if (next.selectedAgent !== previous.selectedAgent) {
          scopeGeneration.current += 1;
          setSaving(false);
        }
      }),
    [],
  );

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

  // Sort cards: enabled first, then disabled (preserve orderedKeys order within each group)
  const { enabledCards, disabledCards } = useMemo(() => {
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

    return { enabledCards, disabledCards };
  }, [channels, orderedKeys, filter, isBuiltin]);

  const handleCardClick = useCallback(
    (key: ChannelKey) => {
      void fetchChannels(true);
      setActiveKey(key);
      setDrawerOpen(true);
      const channelConfig = keepConsoleEnabled(
        key,
        channels[key] || { enabled: false, bot_prefix: "" },
      );
      form.resetFields();
      // Migrate legacy allowlist policy to new access control fields
      const accessControlDm =
        channelConfig.access_control_dm ||
        channelConfig.dm_policy === "allowlist";
      const accessControlGroup =
        channelConfig.access_control_group ||
        channelConfig.group_policy === "allowlist";
      form.setFieldsValue({
        ...channelConfig,
        access_control_dm: accessControlDm,
        access_control_group: accessControlGroup,
        show_tool_calls: channelConfig.show_tool_calls ?? true,
        show_tool_results: channelConfig.show_tool_results ?? true,
        tool_call_max_length: channelConfig.tool_call_max_length ?? 200,
        tool_result_max_length: channelConfig.tool_result_max_length ?? 500,
        show_thinking: channelConfig.show_thinking ?? true,
      });
    },
    [channels, form, fetchChannels],
  );

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setActiveKey(null);
  };

  const handleSubmitSnapshot = async (job: ChannelSaveJob) => {
    const generation = scopeGeneration.current;
    const currentScope = () =>
      generation === scopeGeneration.current &&
      (useAgentStore.getState().selectedAgent || "default") === job.agentId;
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { isBuiltin: _isBuiltin, ...savedConfig } = job.body;
    const updatedChannel = keepConsoleEnabled(job.channel, savedConfig);
    const proposedConfig = updatedChannel as unknown as Parameters<
      typeof api.updateChannelConfig
    >[1];

    if (mounted.current && currentScope()) setSaving(true);
    try {
      if (updatedChannel.enabled === true) {
        try {
          const result = await api.checkChannelConflict(
            job.channel,
            proposedConfig,
            job.agentId,
          );
          if (result.conflict) {
            const agentNames = result.agents
              .map(({ agent_id, agent_name }) =>
                agent_name === agent_id
                  ? agent_id
                  : `${agent_name} (${agent_id})`,
              )
              .join(", ");
            const shouldSave = await new Promise<boolean>((resolve) => {
              let settled = false;
              const settle = (value: boolean) => {
                if (settled) return;
                settled = true;
                resolve(value);
              };

              modal.confirm({
                centered: true,
                title: t("channels.botConflictTitle"),
                content: t("channels.botConflictDescription", {
                  agents: agentNames,
                }),
                okText: t("channels.botConflictConfirm"),
                okButtonProps: { danger: true },
                cancelText: t("common.cancel"),
                onOk: () => settle(true),
                onCancel: () => settle(false),
                afterClose: () => settle(false),
              });
            });
            if (!shouldSave) return false;
          }
        } catch (error) {
          console.warn("Failed to check channel Bot conflicts:", error);
        }
      }

      await api.updateChannelConfig(
        job.channel,
        proposedConfig,
        job.agentId,
        job.authSession,
      );
      if (mounted.current && currentScope()) {
        setChannels((current) => ({
          ...current,
          [job.channel]: { ...current[job.channel], ...updatedChannel },
        }));
      }
      return true;
    } catch (error) {
      console.error("Failed to update channel config:", error);
      throw error;
    } finally {
      if (mounted.current && currentScope()) setSaving(false);
    }
  };

  const handleSubmit = async (values: Record<string, unknown>) => {
    if (!activeKey) return;
    await handleSubmitSnapshot(
      captureChannelSaveJob({
        agentId: selectedAgent || "default",
        channel: activeKey,
        body: { ...channels[activeKey], ...values },
        formRevision: 0,
      }),
    );
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
        className={styles.pageHeader}
        items={[{ title: t("channels.title") }]}
        center={
          <div className={styles.filterTabs}>
            {FILTER_TABS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                data-press
                aria-pressed={filter === key}
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
        extra={
          <Space size={8} wrap>
            <Badge dot={pendingCount > 0} offset={[-4, 4]}>
              <Button
                icon={<AuditOutlined size="1em" />}
                onClick={() => setPendingDrawerOpen(true)}
              >
                {t("channels.pendingApprovals")}
              </Button>
            </Badge>
            <Button
              icon={<SafetyOutlined size="1em" />}
              onClick={() => setAclDrawerOpen(true)}
            >
              {t("channels.manageAccessControl")}
            </Button>
          </Space>
        }
      />
      <div className={styles.channelsContainer}>
        {loading ? (
          <div className={styles.loading}>
            <span className={styles.loadingText}>{t("channels.loading")}</span>
          </div>
        ) : (
          <>
            {/* Enabled Channels Section */}
            <div className={styles.panelSection}>
              <div className={styles.panelTitle}>
                <span className={styles.panelDotGreen} />
                {t("channels.enabledSection")}
                <span className={styles.panelCount}>
                  {t("channels.enabledCount", { count: enabledCards.length })}
                </span>
              </div>

              {enabledCards.length > 0 ? (
                <div className={styles.channelsGrid}>
                  {enabledCards.map(({ key, config }, index) => (
                    <Cascade key={key} index={index}>
                      <ChannelCard
                        channelKey={key}
                        config={config}
                        iconUrl={channelSchemas[key]?.icon}
                        onClick={() => handleCardClick(key)}
                      />
                    </Cascade>
                  ))}
                </div>
              ) : (
                <div className={styles.emptyConfigured}>
                  <p>{t("channels.noEnabledChannels")}</p>
                  {disabledCards.length > 0 && (
                    <Button
                      type="primary"
                      onClick={() => {
                        document
                          .getElementById("available-channels")
                          ?.scrollIntoView({ behavior: "smooth" });
                      }}
                    >
                      {t("channels.goEnableChannels")}
                    </Button>
                  )}
                </div>
              )}
            </div>

            {/* Available Channels Section */}
            {disabledCards.length > 0 && (
              <div
                id="available-channels"
                className={styles.panelSectionDashed}
              >
                <div className={styles.panelTitle}>
                  <span className={styles.panelDotGray} />
                  {t("channels.availableSection")}
                </div>
                <div className={styles.availableGrid}>
                  {disabledCards.map(({ key }) => (
                    <ChannelAvailableItem
                      key={key}
                      channelKey={key}
                      iconUrl={channelSchemas[key]?.icon}
                      onClick={() => handleCardClick(key)}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
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
        channelSchema={activeKey ? channelSchemas[activeKey] : undefined}
        channelSchemaLoading={
          schemasLoading || (!!activeKey && !channelSchemas[activeKey])
        }
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
        onSubmitSnapshot={handleSubmitSnapshot}
        onRuntimeChange={fetchChannels}
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
