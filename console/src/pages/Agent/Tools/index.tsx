import { useAutoSave } from "@/hooks/useAutoSave";
import { SharedModal as Modal } from "@/components/interaction/SharedModal";
import { Wrench, Check, TriangleAlert, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Spin } from "antd";
import {
  Card,
  Switch,
  Empty,
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
    <div className={styles.browserModeControl}>
      <Button
        className={`${styles.toggleButton} ${styles.browserModeButton}`}
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
}: {
  tool: ToolInfo;
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
    if (!visible || !tool) return;
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
      title={`${t("tools.configure")} - ${tool.name}`}
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
  const [query, setQuery] = useState("");
  const matchesQuery = (tool: ToolInfo) =>
    `${tool.name} ${tool.description}`
      .toLowerCase()
      .includes(query.toLowerCase());
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

  return (
    <div className={styles.toolsPage}>
      <PageHeader
        items={[{ title: t("nav.agent") }, { title: t("tools.title") }]}
        center={
          <Input
            aria-label={t("tools.search", "Search tools")}
            placeholder={t("tools.search", "Search tools")}
            prefix={<Search size={16} />}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            allowClear
          />
        }
        extra={
          <div className={styles.headerAction}>
            <Switch
              checked={enabledTools.length > 0 && disabledTools.length === 0}
              onChange={() =>
                disabledTools.length > 0 ? enableAll() : disableAll()
              }
              disabled={batchLoading || loading}
              checkedChildren={t("tools.enableAll")}
              unCheckedChildren={t("tools.disableAll")}
            />
          </div>
        }
      />
      <div className={styles.toolsContainer}>
        {loading ? (
          <div className={styles.loading}>
            <p>{t("common.loading")}</p>
          </div>
        ) : tools.length === 0 ? (
          <Empty description={t("tools.emptyState")} />
        ) : (
          <>
            {!tools.some(matchesQuery) && (
              <Empty
                description={t("tools.noSearchResults", "No matching tools")}
              />
            )}
            {/* Enabled Section */}
            <div className={styles.panelSection}>
              <div className={styles.panelTitle}>
                <span className={styles.panelDotGreen} />
                {t("common.enabled")}
                <span className={styles.panelCount}>
                  {enabledTools.length} {t("tools.active")}
                </span>
              </div>

              {enabledTools.length > 0 ? (
                <div className={styles.toolsGrid}>
                  {enabledTools.filter(matchesQuery).map((tool) => (
                    <Card
                      key={tool.name}
                      className={`${styles.toolCard} ${styles.enabledCard}`}
                    >
                      <div className={styles.cardHeader}>
                        <h3 className={styles.toolName} title={tool.name}>
                          <Wrench size={18} aria-hidden="true" />{" "}
                          <span className={styles.toolNameText}>
                            {tool.name}
                          </span>
                        </h3>
                        <Switch
                          aria-label={`${t("common.enabled")} ${tool.name}`}
                          checked={tool.enabled}
                          onChange={() => toggleEnabled(tool)}
                        />
                      </div>

                      <p className={styles.toolDescription}>
                        {tool.name === "browser"
                          ? browserTrackLabel(tool, t)
                          : tool.description}
                        {tool.name === "browser" &&
                          browserRestartPending(tool) && (
                            <span
                              className={styles.browserRestartPending}
                              role="status"
                            >
                              {t("tools.browserRestartPending", {
                                mode: browserModeLabel(
                                  tool.config_values?.experimental !== false,
                                  t,
                                ),
                              })}
                            </span>
                          )}
                      </p>

                      {/* Show config status */}
                      {tool.requires_config && (
                        <div className={styles.configStatus}>
                          {tool.config_values &&
                          Object.keys(tool.config_values).length > 0 ? (
                            <span className={styles.configured}>
                              <Check size={13} aria-hidden="true" />{" "}
                              {t("tools.configured")}
                            </span>
                          ) : (
                            <span className={styles.notConfigured}>
                              <TriangleAlert size={13} aria-hidden="true" />{" "}
                              {t("tools.requiresConfig")}
                            </span>
                          )}
                        </div>
                      )}

                      <div className={styles.cardFooter}>
                        {BROWSER_TOOL_NAMES.has(tool.name) && (
                          <BrowserExperimentalToggle
                            toolName={tool.name}
                            experimental={
                              tool.config_values?.experimental !== false
                            }
                            onChange={handleExperimentalChange}
                          />
                        )}
                        {[
                          "execute_shell_command",
                          "delegate_external_agent",
                        ].includes(tool.name) && (
                          <Button
                            className={styles.toggleButton}
                            onClick={() => toggleAsyncExecution(tool)}
                            disabled={!tool.enabled}
                            icon={
                              tool.async_execution ? (
                                <ThunderboltOutlined size="1em" />
                              ) : (
                                <ClockCircleOutlined size="1em" />
                              )
                            }
                          >
                            {tool.async_execution
                              ? t("tools.asyncExecutionEnabled")
                              : t("tools.asyncExecutionDisabled")}
                          </Button>
                        )}
                        {/* Add configure button */}
                        {tool.requires_config && (
                          <Button
                            className={styles.toggleButton}
                            onClick={() => handleConfigure(tool)}
                            icon={<SettingOutlined size="1em" />}
                          >
                            {t("tools.configure")}
                          </Button>
                        )}
                        {WEBSEARCH_TOOL_NAMES.has(tool.name) && (
                          <Button
                            className={styles.toggleButton}
                            onClick={() => handleConfigure(tool)}
                            icon={<SettingOutlined size="1em" />}
                          >
                            {t("tools.configure")}
                          </Button>
                        )}
                      </div>
                    </Card>
                  ))}
                </div>
              ) : (
                <div className={styles.emptyEnabled}>
                  <p>{t("tools.noEnabled")}</p>
                  <Button
                    type="primary"
                    onClick={() => {
                      document
                        .getElementById("available-tools")
                        ?.scrollIntoView({ behavior: "smooth" });
                    }}
                  >
                    {t("tools.goEnableBtn")}
                  </Button>
                </div>
              )}
            </div>

            {/* Available Section */}
            {disabledTools.length > 0 && (
              <div id="available-tools" className={styles.panelSectionDashed}>
                <div className={styles.panelTitle}>
                  <span className={styles.panelDotGray} />
                  {t("tools.available")}
                </div>
                <div className={styles.availableGrid}>
                  {disabledTools.filter(matchesQuery).map((tool) => (
                    <div
                      key={tool.name}
                      className={styles.availableItem}
                      onClick={() => handleAvailableItemClick(tool)}
                    >
                      <Wrench size={18} aria-hidden="true" />
                      <span
                        className={styles.availableItemName}
                        title={tool.name}
                      >
                        {tool.name}
                      </span>
                      <span className={styles.availableItemAction}>
                        {tool.requires_config && !isToolConfigured(tool)
                          ? t("tools.configureAction")
                          : t("tools.enableAction")}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Config modal — key forces remount when switching tools */}
      {currentTool && WEBSEARCH_TOOL_NAMES.has(currentTool.name) ? (
        <WebSearchConfigModal
          key={currentTool.name}
          tool={currentTool}
          visible={configModalVisible}
          onClose={() => setConfigModalVisible(false)}
          onSave={handleSaveConfig}
        />
      ) : (
        currentTool && (
          <ToolConfigModal
            key={currentTool.name}
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
