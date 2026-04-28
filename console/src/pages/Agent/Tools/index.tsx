import { useMemo, useState } from "react";
import {
  Card,
  Switch,
  Empty,
  Button,
  Modal,
  Form,
  Input,
  message as antdMessage,
} from "@agentscope-ai/design";
import {
  EyeOutlined,
  EyeInvisibleOutlined,
  ThunderboltOutlined,
  ClockCircleOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { useTools } from "./useTools";
import { useTranslation } from "react-i18next";
import type { ToolInfo } from "../../../api/modules/tools";
import { PageHeader } from "@/components/PageHeader";
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
  onSave: (values: Record<string, any>) => Promise<void>;
}) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const { t } = useTranslation();

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await onSave(values);
      antdMessage.success(t("tools.configSaved"));
      onClose();
    } catch (error) {
      console.error("Failed to save config:", error);
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
      confirmLoading={saving}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={tool.config_values || {}}
      >
        {tool.config_fields?.map((field) => (
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
          >
            {field.type === "password" ? (
              <Input.Password
                placeholder={field.placeholder}
                autoComplete="off"
              />
            ) : (
              <Input type={field.type} placeholder={field.placeholder} />
            )}
          </Form.Item>
        ))}
      </Form>
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
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [currentTool, setCurrentTool] = useState<ToolInfo | null>(null);

  const handleToggle = (tool: ToolInfo) => {
    toggleEnabled(tool);
  };

  const handleConfigure = (tool: ToolInfo) => {
    setCurrentTool(tool);
    setConfigModalVisible(true);
  };

  const handleSaveConfig = async (values: Record<string, any>) => {
    if (!currentTool) return;
    await saveToolConfig(currentTool.name, values);
    await loadTools();
  };

  const hasDisabledTools = useMemo(
    () => tools.some((tool) => !tool.enabled),
    [tools],
  );
  const hasEnabledTools = useMemo(
    () => tools.some((tool) => tool.enabled),
    [tools],
  );

  return (
    <div className={styles.toolsPage}>
      <PageHeader
        items={[{ title: t("nav.agent") }, { title: t("tools.title") }]}
        extra={
          <div className={styles.headerAction}>
            <Switch
              checked={hasEnabledTools && !hasDisabledTools}
              onChange={() => (hasDisabledTools ? enableAll() : disableAll())}
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
          <div className={styles.toolsGrid}>
            {tools.map((tool) => (
              <Card
                key={tool.name}
                className={`${styles.toolCard} ${
                  tool.enabled ? styles.enabledCard : ""
                }`}
              >
                <div className={styles.cardHeader}>
                  <h3 className={styles.toolName}>
                    <ToolIcon icon={tool.icon} name={tool.name} /> {tool.name}
                  </h3>
                  <div className={styles.statusContainer}>
                    <span className={styles.statusDot} />
                    <span className={styles.statusText}>
                      {tool.enabled
                        ? t("common.enabled")
                        : t("common.disabled")}
                    </span>
                  </div>
                </div>

                <p className={styles.toolDescription}>{tool.description}</p>

                {/* Show config status */}
                {tool.requires_config && (
                  <div className={styles.configStatus}>
                    {tool.config_values &&
                    Object.keys(tool.config_values).length > 0 ? (
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

                <div className={styles.cardFooter}>
                  {tool.name === "execute_shell_command" && (
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
                    onClick={() => handleToggle(tool)}
                    icon={
                      tool.enabled ? <EyeInvisibleOutlined /> : <EyeOutlined />
                    }
                  >
                    {tool.enabled ? t("common.disable") : t("common.enable")}
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Config modal */}
      {currentTool && (
        <ToolConfigModal
          tool={currentTool}
          visible={configModalVisible}
          onClose={() => setConfigModalVisible(false)}
          onSave={handleSaveConfig}
        />
      )}
    </div>
  );
}
