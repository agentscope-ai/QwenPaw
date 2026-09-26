import { useAutoSave } from "@/hooks/useAutoSave";
import { SharedModal as Modal } from "@/components/interaction/SharedModal";
import { CircleHelp, TriangleAlert, Search, Wrench, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Spin, Popover, Segmented } from "antd";
import {
  Switch,
  Button,
  Form,
  Input,
  InputNumber,
  Select,
} from "@agentscope-ai/design";
import api from "../../../api";
import {
  Zap as ThunderboltOutlined,
  Clock as ClockCircleOutlined,
  Settings as SettingOutlined,
} from "lucide-react";
import { useTools } from "./useTools";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { ToolInfo } from "../../../api/modules/tools";
import { PageHeader } from "@/components/PageHeader";
import { WebSearchConfigModal } from "./WebSearchConfigModal";
import styles from "./index.module.less";
import { motion, useReducedMotion } from "motion/react";
import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import { Cascade } from "@/components/interaction/Cascade";
import { TOOL_GROUPS, TOOL_PRESENTATION, toolGroup } from "./toolPresentation";

const BROWSER_TOOL_NAMES = new Set(["browser"]);
const WEBSEARCH_TOOL_NAMES = new Set(["web_search"]);

function browserModeLabel(experimental: boolean, t: TFunction): string {
  return experimental
    ? t("tools.browserUnifiedMode")
    : t("tools.browserLegacyMode");
}

function browserModeButtonLabel(experimental: boolean, t: TFunction): string {
  return experimental
    ? t("tools.browserUnifiedModeButton")
    : t("tools.browserLegacyModeButton");
}

function browserTrackLabel(tool: ToolInfo, t: TFunction): string {
  const effective = tool.config_values?.experimental_effective;
  const shown =
    effective === undefined
      ? tool.config_values?.experimental !== false
      : effective !== false;
  return shown
    ? t("tools.browserUnifiedDescription")
    : t("tools.browserLegacyDescription");
}

function browserRestartPending(tool: ToolInfo): boolean {
  const effective = tool.config_values?.experimental_effective;
  return (
    effective !== undefined &&
    (tool.config_values?.experimental !== false) !== (effective !== false)
  );
}

export function BrowserExperimentalToggle({
  toolName,
  experimental,
  onChange,
}: {
  toolName: string;
  experimental: boolean;
  onChange: (experimental: boolean) => void;
}) {
  const { t } = useTranslation();

  if (!BROWSER_TOOL_NAMES.has(toolName)) return null;

  return (
    <div>
      <Button
        data-press
        className={styles.toggleButton}
        onClick={() => onChange(!experimental)}
        icon={
          experimental ? (
            <ThunderboltOutlined size="1em" />
          ) : (
            <ClockCircleOutlined size="1em" />
          )
        }
      >
        {browserModeButtonLabel(experimental, t)}
      </Button>
    </div>
  );
}

