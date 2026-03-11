import { useState, useEffect, useCallback } from "react";
import {
  Drawer,
  Form,
  Input,
  Button,
  message,
  Switch,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { FormInstance } from "antd";
import type {
  SkillConfigView,
  SkillConfigUpdatePayload,
  SkillSpec,
} from "../../../../api/types";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";
import styles from "../index.module.less";

function parseFrontmatter(content: string): Record<string, string> | null {
  const trimmed = content.trim();
  if (!trimmed.startsWith("---")) return null;

  const endIndex = trimmed.indexOf("---", 3);
  if (endIndex === -1) return null;

  const frontmatterBlock = trimmed.slice(3, endIndex).trim();
  if (!frontmatterBlock) return null;

  const result: Record<string, string> = {};
  for (const line of frontmatterBlock.split("\n")) {
    const colonIndex = line.indexOf(":");
    if (colonIndex > 0) {
      const key = line.slice(0, colonIndex).trim();
      const value = line.slice(colonIndex + 1).trim();
      result[key] = value;
    }
  }
  return result;
}

type SkillDrawerFormValues = SkillSpec & {
  enabledOverride?: boolean;
  skillEnabled?: boolean;
  apiKey?: string;
  clearApiKey?: boolean;
  envJson?: string;
  configJson?: string;
};

interface SkillDrawerProps {
  open: boolean;
  editingSkill: SkillSpec | null;
  form: FormInstance<SkillDrawerFormValues>;
  onClose: () => void;
  onSubmit: (values: SkillSpec) => void;
  onSaveConfig: (
    skillName: string,
    payload: SkillConfigUpdatePayload,
  ) => Promise<boolean>;
  onLoadConfig: (skillName: string) => Promise<SkillConfigView | null>;
  savingConfig?: boolean;
  onContentChange?: (content: string) => void;
}

function parseJsonRecord(
  rawValue: string,
  fieldName: string,
): Record<string, unknown> {
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return {};
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error(`${fieldName} JSON invalid`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${fieldName} must be a JSON object`);
  }
  return parsed as Record<string, unknown>;
}

export function SkillDrawer({
  open,
  editingSkill,
  form,
  onClose,
  onSubmit,
  onSaveConfig,
  onLoadConfig,
  savingConfig = false,
  onContentChange,
}: SkillDrawerProps) {
  const { t } = useTranslation();
  const [showMarkdown, setShowMarkdown] = useState(true);
  const [contentValue, setContentValue] = useState("");
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [configLoadFailed, setConfigLoadFailed] = useState(false);

  const validateFrontmatter = useCallback(
    (_: unknown, value: string) => {
      const content = contentValue || value;
      if (!content || !content.trim()) {
        return Promise.reject(new Error(t("skills.pleaseInputContent")));
      }
      const fm = parseFrontmatter(content);
      if (!fm) {
        return Promise.reject(new Error(t("skills.frontmatterRequired")));
      }
      if (!fm.name) {
        return Promise.reject(new Error(t("skills.frontmatterNameRequired")));
      }
      if (!fm.description) {
        return Promise.reject(
          new Error(t("skills.frontmatterDescriptionRequired")),
        );
      }
      return Promise.resolve();
    },
    [contentValue, t],
  );

  useEffect(() => {
    let cancelled = false;

    const loadConfig = async () => {
      if (!editingSkill) {
        setContentValue("");
        setConfigLoadFailed(false);
        setLoadingConfig(false);
        form.resetFields();
        return;
      }

      setContentValue(editingSkill.content);
      form.setFieldsValue({
        name: editingSkill.name,
        content: editingSkill.content,
        source: editingSkill.source,
        path: editingSkill.path,
        enabledOverride:
          editingSkill.config_status?.enabled !== undefined &&
          editingSkill.config_status?.enabled !== null,
        skillEnabled:
          editingSkill.config_status?.enabled ?? editingSkill.enabled ?? false,
        apiKey: "",
        clearApiKey: false,
        envJson: "",
        configJson: "",
      });

      setLoadingConfig(true);
      setConfigLoadFailed(false);
      const configView = await onLoadConfig(editingSkill.name);
      if (cancelled) {
        setLoadingConfig(false);
        return;
      }
      if (!configView) {
        setConfigLoadFailed(true);
        setLoadingConfig(false);
        return;
      }

      form.setFieldsValue({
        enabledOverride:
          configView.enabled !== undefined && configView.enabled !== null,
        skillEnabled: configView.enabled ?? editingSkill.enabled ?? false,
        apiKey: "",
        clearApiKey: false,
        envJson: JSON.stringify(configView.env || {}, null, 2),
        configJson: JSON.stringify(configView.config || {}, null, 2),
      });
      setLoadingConfig(false);
    };

    loadConfig().catch(() => {
      if (!cancelled) {
        setConfigLoadFailed(true);
        setLoadingConfig(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [editingSkill, form, onLoadConfig]);

  const handleCreateSubmit = (values: { name: string; content: string }) => {
    onSubmit({
      ...values,
      content: contentValue || values.content,
      source: "",
      path: "",
    });
  };

  const handleSaveConfig = async () => {
    if (!editingSkill || configLoadFailed) {
      return;
    }
    try {
      const values = await form.validateFields([
        "enabledOverride",
        "skillEnabled",
        "apiKey",
        "clearApiKey",
        "envJson",
        "configJson",
      ]);

      const env = parseJsonRecord(values.envJson || "", "env");
      const config = parseJsonRecord(values.configJson || "", "config");
      const payload: SkillConfigUpdatePayload = {
        enabled: values.enabledOverride ? (values.skillEnabled ?? false) : null,
        clearApiKey: values.clearApiKey || false,
        env: Object.fromEntries(
          Object.entries(env).map(([key, value]) => [key, String(value ?? "")]),
        ),
        config,
      };
      if (values.apiKey?.trim()) {
        payload.apiKey = values.apiKey.trim();
      }

      const success = await onSaveConfig(editingSkill.name, payload);
      if (success) {
        onClose();
      }
    } catch (error) {
      if (error instanceof Error) {
        message.error(error.message);
      }
    }
  };

  const handleContentChange = (content: string) => {
    setContentValue(content);
    form.setFieldsValue({ content });
    form.validateFields(["content"]).catch(() => {});
    if (onContentChange) {
      onContentChange(content);
    }
  };

  const requirements = editingSkill?.metadata?.requires;
  const missing = editingSkill?.eligibility;

  return (
    <Drawer
      width={640}
      placement="right"
      title={editingSkill ? t("skills.viewSkill") : t("skills.createSkill")}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={!editingSkill ? handleCreateSubmit : undefined}
      >
        {!editingSkill && (
          <>
            <Form.Item
              name="name"
              label={t("skills.skillName")}
              rules={[{ required: true, message: t("skills.pleaseInputName") }]}
            >
              <Input placeholder={t("skills.skillNamePlaceholder")} />
            </Form.Item>

            <Form.Item
              name="content"
              label={t("skills.skillContent")}
              rules={[{ required: true, validator: validateFrontmatter }]}
            >
              <MarkdownCopy
                content={contentValue}
                showMarkdown={showMarkdown}
                onShowMarkdownChange={setShowMarkdown}
                editable={true}
                onContentChange={handleContentChange}
                textareaProps={{
                  placeholder: t("skills.contentPlaceholder"),
                  rows: 12,
                }}
              />
            </Form.Item>

            <Form.Item>
              <div className={styles.drawerActions}>
                <Button onClick={onClose}>{t("common.cancel")}</Button>
                <Button type="primary" htmlType="submit">
                  {t("skills.create")}
                </Button>
              </div>
            </Form.Item>
          </>
        )}

        {editingSkill && (
          <>
            <div className={styles.detailHeader}>
              <div>
                <div className={styles.detailTitle}>
                  {editingSkill.metadata?.emoji || "🧩"} {editingSkill.name}
                </div>
                <div className={styles.detailSubTitle}>
                  key: {editingSkill.resolved_skill_key || editingSkill.name}
                </div>
              </div>
              <div
                className={`${styles.eligibilityBadge} ${
                  editingSkill.eligibility?.eligible ?? true
                    ? styles.eligible
                    : styles.ineligible
                }`}
              >
                {editingSkill.eligibility?.eligible ?? true
                  ? t("skills.eligible")
                  : t("skills.ineligible")}
              </div>
            </div>

            <div className={styles.metaGrid}>
              <div className={styles.metaBlock}>
                <div className={styles.metaLabel}>{t("skills.source")}</div>
                <code className={styles.metaCode}>{editingSkill.source}</code>
              </div>
              <div className={styles.metaBlock}>
                <div className={styles.metaLabel}>{t("skills.primaryEnv")}</div>
                <code className={styles.metaCode}>
                  {editingSkill.metadata?.primary_env || "-"}
                </code>
              </div>
            </div>

            <div className={styles.metaBlock}>
              <div className={styles.metaLabel}>{t("skills.path")}</div>
              <code className={`${styles.metaCode} ${styles.metaPath}`}>
                {editingSkill.path}
              </code>
            </div>

            <div className={styles.requirementsPanel}>
              <div className={styles.sectionTitle}>
                {t("skills.requirements")}
              </div>
              <div className={styles.requirementRow}>
                <span>{t("skills.requiredEnv")}</span>
                <code>{requirements?.env?.join(", ") || "-"}</code>
              </div>
              <div className={styles.requirementRow}>
                <span>{t("skills.requiredConfig")}</span>
                <code>{requirements?.config?.join(", ") || "-"}</code>
              </div>
              <div className={styles.requirementRow}>
                <span>{t("skills.requiredBins")}</span>
                <code>{requirements?.bins?.join(", ") || "-"}</code>
              </div>
              <div className={styles.requirementRow}>
                <span>{t("skills.missing")}</span>
                <code>
                  {[
                    ...(missing?.missing_env || []),
                    ...(missing?.missing_config || []),
                    ...(missing?.missing_bins || []),
                  ].join(", ") || "-"}
                </code>
              </div>
            </div>

            <Form.Item name="content" label={t("skills.skillContent")}>
              <MarkdownCopy
                content={editingSkill.content}
                showMarkdown={showMarkdown}
                onShowMarkdownChange={setShowMarkdown}
                textareaProps={{
                  disabled: true,
                  rows: 12,
                }}
              />
            </Form.Item>

            <div className={styles.sectionTitle}>
              {t("skills.runtimeConfig")}
            </div>

            <Form.Item
              name="enabledOverride"
              label={t("skills.skillEnabledOverride")}
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>

            <Form.Item shouldUpdate noStyle>
              {({ getFieldValue }) => (
                <Form.Item
              name="skillEnabled"
              label={t("skills.skillEnabled")}
              valuePropName="checked"
            >
                  <Switch disabled={!getFieldValue("enabledOverride")} />
                </Form.Item>
              )}
            </Form.Item>

            <Form.Item
              name="apiKey"
              label={t("skills.apiKey")}
              extra={t("skills.apiKeyHint")}
            >
              <Input.Password
                placeholder={t("skills.apiKeyPlaceholder")}
                autoComplete="new-password"
              />
            </Form.Item>

            <Form.Item
              name="clearApiKey"
              label={t("skills.clearApiKey")}
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>

            <Form.Item
              name="envJson"
              label={t("skills.envConfig")}
              extra={t("skills.envConfigHint")}
            >
              <Input.TextArea
                rows={6}
                placeholder='{\n  "DEMO_REGION": "cn"\n}'
              />
            </Form.Item>

            <Form.Item
              name="configJson"
              label={t("skills.extraConfig")}
              extra={t("skills.extraConfigHint")}
            >
              <Input.TextArea
                rows={6}
                placeholder='{\n  "endpoint": "https://example.com"\n}'
              />
            </Form.Item>

            <div className={styles.hintBox}>
              {t("skills.configStatusHint", {
                envKeys: editingSkill.config_status?.env_keys.join(", ") || "-",
                configKeys:
                  editingSkill.config_status?.config_keys.join(", ") || "-",
                hasApiKey: editingSkill.config_status?.has_api_key
                  ? t("common.enabled")
                  : t("common.disabled"),
              })}
            </div>

            <div className={styles.drawerActions}>
              <Button onClick={onClose}>{t("common.cancel")}</Button>
              <Button
                type="primary"
                onClick={handleSaveConfig}
                loading={savingConfig || loadingConfig}
                disabled={configLoadFailed}
              >
                {t("common.save")}
              </Button>
            </div>
          </>
        )}
      </Form>
    </Drawer>
  );
}
