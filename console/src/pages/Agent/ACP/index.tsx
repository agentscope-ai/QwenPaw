import {
  Bot,
  Cable,
  ArrowRight,
  Wrench,
  Plus,
  SlidersHorizontal,
  Search,
} from "lucide-react";
import { Input, Segmented, Empty } from "antd";
import InlineHelp from "@/components/InlineHelp";
import NumberFlow from "@number-flow/react";
import { SharedModal } from "@/components/interaction/SharedModal";
import { Cascade } from "@/components/interaction/Cascade";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { Button, Form, Modal, Select } from "@agentscope-ai/design";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import api from "../../../api";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES,
  type ACPAgentConfig,
  type ACPConfig,
  type ACPNodeRuntimeCandidate,
  type ACPNodeRuntimeStatus,
} from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";
import { isDesktopTauriRuntime } from "../../../utils/openExternalLink";
import { parseErrorDetail } from "../../../utils/error";
import { ACPCard } from "./components/ACPCard";
import { ACPDrawer } from "./components/ACPDrawer";
import {
  parseArgsText,
  parseEnvText,
  stringifyArgs,
  stringifyEnv,
} from "./components/acpFormValues";
import styles from "../../Control/Channels/index.module.less";
import stylesACP from "./index.module.less";

const BUILTIN_ACP_ORDER = [
  "opencode",
  "qwen_code",
  "claude_code",
  "codex",
] as const;
const OTHER_NODE_VALUE = "__other_node__";
const NODE_RUNTIME_LABEL_KEYS: Record<string, string> = {
  bundled: "acp.nodeRuntime.bundled",
  system: "acp.nodeRuntime.system",
  custom: "acp.nodeRuntime.custom",
};
const NODE_RUNTIME_REASON_KEYS: Record<string, string> = {
  node_missing: "acp.nodeRuntimeReason.nodeMissing",
  npx_missing: "acp.nodeRuntimeReason.npxMissing",
  system_node_missing: "acp.nodeRuntimeReason.systemNodeMissing",
  version_check_failed: "acp.nodeRuntimeReason.versionCheckFailed",
};

function isBuiltinACPAgent(key: string): boolean {
  return BUILTIN_ACP_ORDER.includes(key as (typeof BUILTIN_ACP_ORDER)[number]);
}

type FilterType = "all" | "builtin" | "custom";

function formatNodeOption(
  candidate: ACPNodeRuntimeCandidate,
  t: TFunction,
): string {
  const label = t(
    NODE_RUNTIME_LABEL_KEYS[candidate.key] || NODE_RUNTIME_LABEL_KEYS.custom,
  );
  const version = candidate.node_version ? ` (${candidate.node_version})` : "";
  const reason = formatNodeReason(candidate.reason_code, t);
  const detail = candidate.available
    ? candidate.node_path
    : [candidate.node_path, reason].filter(Boolean).join(" - ");
  return `${label}${version}${detail ? `  ${detail}` : ""}`;
}

function formatNodeReason(reasonCode: string, t: TFunction): string {
  return t(
    NODE_RUNTIME_REASON_KEYS[reasonCode] || "acp.nodeRuntimeReason.unavailable",
  );
}

function getNodeRuntimeErrorMessage(error: unknown, t: TFunction): string {
  const detail = parseNodeRuntimeErrorDetail(error);
  const reasonCode =
    typeof detail?.reason_code === "string" ? detail.reason_code : "";
  const reasonKey = NODE_RUNTIME_REASON_KEYS[reasonCode];
  return reasonKey ? t(reasonKey) : t("acp.nodeSaveFailed");
}

function parseNodeRuntimeErrorDetail(
  error: unknown,
): Record<string, unknown> | null {
  if (error instanceof Error) {
    const idx = error.message.lastIndexOf(" - ");
    if (idx !== -1) {
      try {
        const parsed = JSON.parse(error.message.slice(idx + 3)) as {
          detail?: unknown;
        };
        if (typeof parsed.detail === "object" && parsed.detail !== null) {
          return parsed.detail as Record<string, unknown>;
        }
      } catch {
        // Fall through to the shared parser below.
      }
    }
  }
  return parseErrorDetail(error);
}