/** Configuration modal for tools that require configuration */
function ToolConfigModal({
  tool,
  visible,
  onClose,
  onSave,
  surfaceId,
}: {
  tool: ToolInfo;
  surfaceId?: string;
  visible: boolean;
  onClose: () => void;
  onSave: (values: Record<string, unknown>) => Promise<void>;
}) {
  const [form] = Form.useForm();
  const [loadingConfig, setLoadingConfig] = useState(false);
  const { t } = useTranslation();

  // Fetch latest config from backend whenever the modal opens.
  // Cleanup cancels stale in-flight requests on rapid tool switches.
  useEffect(() => {
    if (!visible) return;
    form.resetFields();
    setLoadingConfig(true);
    let cancelled = false;
    api
      .getToolConfig(tool.name)
      .then((config) => {
        if (!cancelled) form.setFieldsValue(config || {});
      })
      .catch(() => {
        // Leave form empty on error
      })
      .finally(() => {
        if (!cancelled) setLoadingConfig(false);
      });
    return () => {
      cancelled = true;
    };
  }, [visible, tool.name, form]);

  const { schedule, flush } = useAutoSave(async () => {
    if (loadingConfig) return;
    const values = form.getFieldsValue(true);
    try {
      await form.validateFields();
    } catch {
      return false;
    }
    await onSave(values);
  });

  return (
    <Modal
      closeIcon={<X size={18} aria-hidden />}
      surfaceId={surfaceId}
      title={`${t("tools.configure")} · ${
        tool.source_plugin_id
          ? tool.name
          : t(`tools.catalog.${tool.name}.name`, tool.name)
      }`}
      open={visible}
      onCancel={() => {
        void flush().then((saved) => {
          if (saved) onClose();
        });
      }}
      footer={null}
    >
      <Spin spinning={loadingConfig}>
        <Form form={form} layout="vertical" onValuesChange={schedule}>
          {tool.config_fields?.map((field) => {
            // Render different input types based on field type
            const renderInput = () => {
              switch (field.type) {
                case "password":
                  return (
                    <Input.Password
                      placeholder={field.placeholder}
                      autoComplete="off"
                    />
                  );

                case "number":
                  return (
                    <InputNumber
                      placeholder={field.placeholder}
                      min={field.min}
                      max={field.max}
                      style={{ width: "100%" }}
                    />
                  );

                case "boolean":
                  return <Switch />;

                case "select":
                  return (
                    <Select placeholder={field.placeholder}>
                      {field.options?.map((option) => (
                        <Select.Option key={option} value={option}>
                          {option}
                        </Select.Option>
                      ))}
                    </Select>
                  );

                case "textarea":
                  return (
                    <Input.TextArea
                      placeholder={field.placeholder}
                      rows={4}
                      autoSize={{ minRows: 2, maxRows: 8 }}
                    />
                  );

                case "text":
                default:
                  return <Input placeholder={field.placeholder} />;
              }
            };

            return (
              <Form.Item
                key={field.name}
                name={field.name}
                label={field.label}
                rules={[
                  {
                    required: field.required,
                    message: `${field.label} is required`,
                  },
                ]}
                help={field.help}
                valuePropName={field.type === "boolean" ? "checked" : "value"}
              >
                {renderInput()}
              </Form.Item>
            );
          })}
        </Form>
      </Spin>
    </Modal>
  );
}

