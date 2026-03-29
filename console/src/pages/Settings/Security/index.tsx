import { useState, useCallback } from "react";
import {
  Form,
  Switch,
  Button,
  Card,
  Select,
  message,
  Tabs,
} from "@agentscope-ai/design";
import { PlusCircleOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { useToolGuard, type MergedRule } from "./useToolGuard";
import {
  PageHeader,
  RuleTable,
  RuleModal,
  PreviewModal,
  SkillScannerSection,
  FileGuardSection,
} from "./components";
import styles from "./index.module.less";

const BUILTIN_TOOLS = [
  "execute_shell_command",
  "execute_python_code",
  "browser_use",
  "desktop_screenshot",
  "view_image",
  "read_file",
  "write_file",
  "edit_file",
  "append_file",
  "view_text_file",
  "write_text_file",
  "send_file_to_user",
];

function SecurityPage() {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState("toolGuard");

  // FileGuard handlers exposed from child component
  const [fileGuardHandlers, setFileGuardHandlers] = useState<{
    save: () => Promise<void>;
    reset: () => void;
    saving: boolean;
  } | null>(null);

  const onFileGuardHandlersReady = useCallback(
    (handlers: {
      save: () => Promise<void>;
      reset: () => void;
      saving: boolean;
    }) => {
      setFileGuardHandlers(handlers);
    },
    [],
  );

  const {
    config,
    customRules,
    builtinRules,
    enabled,
    setEnabled,
    mergedRules,
    loading,
    error,
    fetchAll,
    toggleRule,
    deleteCustomRule,
    addCustomRule,
    updateCustomRule,
    buildSaveBody,
  } = useToolGuard();

  // Modal states
  const [editModal, setEditModal] = useState(false);
  const [editingRule, setEditingRule] = useState<MergedRule | null>(null);
  const [previewRule, setPreviewRule] = useState<MergedRule | null>(null);

  // Form handlers
  const handleSave = useCallback(async () => {
    try {
      setSaving(true);
      const values = await form.validateFields();
      const guardedTools: string[] = values.guarded_tools ?? [];
      const body = {
        enabled: values.enabled,
        guarded_tools: guardedTools.length > 0 ? guardedTools : null,
        denied_tools: values.denied_tools ?? [],
        custom_rules: customRules,
        disabled_rules: Array.from(buildSaveBody().disabled_rules),
      };
      await api.updateToolGuard(body);
      setEnabled(body.enabled);
      message.success(t("security.saveSuccess"));
    } catch (err) {
      if (err instanceof Error && "errorFields" in err) {
        return;
      }
      const errMsg =
        err instanceof Error ? err.message : t("security.saveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  }, [customRules, buildSaveBody, form, t]);

  const handleReset = useCallback(() => {
    form.resetFields();
    fetchAll();
  }, [form, fetchAll]);

  // Rule modal handlers
  const openAddRule = useCallback(() => {
    setEditingRule(null);
    editForm.resetFields();
    editForm.setFieldsValue({
      severity: "HIGH",
      category: "command_injection",
      tools: [],
      params: [],
      patterns: "",
      exclude_patterns: "",
    });
    setEditModal(true);
  }, [editForm]);

  const openEditRule = useCallback(
    (rule: MergedRule) => {
      setEditingRule(rule);
      editForm.setFieldsValue({
        ...rule,
        patterns: rule.patterns.join("\n"),
        exclude_patterns: rule.exclude_patterns.join("\n"),
      });
      setEditModal(true);
    },
    [editForm],
  );

  const handleEditSave = useCallback(async () => {
    try {
      const values = await editForm.validateFields();
      const patterns = (values.patterns as string)
        .split("\n")
        .map((s: string) => s.trim())
        .filter(Boolean);
      const excludePatterns = ((values.exclude_patterns as string) || "")
        .split("\n")
        .map((s: string) => s.trim())
        .filter(Boolean);

      const rule = {
        id: values.id,
        tools: values.tools ?? [],
        params: values.params ?? [],
        category: values.category,
        severity: values.severity,
        patterns,
        exclude_patterns: excludePatterns,
        description: values.description || "",
        remediation: values.remediation || "",
      };

      if (editingRule) {
        updateCustomRule(editingRule.id, rule);
      } else {
        const allIds = [
          ...builtinRules.map((r) => r.id),
          ...customRules.map((r) => r.id),
        ];
        if (allIds.includes(rule.id)) {
          message.error(t("security.rules.duplicateId"));
          return;
        }
        addCustomRule(rule);
      }
      setEditModal(false);
    } catch {
      // validation failed
    }
  }, [
    editingRule,
    builtinRules,
    customRules,
    updateCustomRule,
    addCustomRule,
    editForm,
    t,
  ]);

  const toolOptions = BUILTIN_TOOLS.map((name) => ({
    label: name,
    value: name,
  }));

  // Loading state
  if (loading) {
    return (
      <div className={styles.securityPage}>
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className={styles.securityPage}>
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>{error}</span>
          <Button size="small" onClick={fetchAll} style={{ marginTop: 12 }}>
            {t("environments.retry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.securityPage}>
      <PageHeader
        parent={t("security.parent")}
        current={t("security.security")}
      />

      <div className={styles.content}>
        <Tabs
          className={styles.mainTabs}
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "toolGuard",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.toolGuardTitle")}
                </span>
              ),
              children: (
                <div className={styles.tabContent}>
                  <div className={styles.sectionConfigureContainer}>
                    <p className={styles.tabDescription}>
                      {t("security.toolGuardDescription")}
                    </p>

                    <Card className={styles.formCard}>
                      <Form
                        form={form}
                        layout="vertical"
                        className={styles.form}
                        initialValues={{
                          enabled: config?.enabled ?? true,
                          guarded_tools: config?.guarded_tools ?? [],
                          denied_tools: config?.denied_tools ?? [],
                        }}
                      >
                        <Form.Item
                          label={t("security.enabled")}
                          name="enabled"
                          valuePropName="checked"
                          tooltip={t("security.enabledTooltip")}
                        >
                          <Switch onChange={(val) => setEnabled(val)} />
                        </Form.Item>
                      </Form>
                      <div className={styles.toolGuardRow}>
                        <Form.Item
                          label={t("security.guardedTools")}
                          name="guarded_tools"
                          tooltip={t("security.guardedToolsTooltip")}
                          style={{ marginBottom: 0 }}
                        >
                          <Select
                            mode="tags"
                            options={toolOptions}
                            placeholder={t("security.guardedToolsPlaceholder")}
                            disabled={!enabled}
                            allowClear
                            style={{ width: "100%" }}
                          />
                        </Form.Item>

                        <Form.Item
                          label={t("security.deniedTools")}
                          name="denied_tools"
                          tooltip={t("security.deniedToolsTooltip")}
                          style={{ marginBottom: 0 }}
                        >
                          <Select
                            mode="tags"
                            options={toolOptions}
                            placeholder={t("security.deniedToolsPlaceholder")}
                            disabled={!enabled}
                            allowClear
                            style={{ width: "100%" }}
                          />
                        </Form.Item>
                      </div>
                    </Card>
                  </div>

                  <div className={styles.sectionContainer}>
                    <div className={styles.sectionHeader}>
                      <h2 className={styles.sectionTitle}>
                        {t("security.rules.title")}
                      </h2>
                      <Button
                        type="primary"
                        icon={<PlusCircleOutlined />}
                        onClick={openAddRule}
                        disabled={!enabled}
                        size="middle"
                      >
                        {t("security.rules.add")}
                      </Button>
                    </div>

                    <Card className={styles.tableCard}>
                      <RuleTable
                        rules={mergedRules}
                        enabled={enabled}
                        onToggleRule={toggleRule}
                        onPreviewRule={setPreviewRule}
                        onEditRule={openEditRule}
                        onDeleteRule={deleteCustomRule}
                      />
                    </Card>
                  </div>
                </div>
              ),
            },
            {
              key: "fileGuard",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.fileGuard.title")}
                </span>
              ),
              children: (
                <div className={styles.tabContent}>
                  <div className={styles.sectionFileGuardContainer}>
                    <p className={styles.tabDescription}>
                      {t("security.fileGuard.description")}
                    </p>
                    <FileGuardSection onSave={onFileGuardHandlersReady} />
                  </div>
                </div>
              ),
            },
            {
              key: "skillScanner",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.skillScanner.title")}
                </span>
              ),
              children: (
                <div className={styles.tabContent}>
                  <div className={styles.sectionSkillScannerContainer}>
                    <p className={styles.tabDescription}>
                      {t("security.skillScanner.description")}
                    </p>
                    <SkillScannerSection />
                  </div>
                </div>
              ),
            },
          ]}
        />
      </div>

      {activeTab === "toolGuard" && (
        <div className={styles.footerButtons}>
          <Button
            onClick={handleReset}
            disabled={saving}
            style={{ marginRight: 8 }}
          >
            {t("common.reset")}
          </Button>
          <Button type="primary" onClick={handleSave} loading={saving}>
            {t("common.save")}
          </Button>
        </div>
      )}

      {activeTab === "fileGuard" && fileGuardHandlers && (
        <div className={styles.footerButtons}>
          <Button
            onClick={fileGuardHandlers.reset}
            disabled={fileGuardHandlers.saving}
            style={{ marginRight: 8 }}
          >
            {t("common.reset")}
          </Button>
          <Button
            type="primary"
            onClick={fileGuardHandlers.save}
            loading={fileGuardHandlers.saving}
          >
            {t("common.save")}
          </Button>
        </div>
      )}

      <RuleModal
        open={editModal}
        editingRule={editingRule}
        existingRuleIds={[
          ...builtinRules.map((r) => r.id),
          ...customRules.map((r) => r.id),
        ]}
        onOk={handleEditSave}
        onCancel={() => setEditModal(false)}
        form={editForm}
      />

      <PreviewModal rule={previewRule} onClose={() => setPreviewRule(null)} />
    </div>
  );
}

export default SecurityPage;
