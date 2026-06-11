import { useState, useCallback } from "react";
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
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState("toolGuard");

  // Uncontrolled form state for ToolGuard
  const [formEnabled, setFormEnabled] = useState(true);
  const [formGuardedTools, setFormGuardedTools] = useState<string[]>([]);
  const [formDeniedTools, setFormDeniedTools] = useState<string[]>([]);

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

  // AllowNoAuthHosts handlers exposed from child component
  const [allowNoAuthHostsHandlers, setAllowNoAuthHostsHandlers] = useState<{
    save: () => Promise<void>;
    reset: () => void;
    saving: boolean;
  } | null>(null);

  const onAllowNoAuthHostsHandlersReady = useCallback(
    (handlers: {
      save: () => Promise<void>;
      reset: () => void;
      saving: boolean;
    }) => {
      setAllowNoAuthHostsHandlers(handlers);
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
    toggleAutoDeny,
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
      const savedBody = buildSaveBody();
      const body = {
        enabled: formEnabled,
        guarded_tools: formGuardedTools.length > 0 ? formGuardedTools : null,
        denied_tools: formDeniedTools,
        custom_rules: customRules,
        disabled_rules: Array.from(savedBody.disabled_rules),
        auto_denied_rules: savedBody.auto_denied_rules,
        shell_evasion_checks: savedBody.shell_evasion_checks,
      };
      await api.updateToolGuard(body);
      setEnabled(body.enabled);
      message.success(t("security.saveSuccess"));
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : t("security.saveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  }, [
    customRules,
    buildSaveBody,
    formEnabled,
    formGuardedTools,
    formDeniedTools,
    setEnabled,
    t,
  ]);

  const handleReset = useCallback(() => {
    fetchAll();
  }, [fetchAll]);

  // Rule modal handlers
  const openAddRule = useCallback(() => {
    setEditingRule(null);
    setEditModal(true);
  }, []);

  const openEditRule = useCallback((rule: MergedRule) => {
    setEditingRule(rule);
    setEditModal(true);
  }, []);

  interface RuleFormValues {
    id: string;
    tools: string[];
    params: string[];
    category: string;
    severity: string;
    patterns: string;
    exclude_patterns: string;
    description: string;
    remediation: string;
  }

  const handleEditSave = useCallback(
    (values: RuleFormValues) => {
      const patterns = values.patterns
        .split("\n")
        .map((s: string) => s.trim())
        .filter(Boolean);
      const excludePatterns = (values.exclude_patterns || "")
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
    },
    [
      editingRule,
      builtinRules,
      customRules,
      updateCustomRule,
      addCustomRule,
      t,
    ],
  );

  const toolOptions = BUILTIN_TOOLS.map((name) => ({
    label: name,
    value: name,
  }));

  return {
    // Tab state
    activeTab,
    setActiveTab,

    // Tool Guard form state (uncontrolled)
    formEnabled,
    setFormEnabled,
    formGuardedTools,
    setFormGuardedTools,
    formDeniedTools,
    setFormDeniedTools,
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
    toggleAutoDeny,
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
    handleEditSave,
    previewRule,
    setPreviewRule,

    // FileGuard
    fileGuardHandlers,
    onFileGuardHandlersReady,

    // AllowNoAuthHosts
    allowNoAuthHostsHandlers,
    onAllowNoAuthHostsHandlersReady,

    // Loading / Error
    loading,
    error,
    fetchAll,
  };
}
