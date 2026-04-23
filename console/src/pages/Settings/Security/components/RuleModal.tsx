import { useEffect } from "react";
import { Modal, Form, Input, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { ToolGuardRule } from "../../../../api/modules/security";

const SEVERITY_OPTIONS = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
const CATEGORY_OPTIONS = [
  "command_injection",
  "code_execution",
  "data_exfiltration",
  "path_traversal",
  "sensitive_file_access",
  "network_abuse",
  "credential_exposure",
  "resource_abuse",
  "privilege_escalation",
  "prompt_injection",
];
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

interface RuleModalProps {
  open: boolean;
  editingRule: ToolGuardRule | null;
  existingRuleIds: string[];
  onOk: () => void;
  onCancel: () => void;
  form: any;
}

export function RuleModal({
  open,
  editingRule,
  existingRuleIds,
  onOk,
  onCancel,
  form,
}: RuleModalProps) {
  const { t } = useTranslation();

  useEffect(() => {
    if (open) {
      if (editingRule) {
        form.setFieldsValue({
          ...editingRule,
          patterns: editingRule.patterns.join("\n"),
          exclude_patterns: editingRule.exclude_patterns.join("\n"),
        });
      } else {
        form.resetFields();
        form.setFieldsValue({
          severity: "HIGH",
          category: "command_injection",
          tools: [],
          params: [],
          patterns: "",
          exclude_patterns: "",
        });
      }
    }
  }, [open, editingRule, form]);

  const toolOptions = BUILTIN_TOOLS.map((name) => ({
    label: name,
    value: name,
  }));

  return (
    <Modal
      title={
        editingRule
          ? t("security.rules.editTitle")
          : t("security.rules.addTitle")
      }
      open={open}
      onOk={onOk}
      onCancel={onCancel}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      width={640}
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item
          label={t("security.rules.ruleId")}
          name="id"
          rules={[
            { required: true, message: t("security.rules.ruleIdRequired") },
            {
              validator: (_, value) => {
                if (!value || editingRule) return Promise.resolve();
                if (existingRuleIds.includes(value)) {
                  return Promise.reject(
                    new Error(t("security.rules.duplicateId")),
                  );
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <Input placeholder="TOOL_CMD_CUSTOM_RULE" disabled={!!editingRule} />
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
            options={CATEGORY_OPTIONS.map((c) => ({
              label: t(`security.rules.categories.${c}`, { defaultValue: c }),
              value: c,
            }))}
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
            placeholder={"\\brm\\b\\n\\bmv\\b"}
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
  );
}
