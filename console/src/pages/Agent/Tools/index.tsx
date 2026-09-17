import { useEffect, useMemo, useState } from "react";
import { Spin } from "antd";
import {
  Card,
  Switch,
  Empty,
  Button,
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
} from "@agentscope-ai/design";
import api from "../../../api";
import {
  EyeInvisibleOutlined,
  ThunderboltOutlined,
  ClockCircleOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { useTools } from "./useTools";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { ToolInfo } from "../../../api/modules/tools";
import type { ToolConfigUpdate } from "../../../api/modules/tools";
import { PageHeader } from "@/components/PageHeader";
import { buildToolConfigUpdate } from "./credentials";
import styles from "./index.module.less";

/** Stable background colours for the initial-letter fallback icon. */
const ICON_PALETTE = [
  "#f56a00",
  "#7265e6",
  "#ffbf00",
  "#00a2ae",
  "#87d068",
  "#1890ff",
  "#eb2f96",
  "#722ed1",
];

function hashStringToIndex(value: string, mod: number): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % mod;
}

/** Renders the emoji icon or a coloured initial-letter badge as fallback. */
function ToolIcon({ icon, name }: { icon: string; name: string }) {
  if (icon) {
    return <span>{icon}</span>;
  }
  const letter = name.charAt(0).toUpperCase();
  const backgroundColor =
    ICON_PALETTE[hashStringToIndex(name, ICON_PALETTE.length)];
  return (
    <span className={styles.toolIconFallback} style={{ backgroundColor }}>
      {letter}
    </span>
  );
}