export default function ToolsPage() {
  const { t } = useTranslation();
  const instanceId = useId();
  const reducedMotion = useReducedMotion();
  const entered = useRef(false);
  const {
    tools,
    loading,
    batchLoading,
    toggleEnabled,
    toggleAsyncExecution,
    enableAll,
    disableAll,
    loadTools,
    saveToolConfig,
  } = useTools();
  useEffect(() => {
    if (tools.length > 0) entered.current = true;
  }, [tools.length]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const toolLabel = (tool: ToolInfo) =>
    tool.source_plugin_id
      ? tool.name
      : t(`tools.catalog.${tool.name}.name`, tool.name);
  const toolDescription = (tool: ToolInfo) =>
    tool.source_plugin_id
      ? tool.description
      : t(`tools.catalog.${tool.name}.description`, tool.description);
  const matchesQuery = (tool: ToolInfo) =>
    `${tool.name} ${tool.description} ${toolLabel(tool)} ${toolDescription(
      tool,
    )}`
      .toLowerCase()
      .includes(query.trim().toLowerCase());
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [currentTool, setCurrentTool] = useState<ToolInfo | null>(null);

  const handleConfigure = (tool: ToolInfo) => {
    setCurrentTool(tool);
    setConfigModalVisible(true);
  };

  const handleSaveConfig = async (values: Record<string, unknown>) => {
    if (!currentTool) return;
    await saveToolConfig(currentTool.name, values);
    await loadTools();
  };

  const handleExperimentalChange = async (experimental: boolean) => {
    // Keep the switch on the Browser card even when the currently registered
    // implementation is the deprecated stable browser track.
    await saveToolConfig("browser", { experimental });
    await loadTools();
  };

  const { enabledTools, disabledTools } = useMemo(() => {
    const enabled = tools.filter((tool) => tool.enabled);
    const disabled = tools.filter((tool) => !tool.enabled);
    return { enabledTools: enabled, disabledTools: disabled };
  }, [tools]);

  const isToolConfigured = (tool: ToolInfo) =>
    !tool.requires_config ||
    (tool.config_values && Object.keys(tool.config_values).length > 0);

  const handleAvailableItemClick = (tool: ToolInfo) => {
    if (tool.requires_config && !isToolConfigured(tool)) {
      handleConfigure(tool);
    } else {
      toggleEnabled(tool);
    }
  };

  const visibleTools = tools.filter(
    (tool) =>
      matchesQuery(tool) &&
      (filter === "all" || tool.enabled === (filter === "enabled")),
  );
  const groups = TOOL_GROUPS.map((key) => ({
    key,
    label: t(`tools.groups.${key}`),
    tools: visibleTools.filter((tool) => toolGroup(tool) === key),
  }));

  return (
    <div className={styles.toolsPage}>
      <PageHeader items={[{ title: t("tools.title") }]} />
      <div className={styles.toolsContainer}>
        <div className={styles.toolbar}>
          <Segmented
            aria-label={t("tools.title")}
            value={filter}
            onChange={(value) => setFilter(String(value))}
            options={[
              { value: "all", label: t("tools.filterAll") },
              { value: "enabled", label: t("tools.filterEnabled") },
              { value: "disabled", label: t("tools.filterDisabled") },
            ]}
          />
          <Input
            className={styles.search}
            aria-label={t("tools.search", "Search tools")}
            placeholder={t("tools.search", "Search tools")}
            prefix={<Search size={16} aria-hidden />}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className={styles.summary}>
          <span>
            {t("tools.enabledCount", {
              enabled: enabledTools.length,
              total: tools.length,
            })}
          </span>
          <div className={styles.batchActions}>
            <Button
              data-press
              disabled={batchLoading || loading || disabledTools.length === 0}
              onClick={enableAll}
            >
              {t("tools.enableAll")}
            </Button>
            <Button
              data-press
              disabled={batchLoading || loading || enabledTools.length === 0}
              onClick={disableAll}
            >
              {t("tools.disableAll")}
            </Button>
          </div>
        </div>
        {loading ? (
          <div className={styles.empty} role="status">
            <Spin />
            <span>{t("common.loading")}</span>
          </div>
        ) : tools.length === 0 || visibleTools.length === 0 ? (
          <div className={styles.empty} role="status">
            <Search size={24} aria-hidden />
            <span>
              {tools.length === 0
                ? t("tools.emptyState")
                : t("tools.noSearchResults", "No matching tools")}
            </span>
          </div>
        ) : (
          groups.map(
            (group) =>
              group.tools.length > 0 && (
                <section
                  className={styles.section}
                  key={group.label}
                  aria-label={group.label}
                >
                  <h2 className={styles.sectionTitle}>
                    {group.label}
                    <span className={styles.count}>{group.tools.length}</span>
                  </h2>
                  <div className={styles.toolList}>
                    {group.tools.map((tool, index) => {
                      const Icon = tool.source_plugin_id
                        ? Wrench
                        : TOOL_PRESENTATION[tool.name]?.Icon ?? Wrench;
                      const canConfigure =
                        tool.requires_config ||
                        WEBSEARCH_TOOL_NAMES.has(tool.name);
                      const hasActions =
                        tool.enabled &&
                        (BROWSER_TOOL_NAMES.has(tool.name) ||
                          [
                            "execute_shell_command",
                            "delegate_external_agent",
                          ].includes(tool.name));
                      return (
                        <Cascade
                          key={tool.name}
                          index={index}
                          animate={!entered.current}
                        >
                          <InteractiveCard className={styles.toolCard} tilt={2}>
                            <div className={styles.cardHeader}>
                              <span className={styles.toolIcon}>
                                <Icon
                                  size={20}
                                  strokeWidth={1.75}
                                  aria-hidden
                                />
                              </span>
                              <h3 className={styles.toolName}>
                                {toolLabel(tool)}
                              </h3>
                              <Popover
                                trigger={["hover", "focus", "click"]}
                                content={
                                  <div className={styles.helpContent}>
                                    <code>{tool.name}</code>
                                    <p>
                                      {tool.name === "browser"
                                        ? browserTrackLabel(tool, t)
                                        : toolDescription(tool)}
                                    </p>
                                  </div>
                                }
                              >
                                <button
                                  type="button"
                                  data-press
                                  className={styles.helpButton}
                                  aria-label={`${toolLabel(tool)} · ${t(
                                    "common.help",
                                  )}`}
                                >
                                  <CircleHelp
                                    size={16}
                                    strokeWidth={1.75}
                                    aria-hidden
                                  />
                                </button>
                              </Popover>
                              <span className={styles.switchTarget}>
                                <Switch
                                  aria-label={`${t(
                                    tool.enabled
                                      ? "common.disable"
                                      : "common.enable",
                                  )} ${toolLabel(tool)}`}
                                  checked={tool.enabled}
                                  disabled={batchLoading}
                                  onChange={() =>
                                    tool.enabled
                                      ? toggleEnabled(tool)
                                      : handleAvailableItemClick(tool)
                                  }
                                />
                              </span>
                            </div>
                            <p className={styles.description}>
                              {toolDescription(tool)}
                            </p>
                            {tool.name === "browser" &&
                              browserRestartPending(tool) && (
                                <span className={styles.pending} role="status">
                                  {t("tools.browserRestartPending", {
                                    mode: browserModeLabel(
                                      tool.config_values?.experimental !==
                                        false,
                                      t,
                                    ),
                                  })}
                                </span>
                              )}
                            {(canConfigure || tool.source_plugin_id) && (
                              <div className={styles.cardFooter}>
                                {tool.source_plugin_id && (
                                  <span className={styles.pluginSource}>
                                    {tool.source_plugin_name ||
                                      tool.source_plugin_id}
                                  </span>
                                )}
                                {tool.requires_config &&
                                  !isToolConfigured(tool) && (
                                    <span className={styles.notConfigured}>
                                      <TriangleAlert size={14} aria-hidden />
                                      {t("tools.requiresConfig")}
                                    </span>
                                  )}
                                <div className={styles.rowActions}>
                                  {canConfigure && (
                                    <motion.div
                                      layoutId={
                                        reducedMotion
                                          ? undefined
                                          : `${instanceId}-${tool.name}-config`
                                      }
                                      style={{
                                        borderRadius: 20,
                                        background: "var(--app-surface)",
                                      }}
                                      transition={{
                                        type: "spring",
                                        stiffness: 360,
                                        damping: 38,
                                      }}
                                    >
                                      <Button
                                        data-press
                                        className={styles.toggleButton}
                                        aria-label={`${t(
                                          "tools.configure",
                                        )} ${toolLabel(tool)}`}
                                        onClick={() => handleConfigure(tool)}
                                        icon={
                                          <SettingOutlined
                                            size={16}
                                            aria-hidden
                                          />
                                        }
                                      >
                                        {t("tools.configure")}
                                      </Button>
                                    </motion.div>
                                  )}
                                </div>
                              </div>
                            )}
                            {hasActions && (
                              <div className={styles.extraActions}>
                                {BROWSER_TOOL_NAMES.has(tool.name) ? (
                                  <BrowserExperimentalToggle
                                    toolName={tool.name}
                                    experimental={
                                      tool.config_values?.experimental !== false
                                    }
                                    onChange={handleExperimentalChange}
                                  />
                                ) : (
                                  <Button
                                    data-press
                                    className={styles.toggleButton}
                                    aria-pressed={tool.async_execution}
                                    onClick={() => toggleAsyncExecution(tool)}
                                    disabled={batchLoading}
                                    icon={
                                      <ClockCircleOutlined
                                        size={16}
                                        aria-hidden
                                      />
                                    }
                                  >
                                    {t(
                                      tool.async_execution
                                        ? "tools.asyncExecutionEnabled"
                                        : "tools.asyncExecutionDisabled",
                                    )}
                                  </Button>
                                )}
                              </div>
                            )}
                          </InteractiveCard>
                        </Cascade>
                      );
                    })}
                  </div>
                </section>
              ),
          )
        )}
      </div>

      {/* Config modal — key forces remount when switching tools */}
      {currentTool && WEBSEARCH_TOOL_NAMES.has(currentTool.name) ? (
        <WebSearchConfigModal
          key={currentTool.name}
          surfaceId={`${instanceId}-${currentTool.name}-config`}
          tool={currentTool}
          visible={configModalVisible}
          onClose={() => setConfigModalVisible(false)}
          onSave={handleSaveConfig}
        />
      ) : (
        currentTool && (
          <ToolConfigModal
            key={currentTool.name}
            surfaceId={`${instanceId}-${currentTool.name}-config`}
            tool={currentTool}
            visible={configModalVisible}
            onClose={() => setConfigModalVisible(false)}
            onSave={handleSaveConfig}
          />
        )
      )}
    </div>
  );
}
