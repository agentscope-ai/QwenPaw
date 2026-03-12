import { useState, useEffect, useCallback } from "react";
import {
  Form,
  Switch,
  Button,
  Card,
  Select,
  Table,
  Tag,
  Modal,
  Input,
  message,
  Tooltip,
} from "@agentscope-ai/design";
import { Space } from "antd";
import { Plus, Trash2, Pencil, Eye } from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type {
  ToolGuardConfig,
  ToolGuardRule,
} from "../../../api/modules/security";
import styles from "./index.module.less";

const BUILTIN_TOOLS = [
  "execute_shell_command",
  "execute_python_code",
  "browser_use",
  "desktop_screenshot",
  "read_file",
  "write_file",
  "edit_file",
  "append_file",
  "view_text_file",
  "write_text_file",
  "send_file_to_user",
];

const SEVERITY_OPTIONS = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
const CATEGORY_OPTIONS = [
  "command_injection",
  "data_exfiltration",
  "path_traversal",
  "sensitive_file_access",
  "network_abuse",
  "credential_exposure",
  "resource_abuse",
  "code_execution",
];

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "red",
  HIGH: "orange",
  MEDIUM: "gold",
  LOW: "blue",
  INFO: "default",
};

interface MergedRule extends ToolGuardRule {
  source: "builtin" | "custom";
  disabled: boolean;
}

