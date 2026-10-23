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
import { Badge, Button, Space } from "antd";
import {
  ShieldCheck as SafetyOutlined,
  ClipboardCheck as AuditOutlined,
  RefreshCcw,
  TriangleAlert,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import {
  ChannelCard,
  ChannelFormDrawer,
  AccessControlDrawer,
  PendingApprovalsDrawer,
  useChannels,
  getChannelLabel,
  ChannelAvailableItem,
  type ChannelKey,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import {
  keepConsoleEnabled,
  normalizeChannelSubmitValues,
} from "./components/channelConfig";
import styles from "./index.module.less";

type FilterType = "all" | "builtin" | "custom";

function ChannelsPage() {
  const { t } = useTranslation();
  const { modal } = useAppMessage();
  const {
    agentId,
    channels,
    orderedKeys,
    channelSchemas,
    isBuiltin,
    loading,
    error,
    ready,
    canMutate,
    fetchChannels,
    setChannels,
  } = useChannels();
  const [filter, setFilter] = useState<FilterType>("all");
  const [saving, setSaving] = useState(false);
  const [activeKey, setActiveKey] = useState<ChannelKey | null>(null);
  const [drawerAgentId, setDrawerAgentId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [aclDrawerOpen, setAclDrawerOpen] = useState(false);
  const [aclDrawerAgentId, setAclDrawerAgentId] = useState<string | null>(null);
  const [pendingDrawerOpen, setPendingDrawerOpen] = useState(false);
  const [pendingDrawerAgentId, setPendingDrawerAgentId] = useState<
    string | null
  >(null);
  const [pendingCount, setPendingCount] = useState(0);
  const agentIdRef = useRef(agentId);
  const pendingCountRequestIdRef = useRef(0);
  const proposalIdRef = useRef(0);
  const conflictModalDestroyRef = useRef<(() => void) | null>(null);
  agentIdRef.current = agentId;

  const fetchPendingCount = useCallback(async () => {
    const ownerAgentId = agentIdRef.current;
    const requestId = ++pendingCountRequestIdRef.current;
    try {
      const data = await api.getAclAllPending();
      if (
        requestId !== pendingCountRequestIdRef.current ||
        ownerAgentId !== agentIdRef.current
      )
        return;
      setPendingCount(data.length);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    void fetchPendingCount();
  }, [agentId, fetchPendingCount]);

  useLayoutEffect(() => {
    pendingCountRequestIdRef.current += 1;
    proposalIdRef.current += 1;
    conflictModalDestroyRef.current?.();
    conflictModalDestroyRef.current = null;
    setDrawerOpen(false);
    setActiveKey(null);
    setDrawerAgentId(null);
    setAclDrawerOpen(false);
    setAclDrawerAgentId(null);
    setPendingDrawerOpen(false);
    setPendingDrawerAgentId(null);
    setPendingCount(0);
    setSaving(false);
  }, [agentId]);

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
      if (!ready) return;
      setActiveKey(key);
      setDrawerAgentId(agentId);
      setDrawerOpen(true);
    },
    [agentId, ready],
  );

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setActiveKey(null);
    setDrawerAgentId(null);
  };

  const handleSubmit = async (values: Record<string, unknown>) => {
    if (!activeKey || !drawerAgentId || !canMutate(drawerAgentId)) {
      void fetchChannels();
      return false;
    }
    const ownerAgentId = drawerAgentId;
    const channelKey = activeKey;
    const proposalId = ++proposalIdRef.current;
    conflictModalDestroyRef.current?.();
    conflictModalDestroyRef.current = null;
    const ownsProposal = () =>
      proposalIdRef.current === proposalId && canMutate(ownerAgentId);

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { isBuiltin: _isBuiltin, ...savedConfig } =
      channels[channelKey] || {};
    const updatedChannel = normalizeChannelSubmitValues(
      channelKey,
      keepConsoleEnabled(channelKey, {
        ...savedConfig,
        ...values,
      }),
    );
    const proposedConfig = updatedChannel as unknown as Parameters<
      typeof api.updateChannelConfig
    >[1];

    setSaving(true);
    try {
      if (updatedChannel.enabled === true) {
        try {
          const result = await api.checkChannelConflict(
            channelKey,
            proposedConfig,
            ownerAgentId,
          );
          if (!ownsProposal()) return;
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
                if (proposalIdRef.current === proposalId) {
                  conflictModalDestroyRef.current = null;
                }
                resolve(value && ownsProposal());
              };

              const instance = modal.confirm({
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
              conflictModalDestroyRef.current = instance.destroy;
            });
            if (!shouldSave || !ownsProposal()) return false;
          }
        } catch (error) {
          if (!ownsProposal()) return false;
          console.warn("Failed to check channel Bot conflicts:", error);
        }
      }

      if (!ownsProposal()) {
        void fetchChannels();
        return false;
      }

      await api.updateChannelConfig(channelKey, proposedConfig, ownerAgentId);
      if (!ownsProposal()) return false;
      setChannels(ownerAgentId, (current) => {
        const isBuiltin = current[channelKey]?.isBuiltin;
        return {
          ...current,
          [channelKey]: {
            ...updatedChannel,
            ...(typeof isBuiltin === "boolean" ? { isBuiltin } : {}),
          },
        };
      });
      return true;
    } catch (error) {
      if (!ownsProposal()) return false;
      console.error("Failed to update channel config:", error);
      throw error;
    } finally {
      if (proposalIdRef.current === proposalId) setSaving(false);
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
                disabled={!ready}
                onClick={() => {
                  setPendingDrawerAgentId(agentId);
                  setPendingDrawerOpen(true);
                }}
              >
                {t("channels.pendingApprovals")}
              </Button>
            </Badge>
            <Button
              icon={<SafetyOutlined size="1em" />}
              disabled={!ready}
              onClick={() => {
                setAclDrawerAgentId(agentId);
                setAclDrawerOpen(true);
              }}
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
        ) : error ? (
          <div className={styles.loadError} role="alert">
            <TriangleAlert size={24} aria-hidden="true" />
            <span>{t("channels.loadFailed")}</span>
            <Button
              icon={<RefreshCcw size={16} />}
              onClick={() => void fetchChannels()}
            >
              {t("common.retry")}
            </Button>
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
      <ChannelFormDrawer
        key={`${agentId}:${activeKey ?? "closed"}`}
        ownerKey={`${agentId}:${activeKey ?? "closed"}`}
        open={drawerOpen}
        activeKey={activeKey}
        activeLabel={activeLabel}
        saving={saving}
        initialValues={
          activeKey
            ? keepConsoleEnabled(
                activeKey,
                channels[activeKey] || { enabled: false, bot_prefix: "" },
              )
            : undefined
        }
        isBuiltin={activeKey ? isBuiltin(activeKey) : true}
        channelSchema={activeKey ? channelSchemas[activeKey] : undefined}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />
      <AccessControlDrawer
        open={aclDrawerOpen && aclDrawerAgentId !== null}
        ownerAgentId={aclDrawerAgentId}
        canMutate={canMutate}
        onStale={() => void fetchChannels()}
        onClose={() => {
          setAclDrawerOpen(false);
          setAclDrawerAgentId(null);
        }}
      />
      <PendingApprovalsDrawer
        open={pendingDrawerOpen && pendingDrawerAgentId !== null}
        ownerAgentId={pendingDrawerAgentId}
        canMutate={canMutate}
        onStale={() => void fetchChannels()}
        onClose={() => {
          setPendingDrawerOpen(false);
          setPendingDrawerAgentId(null);
          void fetchPendingCount();
        }}
      />
    </div>
  );
}

export default ChannelsPage;
