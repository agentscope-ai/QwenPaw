import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Form, Modal } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import api from "../../../api";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES,
  type ACPAgentConfig,
} from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";
import { ACPCard } from "./components/ACPCard";
import {
  ACPDrawer,
  parseArgsText,
  parseEnvText,
  stringifyArgs,
  stringifyEnv,
} from "./components/ACPDrawer";
import styles from "../../Control/Channels/index.module.less";

const BUILTIN_ACP_ORDER = [
  "opencode",
  "qwen_code",
  "claude_code",
  "codex",
] as const;

function isBuiltinACPAgent(key: string): boolean {
  return BUILTIN_ACP_ORDER.includes(key as (typeof BUILTIN_ACP_ORDER)[number]);
}

type FilterType = "all" | "builtin" | "custom";

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
          <Button type="primary" onClick={handleCreateClick}>
            {t("acp.create")}
          </Button>
        }
      />
      <div className={styles.channelsContainer}>
        {loading ? (
          <div className={styles.loading}>
            <span className={styles.loadingText}>{t("acp.loading")}</span>
          </div>
        ) : (
          <div className={styles.channelsGrid}>
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
    </div>
  );
}

export default ACPPage;
