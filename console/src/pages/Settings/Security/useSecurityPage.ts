import { useState, useCallback } from "react";
import { Form } from "@agentscope-ai/design";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { useToolGuard, type MergedRule } from "./useToolGuard";

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

export function useSecurityPage() {
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
    shellEvasionChecks,
    toggleShellEvasionCheck,
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

  const { message } = useAppMessage();

  // Form handlers
  const handleSave = useCallback(async () => {
    try {
      setSaving(true);
      const values = await form.validateFields();
      const guardedTools: string[] = values.guarded_tools ?? [];
      const savedBody = buildSaveBody();
      const body = {
        enabled: values.enabled,
        guarded_tools: guardedTools.length > 0 ? guardedTools : null,
        denied_tools: values.denied_tools ?? [],
        custom_rules: customRules,
        disabled_rules: Array.from(savedBody.disabled_rules),
        shell_evasion_checks: savedBody.shell_evasion_checks,
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

  return {
    // Tab state
    activeTab,
    setActiveTab,

    // Tool Guard form
    form,
    config,
    enabled,
    setEnabled,
    toolOptions,
    saving,
    handleSave,
    handleReset,

    // Rules
    mergedRules,
    builtinRules,
    customRules,
    toggleRule,
    deleteCustomRule,
    openAddRule,
    openEditRule,

    // Shell Evasion
    shellEvasionChecks,
    toggleShellEvasionCheck,

    // Modals
    editModal,
    setEditModal,
    editingRule,
    editForm,
    handleEditSave,
    previewRule,
    setPreviewRule,

    // FileGuard
    fileGuardHandlers,
    onFileGuardHandlersReady,

    // Loading / Error
    loading,
    error,
    fetchAll,
  };
}