function SecurityPage() {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);

  const [builtinRules, setBuiltinRules] = useState<ToolGuardRule[]>([]);
  const [customRules, setCustomRules] = useState<ToolGuardRule[]>([]);
  const [disabledRules, setDisabledRules] = useState<Set<string>>(new Set());

  const [editModal, setEditModal] = useState(false);
  const [editingRule, setEditingRule] = useState<ToolGuardRule | null>(null);
  const [editForm] = Form.useForm();
  const [previewRule, setPreviewRule] = useState<ToolGuardRule | null>(null);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [config, builtin] = await Promise.all([
        api.getToolGuard(),
        api.getBuiltinRules(),
      ]);
      setEnabled(config.enabled);
      setBuiltinRules(builtin);
      setCustomRules(config.custom_rules ?? []);
      setDisabledRules(new Set(config.disabled_rules ?? []));
      form.setFieldsValue({
        enabled: config.enabled,
        guarded_tools: config.guarded_tools ?? [],
        denied_tools: config.denied_tools,
      });
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : t("security.loadFailed");
      setError(errMsg);
    } finally {
      setLoading(false);
    }
  }, [form, t]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const buildSaveBody = async (): Promise<ToolGuardConfig> => {
    const values = await form.validateFields();
    const guardedTools: string[] = values.guarded_tools ?? [];
    return {
      enabled: values.enabled,
      guarded_tools: guardedTools.length > 0 ? guardedTools : null,
      denied_tools: values.denied_tools ?? [],
      custom_rules: customRules,
      disabled_rules: Array.from(disabledRules),
    };
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      const body = await buildSaveBody();
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
  };

  const toggleRule = (ruleId: string, currentlyDisabled: boolean) => {
    setDisabledRules((prev) => {
      const next = new Set(prev);
      if (currentlyDisabled) {
        next.delete(ruleId);
      } else {
        next.add(ruleId);
      }
      return next;
    });
  };

  const deleteCustomRule = (ruleId: string) => {
    setCustomRules((prev) => prev.filter((r) => r.id !== ruleId));
    setDisabledRules((prev) => {
      const next = new Set(prev);
      next.delete(ruleId);
      return next;
    });
  };

  const openAddRule = () => {
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
  };

  const openEditRule = (rule: ToolGuardRule) => {
    setEditingRule(rule);
    editForm.setFieldsValue({
      ...rule,
      patterns: rule.patterns.join("\n"),
      exclude_patterns: rule.exclude_patterns.join("\n"),
    });
    setEditModal(true);
  };

  const handleEditSave = async () => {
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

      const rule: ToolGuardRule = {
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
        setCustomRules((prev) =>
          prev.map((r) => (r.id === editingRule.id ? rule : r)),
        );
      } else {
        const allIds = [
          ...builtinRules.map((r) => r.id),
          ...customRules.map((r) => r.id),
        ];
        if (allIds.includes(rule.id)) {
          message.error(t("security.rules.duplicateId"));
          return;
        }
        setCustomRules((prev) => [...prev, rule]);
      }
      setEditModal(false);
    } catch {
      // validation failed
    }
  };

  const mergedRules: MergedRule[] = [
    ...builtinRules.map((r) => ({
      ...r,
      source: "builtin" as const,
      disabled: disabledRules.has(r.id),
    })),
    ...customRules.map((r) => ({
      ...r,
      source: "custom" as const,
      disabled: disabledRules.has(r.id),
    })),
  ];

  const columns = [
    {
      title: t("security.rules.id"),
      dataIndex: "id",
      key: "id",
      width: 220,
      render: (id: string, record: MergedRule) => (
        <span style={{ opacity: record.disabled ? 0.4 : 1 }}>{id}</span>
      ),
    },
    {
      title: t("security.rules.severity"),
      dataIndex: "severity",
      key: "severity",
      width: 100,
      render: (sev: string, record: MergedRule) => (
        <Tag
          color={SEVERITY_COLORS[sev] ?? "default"}
          style={{ opacity: record.disabled ? 0.4 : 1 }}
        >
          {sev}
        </Tag>
      ),
    },
    {
      title: t("security.rules.descriptionCol"),
      dataIndex: "description",
      key: "description",
      render: (_text: string, record: MergedRule) => {
        const i18nKey = `security.rules.descriptions.${record.id}`;
        const translated = t(i18nKey, { defaultValue: "" });
        const display = translated || record.description;
        return (
          <span
            style={{
              opacity: record.disabled ? 0.4 : 1,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {display}
          </span>
        );
      },
    },
    {
      title: t("security.rules.source"),
      dataIndex: "source",
      key: "source",
      width: 100,
      render: (source: string, record: MergedRule) => (
        <Tag
          color={source === "builtin" ? "geekblue" : "green"}
          style={{ opacity: record.disabled ? 0.4 : 1 }}
        >
          {source === "builtin"
            ? t("security.rules.builtin")
            : t("security.rules.custom")}
        </Tag>
      ),
    },
    {
      title: t("security.rules.actions"),
      key: "actions",
      width: 160,
      render: (_: unknown, record: MergedRule) => (
        <Space size="small">
          <Tooltip
            title={
              record.disabled
                ? t("security.rules.enable")
                : t("security.rules.disable")
            }
          >
            <Switch
              size="small"
              checked={!record.disabled}
              onChange={() => toggleRule(record.id, record.disabled)}
            />
          </Tooltip>
          {record.source === "builtin" && (
            <Tooltip title={t("security.rules.preview")}>
              <Button
                type="text"
                size="small"
                icon={<Eye size={14} />}
                onClick={() => setPreviewRule(record)}
              />
            </Tooltip>
          )}
          {record.source === "custom" && (
            <>
              <Tooltip title={t("security.rules.edit")}>
                <Button
                  type="text"
                  size="small"
                  icon={<Pencil size={14} />}
                  onClick={() => openEditRule(record)}
                />
              </Tooltip>
              <Tooltip title={t("security.rules.delete")}>
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<Trash2 size={14} />}
                  onClick={() => deleteCustomRule(record.id)}
                />
              </Tooltip>
            </>
          )}
        </Space>
      ),
    },
  ];

  const toolOptions = BUILTIN_TOOLS.map((name) => ({
    label: name,
    value: name,
  }));

  return (
    <div className={styles.page}>
      {loading && (
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      )}

      {error && !loading && (
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>{error}</span>
          <Button size="small" onClick={fetchConfig} style={{ marginTop: 12 }}>
            {t("environments.retry")}
          </Button>
        </div>
      )}

      <div style={{ display: loading || error ? "none" : "block" }}>
        <div className={styles.header}>
          <div>
            <h1 className={styles.title}>{t("security.title")}</h1>
            <p className={styles.description}>{t("security.description")}</p>
          </div>
        </div>

        <Card className={styles.formCard}>
          <Form form={form} layout="vertical" className={styles.form}>
            <Form.Item
              label={t("security.enabled")}
              name="enabled"
              valuePropName="checked"
              tooltip={t("security.enabledTooltip")}
            >
              <Switch onChange={(val) => setEnabled(val)} />
            </Form.Item>

            <Form.Item
              label={t("security.guardedTools")}
              name="guarded_tools"
              tooltip={t("security.guardedToolsTooltip")}
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
          </Form>
        </Card>

        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>{t("security.rules.title")}</h2>
          <Button
            type="primary"
            icon={<Plus size={14} />}
            onClick={openAddRule}
            disabled={!enabled}
            size="small"
          >
            {t("security.rules.add")}
          </Button>
        </div>

        <Card className={styles.tableCard}>
          <Table
            dataSource={mergedRules}
            columns={columns}
            rowKey="id"
            pagination={false}
            size="small"
          />
        </Card>

        <div className={styles.footerButtons}>
          <Button
            onClick={fetchConfig}
            disabled={saving}
            style={{ marginRight: 8 }}
          >
            {t("common.reset")}
          </Button>
          <Button type="primary" onClick={handleSave} loading={saving}>
            {t("common.save")}
          </Button>
        </div>
      </div>

      <Modal
        title={
          editingRule
            ? t("security.rules.editTitle")
            : t("security.rules.addTitle")
        }
        open={editModal}
        onOk={handleEditSave}
        onCancel={() => setEditModal(false)}
        width={640}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            label={t("security.rules.ruleId")}
            name="id"
            rules={[
              { required: true, message: t("security.rules.ruleIdRequired") },
            ]}
          >
            <Input
              placeholder="TOOL_CMD_CUSTOM_RULE"
              disabled={!!editingRule}
            />
          </Form.Item>
          <Form.Item label={t("security.rules.tools")} name="tools">
            <Select
              mode="tags"
              options={toolOptions}
              placeholder={t("security.rules.toolsPlaceholder")}
              allowClear
            />
          </Form.Item>
          <Form.Item label={t("security.rules.params")} name="params">
            <Select
              mode="tags"
              placeholder={t("security.rules.paramsPlaceholder")}
              allowClear
            />
          </Form.Item>
          <Form.Item label={t("security.rules.severityLabel")} name="severity">
            <Select
              options={SEVERITY_OPTIONS.map((s) => ({ label: s, value: s }))}
            />
          </Form.Item>
          <Form.Item label={t("security.rules.categoryLabel")} name="category">
            <Select
              options={CATEGORY_OPTIONS.map((c) => ({ label: c, value: c }))}
            />
          </Form.Item>
          <Form.Item
            label={t("security.rules.patterns")}
            name="patterns"
            rules={[
              { required: true, message: t("security.rules.patternsRequired") },
            ]}
            tooltip={t("security.rules.patternsTooltip")}
          >
            <Input.TextArea
              rows={3}
              placeholder={"\\brm\\b\n\\bmv\\b"}
              style={{ fontFamily: "monospace" }}
            />
          </Form.Item>
          <Form.Item
            label={t("security.rules.excludePatterns")}
            name="exclude_patterns"
            tooltip={t("security.rules.excludePatternsTooltip")}
          >
            <Input.TextArea
              rows={2}
              placeholder={"^#"}
              style={{ fontFamily: "monospace" }}
            />
          </Form.Item>
          <Form.Item
            label={t("security.rules.descriptionLabel")}
            name="description"
          >
            <Input placeholder={t("security.rules.descriptionPlaceholder")} />
          </Form.Item>
          <Form.Item
            label={t("security.rules.remediationLabel")}
            name="remediation"
          >
            <Input placeholder={t("security.rules.remediationPlaceholder")} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t("security.rules.previewTitle")}
        open={!!previewRule}
        onCancel={() => setPreviewRule(null)}
        footer={
          <Button onClick={() => setPreviewRule(null)}>
            {t("common.close")}
          </Button>
        }
        width={640}
      >
        {previewRule && (
          <div style={{ marginTop: 16 }}>
            <p>
              <strong>{t("security.rules.ruleId")}:</strong> {previewRule.id}
            </p>
            <p>
              <strong>{t("security.rules.severityLabel")}:</strong>{" "}
              <Tag color={SEVERITY_COLORS[previewRule.severity] ?? "default"}>
                {previewRule.severity}
              </Tag>
            </p>
            <p>
              <strong>{t("security.rules.tools")}:</strong>{" "}
              {previewRule.tools.length > 0
                ? previewRule.tools.join(", ")
                : t("security.rules.allTools")}
            </p>
            <p>
              <strong>{t("security.rules.params")}:</strong>{" "}
              {previewRule.params.length > 0
                ? previewRule.params.join(", ")
                : t("security.rules.allParams")}
            </p>
            <p>
              <strong>{t("security.rules.actionLabel")}:</strong>{" "}
              <Tag color="orange">{t("security.rules.actionApproval")}</Tag>
            </p>
            <p style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              <strong>{t("security.rules.descriptionLabel")}:</strong>{" "}
              {t(`security.rules.descriptions.${previewRule.id}`, {
                defaultValue: "",
              }) || previewRule.description}
            </p>
            <p>
              <strong>{t("security.rules.patterns")}:</strong>
            </p>
            <pre
              style={{
                background: "#f5f5f5",
                padding: 12,
                borderRadius: 6,
                fontSize: 13,
              }}
            >
              {previewRule.patterns.join("\n")}
            </pre>
            {previewRule.exclude_patterns.length > 0 && (
              <>
                <p>
                  <strong>{t("security.rules.excludePatterns")}:</strong>
                </p>
                <pre
                  style={{
                    background: "#f5f5f5",
                    padding: 12,
                    borderRadius: 6,
                    fontSize: 13,
                  }}
                >
                  {previewRule.exclude_patterns.join("\n")}
                </pre>
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

export default SecurityPage;