const BROWSER_TOOL_NAMES = new Set(["browser"]);

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
        icon={experimental ? <ThunderboltOutlined /> : <ClockCircleOutlined />}
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
  onSave: (body: ToolConfigUpdate) => Promise<void>;
}) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
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
      .then((view) => {
        if (!cancelled) {
          const initial: Record<string, unknown> = { ...(view.config || {}) };
          for (const field of tool.config_fields || []) {
            if (field.type === "password") {
              initial[`credential_action:${field.name}`] = "keep";
            }
          }
          form.setFieldsValue(initial);
        }
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

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const actions: Record<string, "keep" | "replace" | "delete"> = {};
      const replacements: Record<string, string> = {};
      for (const field of tool.config_fields || []) {
        if (field.type !== "password") continue;
        actions[field.name] =
          values[`credential_action:${field.name}`] || "keep";
        replacements[field.name] =
          values[`credential_value:${field.name}`] || "";
      }
      const body = buildToolConfigUpdate(
        tool.config_fields || [],
        values,
        actions,
        replacements,
      );
      setSaving(true);
      await onSave(body);
      // Success message is shown in useTools.saveToolConfig
      onClose();
    } catch (error) {
      console.error("Failed to save config:", error);
      // Error is already handled and shown in useTools
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`${t("tools.configure")} - ${tool.name}`}
      open={visible}
      onCancel={onClose}
      onOk={handleSave}
      confirmLoading={saving || loadingConfig}
      okButtonProps={{ disabled: loadingConfig }}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
    >
      <Spin spinning={loadingConfig}>
        <Form form={form} layout="vertical">
          {tool.config_fields?.map((field) => {
            // Render different input types based on field type
            const renderInput = () => {
              switch (field.type) {
                case "password":
                  return (
                    <div>
                      <Form.Item
                        name={`credential_action:${field.name}`}
                        initialValue="keep"
                        noStyle
                      >
                        <Select style={{ width: "100%", marginBottom: 8 }}>
                          <Select.Option value="keep">
                            {t("tools.credentialKeep")}
                          </Select.Option>
                          <Select.Option value="replace">
                            {t("tools.credentialReplace")}
                          </Select.Option>
                          <Select.Option value="delete">
                            {t("tools.credentialDelete")}
                          </Select.Option>
                        </Select>
                      </Form.Item>
                      <Form.Item
                        noStyle
                        shouldUpdate={(previous, current) =>
                          previous[`credential_action:${field.name}`] !==
                          current[`credential_action:${field.name}`]
                        }
                      >
                        {({ getFieldValue }) =>
                          getFieldValue(`credential_action:${field.name}`) ===
                          "replace" ? (
                            <Form.Item
                              name={`credential_value:${field.name}`}
                              rules={[
                                {
                                  required: true,
                                  message: `${field.label} is required`,
                                },
                              ]}
                              noStyle
                            >
                              <Input.Password
                                placeholder={field.placeholder}
                                autoComplete="new-password"
                              />
                            </Form.Item>
                          ) : null
                        }
                      </Form.Item>
                    </div>
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
                name={field.type === "password" ? undefined : field.name}
                label={field.label}
                rules={[
                  {
                    required: field.required && field.type !== "password",
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
    readOnly,
    toggleEnabled,
    toggleAsyncExecution,
    enableAll,
    disableAll,
    loadTools,
    saveToolConfig,
  } = useTools();
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [currentTool, setCurrentTool] = useState<ToolInfo | null>(null);

  const handleConfigure = (tool: ToolInfo) => {
    setCurrentTool(tool);
    setConfigModalVisible(true);
  };

  const handleSaveConfig = async (body: ToolConfigUpdate) => {
    if (!currentTool) return;
    await saveToolConfig(currentTool.name, body);
    await loadTools();
  };

  const handleExperimentalChange = async (experimental: boolean) => {
    // Keep the switch on the Browser card even when the currently registered
    // implementation is the deprecated stable browser track.
    await saveToolConfig("browser", {
      config: { experimental },
      credential_updates: {},
    });
    await loadTools();
  };

  const { enabledTools, disabledTools } = useMemo(() => {
    const enabled = tools.filter((tool) => tool.enabled);
    const disabled = tools.filter((tool) => !tool.enabled);
    return { enabledTools: enabled, disabledTools: disabled };
  }, [tools]);

  const editableTools = useMemo(
    () => tools.filter((tool) => tool.can_edit !== false),
    [tools],
  );
  const allEditableToolsEnabled =
    editableTools.length > 0 && editableTools.every((tool) => tool.enabled);

  const isToolConfigured = (tool: ToolInfo) =>
    !tool.requires_config ||
    Object.values(tool.credential_status || {}).some(
      (status) => status === "configured",
    ) ||
    Boolean(tool.config_values && Object.keys(tool.config_values).length > 0);

  const handleAvailableItemClick = (tool: ToolInfo) => {
    if (tool.policy_locked || tool.can_edit === false) return;
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
        extra={
          readOnly ? null : (
            <div className={styles.headerAction}>
              <Switch
                checked={allEditableToolsEnabled}
                onChange={() =>
                  allEditableToolsEnabled ? disableAll() : enableAll()
                }
                disabled={batchLoading || loading}
                checkedChildren={t("tools.enableAll")}
                unCheckedChildren={t("tools.disableAll")}
              />
            </div>
          )
        }
      />
      {readOnly && (
        <div className={styles.panelSectionDashed}>
          <div className={styles.panelTitle}>{t("common.readOnly")}</div>
          <p>{t("agent.readOnlyHint")}</p>
        </div>
      )}
      <div className={styles.toolsContainer}>
        {loading ? (
          <div className={styles.loading}>
            <p>{t("common.loading")}</p>
          </div>
        ) : tools.length === 0 ? (
          <Empty description={t("tools.emptyState")} />
        ) : (
          <>
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
                  {enabledTools.map((tool) => (
                    <Card
                      key={tool.name}
                      className={`${styles.toolCard} ${styles.enabledCard}`}
                    >
                      <div className={styles.cardHeader}>
                        <h3 className={styles.toolName} title={tool.name}>
                          <ToolIcon icon={tool.icon} name={tool.name} />{" "}
                          <span className={styles.toolNameText}>
                            {tool.name}
                          </span>
                        </h3>
                        <div className={styles.statusContainer}>
                          <span className={styles.statusDot} />
                          <span className={styles.statusText}>
                            {t("common.enabled")}
                          </span>
                        </div>
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
                          {isToolConfigured(tool) ? (
                            <span className={styles.configured}>
                              ✓ {t("tools.configured")}
                            </span>
                          ) : (
                            <span className={styles.notConfigured}>
                              ⚠ {t("tools.requiresConfig")}
                            </span>
                          )}
                        </div>
                      )}

                      {!readOnly && tool.can_edit !== false && (
                        <div className={styles.cardFooter}>
                          {BROWSER_TOOL_NAMES.has(tool.name) &&
                            !tool.policy_locked && (
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
                                  <ThunderboltOutlined />
                                ) : (
                                  <ClockCircleOutlined />
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
                              icon={<SettingOutlined />}
                            >
                              {t("tools.configure")}
                            </Button>
                          )}
                          <Button
                            className={styles.toggleButton}
                            onClick={() => toggleEnabled(tool)}
                            icon={<EyeInvisibleOutlined />}
                          >
                            {t("common.disable")}
                          </Button>
                        </div>
                      )}
                    </Card>
                  ))}
                </div>
              ) : (
                <div className={styles.emptyEnabled}>
                  <p>{t("tools.noEnabled")}</p>
                  {!readOnly && (
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
                  )}
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
                  {disabledTools.map((tool) => (
                    <div
                      key={tool.name}
                      className={styles.availableItem}
                      onClick={() => {
                        if (!readOnly && !tool.policy_locked)
                          handleAvailableItemClick(tool);
                      }}
                      style={{
                        cursor:
                          readOnly || tool.policy_locked
                            ? "default"
                            : undefined,
                      }}
                    >
                      <ToolIcon icon={tool.icon} name={tool.name} />
                      <span
                        className={styles.availableItemName}
                        title={tool.name}
                      >
                        {tool.name}
                      </span>
                      {!readOnly && (
                        <span className={styles.availableItemAction}>
                          {tool.policy_locked
                            ? t("tools.browserPolicyLocked")
                            : tool.requires_config && !isToolConfigured(tool)
                            ? t("tools.configureAction")
                            : t("tools.enableAction")}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Config modal — key forces remount when switching tools */}
      {!readOnly && currentTool && (
        <ToolConfigModal
          key={currentTool.name}
          tool={currentTool}
          visible={configModalVisible}
          onClose={() => setConfigModalVisible(false)}
          onSave={handleSaveConfig}
        />
      )}
    </div>
  );
}