function sameNodePath(left: string, right: string): boolean {
  if (!left || !right) return false;
  const normalize = (value: string) =>
    value.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  return normalize(left) === normalize(right);
}

function getSelectedNodeValue(
  status: ACPNodeRuntimeStatus | null,
): string | undefined {
  if (!status) return undefined;
  if (status.node_path) {
    const configured = status.candidates.find(
      (candidate) =>
        sameNodePath(candidate.node_path, status.node_path) ||
        candidate.key === "custom",
    );
    return configured?.node_path || status.node_path;
  }
  return status.effective_node_path || undefined;
}

type ACPMutationOwner = {
  agentId: string;
  generation: number;
};

function ACPPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const [agents, setAgents] = useState<Record<string, ACPAgentConfig>>({});
  const [loadedConfig, setLoadedConfig] = useState<ACPConfig | null>(null);
  const [loadedConfigOwner, setLoadedConfigOwner] = useState<string | null>(
    null,
  );
  const [pageAgent, setPageAgent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [filter, setFilter] = useState<FilterType>("all");
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const surfacePrefix = useId();
  const [drawerSurface, setDrawerSurface] = useState<string>();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [isCreateMode, setIsCreateMode] = useState(false);
  const [nodeModalOpen, setNodeModalOpen] = useState(false);
  const [nodeRuntime, setNodeRuntime] = useState<ACPNodeRuntimeStatus | null>(
    null,
  );
  const [nodeRuntimeLoading, setNodeRuntimeLoading] = useState(false);
  const [nodeRuntimeSaving, setNodeRuntimeSaving] = useState(false);
  const [form] = Form.useForm<Record<string, unknown>>();
  const requestSequence = useRef(0);
  const nodeRequestSequence = useRef(0);

  const fetchACP = useCallback(async (requestedAgent: string) => {
    const requestId = ++requestSequence.current;
    const requestIsCurrent = () =>
      requestId === requestSequence.current &&
      useAgentStore.getState().selectedAgent === requestedAgent;
    if (!requestIsCurrent()) return;
    setLoading(true);
    setLoadError(false);
    setLoadedConfig(null);
    setLoadedConfigOwner(null);
    setPageAgent(requestedAgent);
    setAgents({});
    setNodeRuntime(null);
    setNodeRuntimeLoading(false);
    setNodeRuntimeSaving(false);
    setSaving(false);
    setDrawerOpen(false);
    setNodeModalOpen(false);
    setActiveKey(null);
    try {
      const data = await api.getACPConfig(requestedAgent);
      if (!data?.agents) throw new Error("Invalid ACP config response");
      if (!requestIsCurrent()) return;
      setLoadedConfig(data);
      setLoadedConfigOwner(requestedAgent);
      setAgents(data.agents);
    } catch (error) {
      if (!requestIsCurrent()) return;
      console.error("❌ Failed to load ACP config:", error);
      setLoadError(true);
    } finally {
      if (requestIsCurrent()) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchACP(selectedAgent);
  }, [fetchACP, selectedAgent]);

  useEffect(
    () => () => {
      requestSequence.current += 1;
      nodeRequestSequence.current += 1;
    },
    [],
  );

  const ownerIsCurrent = useCallback(
    (owner: ACPMutationOwner) =>
      requestSequence.current === owner.generation &&
      loadedConfigOwner === owner.agentId &&
      useAgentStore.getState().selectedAgent === owner.agentId,
    [loadedConfigOwner],
  );

  const getWritableOwner = useCallback(() => {
    const currentAgent = useAgentStore.getState().selectedAgent;
    if (!loadedConfig || loadedConfigOwner !== currentAgent) {
      void fetchACP(currentAgent);
      return null;
    }
    return {
      agentId: currentAgent,
      generation: requestSequence.current,
    };
  }, [fetchACP, loadedConfig, loadedConfigOwner]);

  const fetchNodeRuntime = useCallback(
    async (owner: ACPMutationOwner) => {
      const requestId = ++nodeRequestSequence.current;
      const requestIsCurrent = () =>
        requestId === nodeRequestSequence.current && ownerIsCurrent(owner);
      if (!requestIsCurrent()) return;
      setNodeRuntimeLoading(true);
      try {
        const status = await api.getACPNodeRuntime(owner.agentId);
        if (requestIsCurrent()) setNodeRuntime(status);
      } catch (error) {
        if (!requestIsCurrent()) return;
        console.error("Failed to load ACP Node runtime:", error);
        message.error(t("acp.nodeLoadFailed"));
      } finally {
        if (requestIsCurrent()) setNodeRuntimeLoading(false);
      }
    },
    [message, ownerIsCurrent, t],
  );

  const orderedKeys = useMemo(() => {
    const keys = Object.keys(agents);
    return [
      ...BUILTIN_ACP_ORDER.filter((key) => keys.includes(key)),
      ...keys
        .filter((key) => !isBuiltinACPAgent(key))
        .sort((left, right) => left.localeCompare(right)),
    ];
  }, [agents]);

  const [search, setSearch] = useState("");
  const cards = useMemo(() => {
    const enabledCards: { key: string; config: ACPAgentConfig }[] = [];
    const disabledCards: { key: string; config: ACPAgentConfig }[] = [];

    orderedKeys.forEach((key) => {
      const config = agents[key];
      if (!config) return;
      if (
        search &&
        !`${key} ${config.command}`.toLowerCase().includes(search.toLowerCase())
      )
        return;

      const builtin = isBuiltinACPAgent(key);
      if (filter === "builtin" && !builtin) return;
      if (filter === "custom" && builtin) return;

      if (config.enabled) {
        enabledCards.push({ key, config });
      } else {
        disabledCards.push({ key, config });
      }
    });

    return [...enabledCards, ...disabledCards];
  }, [agents, orderedKeys, filter, search]);

  const nodeOptions = useMemo(
    () => [
      ...(nodeRuntime?.candidates || []).map((candidate) => ({
        label: formatNodeOption(candidate, t),
        value: candidate.node_path || `__missing_${candidate.key}`,
        disabled: !candidate.available,
      })),
      {
        label: t("acp.chooseOtherNode"),
        value: OTHER_NODE_VALUE,
      },
    ],
    [nodeRuntime, t],
  );

  const selectedNodeValue = useMemo(
    () => getSelectedNodeValue(nodeRuntime),
    [nodeRuntime],
  );

  const pickNodePath = useCallback(async () => {
    if (isDesktopTauriRuntime()) {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({
        multiple: false,
        directory: false,
        title: t("acp.selectNodePath"),
      });
      if (Array.isArray(selected)) return selected[0] || null;
      return selected || null;
    }

    const value = window.prompt(
      t("acp.nodePathPrompt"),
      nodeRuntime?.effective_node_path || "",
    );
    return value?.trim() || null;
  }, [nodeRuntime?.effective_node_path, t]);

  const saveNodePath = useCallback(
    async (value: string) => {
      const ownerAgent = getWritableOwner();
      if (!ownerAgent) return;
      let nodePath = value;
      if (nodePath === OTHER_NODE_VALUE) {
        const selected = await pickNodePath();
        if (!selected) return;
        nodePath = selected;
      }
      if (!ownerIsCurrent(ownerAgent)) {
        void fetchACP(useAgentStore.getState().selectedAgent);
        return;
      }

      setNodeRuntimeSaving(true);
      try {
        const status = await api.updateACPNodeRuntime(
          { node_path: nodePath },
          ownerAgent.agentId,
        );
        if (!ownerIsCurrent(ownerAgent)) return;
        setNodeRuntime(status);
        setLoadedConfig((current) =>
          current ? { ...current, node_path: status.node_path } : current,
        );
        message.success(t("acp.nodeSaved"));
      } catch (error) {
        if (!ownerIsCurrent(ownerAgent)) return;
        console.error("Failed to update ACP Node runtime:", error);
        message.error(getNodeRuntimeErrorMessage(error, t));
        void fetchNodeRuntime(ownerAgent);
      } finally {
        if (ownerIsCurrent(ownerAgent)) setNodeRuntimeSaving(false);
      }
    },
    [
      fetchACP,
      fetchNodeRuntime,
      getWritableOwner,
      message,
      ownerIsCurrent,
      pickNodePath,
      t,
    ],
  );

  const handleNodeSettingsClick = () => {
    const ownerAgent = getWritableOwner();
    if (!ownerAgent) return;
    setNodeModalOpen(true);
    void fetchNodeRuntime(ownerAgent);
  };

  const handleCardClick = (key: string) => {
    if (!getWritableOwner()) return;
    setDrawerSurface(`${surfacePrefix}:${key}`);
    const config = agents[key];
    setIsCreateMode(false);
    setActiveKey(key);
    setDrawerOpen(true);
    form.resetFields();
    form.setFieldsValue({
      ...config,
      agentKey: key,
      argsText: stringifyArgs(config?.args),
      envText: stringifyEnv(config?.env),
      stdio_buffer_limit_bytes:
        config?.stdio_buffer_limit_bytes ??
        ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES,
    });
  };

  const handleCreateClick = () => {
    if (!getWritableOwner()) return;
    setDrawerSurface(undefined);
    setIsCreateMode(true);
    setActiveKey(null);
    setDrawerOpen(true);
    form.resetFields();
    form.setFieldsValue({
      agentKey: "",
      enabled: true,
      command: "",
      argsText: "",
      envText: "",
      trusted: true,
      tool_parse_mode: "call_title",
      stdio_buffer_limit_bytes: ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES,
    });
  };

  const handleClose = () => {
    setDrawerOpen(false);
  };

  const handleSubmit = async (values: Record<string, unknown>) => {
    const ownerAgent = getWritableOwner();
    if (!loadedConfig || !ownerAgent) return false;
    const targetKey = String(values.agentKey || activeKey || "").trim();
    if (!targetKey) return false;
    const existingConfig: Partial<ACPAgentConfig> =
      (!isCreateMode && activeKey ? agents[activeKey] : undefined) || {};

    if ((isCreateMode || targetKey !== activeKey) && agents[targetKey]) {
      message.error(t("acp.agentKeyExists"));
      return false;
    }

    const updatedConfig: ACPAgentConfig = {
      ...existingConfig,
      enabled: Boolean(values.enabled),
      command: String(values.command || ""),
      args: parseArgsText(values.argsText),
      env: parseEnvText(values.envText),
      trusted: Boolean(values.trusted),
      tool_parse_mode: (values.tool_parse_mode ||
        "call_title") as ACPAgentConfig["tool_parse_mode"],
      stdio_buffer_limit_bytes: Number(
        values.stdio_buffer_limit_bytes ??
          existingConfig.stdio_buffer_limit_bytes ??
          ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES,
      ),
    };

    setSaving(true);
    try {
      if (isCreateMode || targetKey !== activeKey) {
        const nextAgents = { ...agents };
        if (!isCreateMode && activeKey) {
          delete nextAgents[activeKey];
        }
        nextAgents[targetKey] = updatedConfig;
        const nextConfig = { ...loadedConfig, agents: nextAgents };
        const savedConfig = await api.updateACPConfig(
          nextConfig,
          ownerAgent.agentId,
        );
        if (!ownerIsCurrent(ownerAgent)) return false;
        setLoadedConfig(savedConfig || nextConfig);
      } else {
        await api.updateACPAgentConfig(
          targetKey,
          updatedConfig,
          ownerAgent.agentId,
        );
        if (!ownerIsCurrent(ownerAgent)) return false;
        setLoadedConfig((current) =>
          current
            ? {
                ...current,
                agents: {
                  ...current.agents,
                  [targetKey]: updatedConfig,
                },
              }
            : current,
        );
      }
      setAgents((current) => {
        const next = { ...current };
        if (activeKey && activeKey !== targetKey) delete next[activeKey];
        next[targetKey] = updatedConfig;
        return next;
      });
      if (isCreateMode) {
        setDrawerOpen(false);
        message.success(t("acp.createSuccess"));
      } else {
        setActiveKey(targetKey);
      }
    } catch (error) {
      if (!ownerIsCurrent(ownerAgent)) return false;
      console.error("❌ Failed to update ACP config:", error);
      if (!isCreateMode) throw error;
      message.error(t("acp.configFailed"));
    } finally {
      if (ownerIsCurrent(ownerAgent)) setSaving(false);
    }
  };

  const handleDelete = () => {
    const ownerAgent = getWritableOwner();
    if (
      !loadedConfig ||
      !ownerAgent ||
      !activeKey ||
      isBuiltinACPAgent(activeKey)
    )
      return;

    Modal.confirm({
      title: t("acp.deleteTitle", { name: activeKey }),
      content: t("acp.deleteConfirm"),
      okText: t("common.delete"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      async onOk() {
        if (!ownerIsCurrent(ownerAgent)) {
          void fetchACP(useAgentStore.getState().selectedAgent);
          return;
        }
        try {
          const nextAgents = { ...agents };
          delete nextAgents[activeKey];
          const nextConfig = { ...loadedConfig, agents: nextAgents };
          const savedConfig = await api.updateACPConfig(
            nextConfig,
            ownerAgent.agentId,
          );
          if (!ownerIsCurrent(ownerAgent)) return;
          setLoadedConfig(savedConfig || nextConfig);
          await fetchACP(ownerAgent.agentId);
          handleClose();
          message.success(t("acp.deleteSuccess"));
        } catch (error) {
          if (!ownerIsCurrent(ownerAgent)) return;
          console.error("❌ Failed to delete ACP config:", error);
          message.error(t("acp.deleteFailed"));
          throw error;
        }
      },
    });
  };

  const FILTER_TABS: { key: FilterType; label: string }[] = [
    { key: "all", label: t("common.all", { defaultValue: "All" }) },
    { key: "builtin", label: t("acp.builtin") },
    { key: "custom", label: t("acp.custom") },
  ];

  const renderPageHeader = (showActions: boolean) => (
    <PageHeader
      className={stylesACP.pageHeader}
      current={t("acp.title")}
      afterBreadcrumb={
        <InlineHelp>{`${t("acp.intro")} ${t("acp.protocolHelp")}`}</InlineHelp>
      }
      extra={
        showActions ? (
          <div className={stylesACP.headerActions}>
            <Button
              icon={<SlidersHorizontal size={16} />}
              onClick={handleNodeSettingsClick}
            >
              {t("acp.nodeSettings")}
            </Button>
            <Button
              type="primary"
              icon={<Plus size={16} />}
              onClick={handleCreateClick}
            >
              {t("acp.create")}
            </Button>
          </div>
        ) : undefined
      }
    />
  );

  const waitingForCurrentAgent =
    pageAgent !== selectedAgent ||
    loading ||
    (!loadError && (!loadedConfig || loadedConfigOwner !== selectedAgent));

  if (waitingForCurrentAgent) {
    return (
      <div className={styles.channelsPage}>
        {renderPageHeader(false)}
        <div className={styles.loading} role="status">
          <span className={styles.loadingText}>{t("acp.loading")}</span>
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className={styles.channelsPage}>
        {renderPageHeader(false)}
        <div className={stylesACP.loadError} role="alert">
          <span>{t("acp.loadError")}</span>
          <Button type="primary" onClick={() => void fetchACP(selectedAgent)}>
            {t("common.retry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.channelsPage}>
      {renderPageHeader(true)}
      <section className={stylesACP.intro}>
        <div className={stylesACP.connection} aria-label={t("acp.intro")}>
          <span>
            <Bot size={18} />
            {t("acp.currentAgent")}
          </span>
          <ArrowRight size={16} aria-hidden />
          <span className={stylesACP.protocol}>
            <Cable size={20} />
            ACP
          </span>
          <ArrowRight size={16} aria-hidden />
          <span>
            <Wrench size={18} />
            {t("acp.callableTools")}
          </span>
        </div>
        <div className={stylesACP.metric}>
          <NumberFlow
            value={Object.values(agents).filter((item) => item.enabled).length}
            respectMotionPreference
          />
          <span>{t("acp.enabledIntegrations")}</span>
        </div>
      </section>
      <div className={stylesACP.collectionControls}>
        <Segmented
          value={filter}
          onChange={(value) => setFilter(value as FilterType)}
          options={FILTER_TABS.map((item) => ({
            value: item.key,
            label: item.label,
          }))}
        />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          allowClear
          prefix={<Search size={16} />}
          placeholder={t("acp.search")}
          aria-label={t("acp.search")}
        />
      </div>
      <div className={styles.channelsContainer}>
        {loading ? (
          <div className={styles.loading}>
            <span className={styles.loadingText}>{t("acp.loading")}</span>
          </div>
        ) : (
          <div
            className={`${styles.channelsGrid} ${stylesACP.channelsGridMobile}`}
          >
            {!cards.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
            {cards.map(({ key, config }, index) => (
              <Cascade key={key} index={index}>
                <ACPCard
                  surfaceId={`${surfacePrefix}:${key}`}
                  agentKey={key}
                  config={config}
                  isBuiltin={isBuiltinACPAgent(key)}
                  onClick={() => handleCardClick(key)}
                  onToggle={async () => {
                    const ownerAgent = getWritableOwner();
                    if (!ownerAgent) return;
                    try {
                      await api.updateACPAgentConfig(
                        key,
                        {
                          ...config,
                          enabled: !config.enabled,
                        },
                        ownerAgent.agentId,
                      );
                      if (!ownerIsCurrent(ownerAgent)) return;
                      setAgents((current) => ({
                        ...current,
                        [key]: { ...current[key], enabled: !config.enabled },
                      }));
                    } catch {
                      if (!ownerIsCurrent(ownerAgent)) return;
                      message.error(t("acp.configFailed"));
                    }
                  }}
                />
              </Cascade>
            ))}
          </div>
        )}
      </div>
      <ACPDrawer
        surfaceId={drawerSurface}
        open={drawerOpen}
        activeKey={activeKey}
        isCreateMode={isCreateMode}
        form={form}
        saving={saving}
        initialValues={activeKey ? agents[activeKey] : undefined}
        canEditKey={isCreateMode || !isBuiltinACPAgent(activeKey || "")}
        canDelete={!isCreateMode && !isBuiltinACPAgent(activeKey || "")}
        onClose={handleClose}
        onSubmit={handleSubmit}
        onDelete={handleDelete}
      />
      <SharedModal
        title={t("acp.nodeSettings")}
        open={nodeModalOpen}
        onCancel={() => setNodeModalOpen(false)}
        footer={null}
        destroyOnHidden
      >
        <div className={stylesACP.nodeSettings}>
          <label className={stylesACP.nodeLabel}>{t("acp.nodePath")}</label>
          <Select
            value={selectedNodeValue}
            options={nodeOptions}
            loading={nodeRuntimeLoading || nodeRuntimeSaving}
            onChange={(value) => saveNodePath(String(value))}
            placeholder={t("acp.nodePath")}
            style={{ width: "100%" }}
          />
        </div>
      </SharedModal>
    </div>
  );
}

export default ACPPage;
