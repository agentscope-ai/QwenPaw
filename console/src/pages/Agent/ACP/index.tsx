import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Form, Modal, Select } from "@agentscope-ai/design";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import api from "../../../api";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES,
  type ACPAgentConfig,
  type ACPNodeRuntimeCandidate,
  type ACPNodeRuntimeStatus,
} from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";
import { isDesktopTauriRuntime } from "../../../utils/openExternalLink";
import { parseErrorDetail } from "../../../utils/error";
import { ACPCard } from "./components/ACPCard";
import {
  ACPDrawer,
  parseArgsText,
  parseEnvText,
  stringifyArgs,
  stringifyEnv,
} from "./components/ACPDrawer";
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

function ACPPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const [agents, setAgents] = useState<Record<string, ACPAgentConfig>>({});
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterType>("all");
  const [activeKey, setActiveKey] = useState<string | null>(null);
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

  const fetchACP = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getACPConfig();
      setAgents(data?.agents || {});
    } catch (error) {
      console.error("❌ Failed to load ACP config:", error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchACP();
  }, [fetchACP, selectedAgent]);

  const fetchNodeRuntime = useCallback(async () => {
    setNodeRuntimeLoading(true);
    try {
      setNodeRuntime(await api.getACPNodeRuntime());
    } catch (error) {
      console.error("Failed to load ACP Node runtime:", error);
      message.error(t("acp.nodeLoadFailed"));
    } finally {
      setNodeRuntimeLoading(false);
    }
  }, [message, t]);

  const orderedKeys = useMemo(() => {
    const keys = Object.keys(agents);
    return [
      ...BUILTIN_ACP_ORDER.filter((key) => keys.includes(key)),
      ...keys
        .filter((key) => !isBuiltinACPAgent(key))
        .sort((left, right) => left.localeCompare(right)),
    ];
  }, [agents]);

  const cards = useMemo(() => {
    const enabledCards: { key: string; config: ACPAgentConfig }[] = [];
    const disabledCards: { key: string; config: ACPAgentConfig }[] = [];

    orderedKeys.forEach((key) => {
      const config = agents[key];
      if (!config) return;

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
  }, [agents, orderedKeys, filter]);

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
      let nodePath = value;
      if (nodePath === OTHER_NODE_VALUE) {
        const selected = await pickNodePath();
        if (!selected) return;
        nodePath = selected;
      }

      setNodeRuntimeSaving(true);
      try {
        setNodeRuntime(await api.updateACPNodeRuntime({ node_path: nodePath }));
        message.success(t("acp.nodeSaved"));
      } catch (error) {
        console.error("Failed to update ACP Node runtime:", error);
        message.error(getNodeRuntimeErrorMessage(error, t));
        void fetchNodeRuntime();
      } finally {
        setNodeRuntimeSaving(false);
      }
    },
    [fetchNodeRuntime, message, pickNodePath, t],
  );

  const handleNodeSettingsClick = () => {
    setNodeModalOpen(true);
    void fetchNodeRuntime();
  };

  const handleCardClick = (key: string) => {
    const config = agents[key];
    setIsCreateMode(false);
    setActiveKey(key);
    setDrawerOpen(true);
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
    setActiveKey(null);
    setIsCreateMode(false);
    form.resetFields();
  };

  const handleSubmit = async (values: Record<string, unknown>) => {
    const targetKey = String(values.agentKey || activeKey || "").trim();
    if (!targetKey) return;
    const existingConfig: Partial<ACPAgentConfig> =
      (!isCreateMode && activeKey ? agents[activeKey] : undefined) || {};

    if ((isCreateMode || targetKey !== activeKey) && agents[targetKey]) {
      message.error(t("acp.agentKeyExists"));
      return;
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
        await api.updateACPConfig({ agents: nextAgents });
      } else {
        await api.updateACPAgentConfig(targetKey, updatedConfig);
      }
      await fetchACP();
      setDrawerOpen(false);
      message.success(
        isCreateMode ? t("acp.createSuccess") : t("acp.configSaved"),
      );
    } catch (error) {
      console.error("❌ Failed to update ACP config:", error);
      message.error(t("acp.configFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = () => {
    if (!activeKey || isBuiltinACPAgent(activeKey)) return;

    Modal.confirm({
      title: t("acp.deleteTitle", { name: activeKey }),
      content: t("acp.deleteConfirm"),
      okText: t("common.delete"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      async onOk() {
        try {
          const nextAgents = { ...agents };
          delete nextAgents[activeKey];
          await api.updateACPConfig({ agents: nextAgents });
          await fetchACP();
          handleClose();
          message.success(t("acp.deleteSuccess"));
        } catch (error) {
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

  return (
    <div className={styles.channelsPage}>
      <PageHeader
        className={stylesACP.pageHeader}
        items={[{ title: t("nav.agent") }, { title: t("acp.title") }]}
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
        extra={
          <div className={stylesACP.headerActions}>
            <Button onClick={handleNodeSettingsClick}>
              {t("acp.nodeSettings")}
            </Button>
            <Button type="primary" onClick={handleCreateClick}>
              {t("acp.create")}
            </Button>
          </div>
        }
      />
      <div className={styles.channelsContainer}>
        {loading ? (
          <div className={styles.loading}>
            <span className={styles.loadingText}>{t("acp.loading")}</span>
          </div>
        ) : (
          <div
            className={`${styles.channelsGrid} ${stylesACP.channelsGridMobile}`}
          >
            {cards.map(({ key, config }) => (
              <ACPCard
                key={key}
                agentKey={key}
                config={config}
                isBuiltin={isBuiltinACPAgent(key)}
                onClick={() => handleCardClick(key)}
              />
            ))}
          </div>
        )}
      </div>
      <ACPDrawer
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
      <Modal
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
      </Modal>
    </div>
  );
}

export default ACPPage;
