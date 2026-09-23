import { useAutoSave } from "@/hooks/useAutoSave";
import { useState, useCallback } from "react";
import { Form } from "@agentscope-ai/design";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { useToolGuard, type MergedRule } from "./useToolGuard";

const BUILTIN_TOOLS = [
  "execute_shell_command",
  "execute_python_code",
  "browser",
  // ── DEPRECATED BROWSER (remove together with backend deprecated_browser/) ──
  "browser",
  // ── END DEPRECATED BROWSER ──
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
    sandboxEnabled,
    savedSandboxEnabled,
    markSandboxSaved,
    setSandboxEnabled,
    sandboxEffective,
    sandboxReason,
    denyPathsActive,
    denyPathsLoading,
    denyPathsProtectedPaths,
    denyPathsPlatformSupported,
    toggleDenyPaths,
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
  const handleSave = useCallback(
    async (automatic = false) => {
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
          auto_denied_rules: savedBody.auto_denied_rules,
          shell_evasion_checks: savedBody.shell_evasion_checks,
        };
        // Save sandbox FIRST so that if it fails (e.g. 403 for non-admin),
        // Tool Guard has not been touched — avoiding a partial-save state
        // where Tool Guard is persisted but sandbox is not.
        // Only call the API when the value actually changed to skip
        // unnecessary requests (and potential 403s) on unchanged toggles.
        if (sandboxEnabled !== savedSandboxEnabled) {
          await api.updateSandbox({ enabled: sandboxEnabled });
        }
        await api.updateToolGuard(body);
        setEnabled(body.enabled);
        markSandboxSaved();
        if (!automatic) message.success(t("security.saveSuccess"));
      } catch (err) {
        if (err && typeof err === "object" && "errorFields" in err) {
          return;
        }
        if (automatic) throw err;
        const errMsg =
          err instanceof Error ? err.message : t("security.saveFailed");
        message.error(errMsg);
      } finally {
        setSaving(false);
      }
    },
    [
      customRules,
      buildSaveBody,
      form,
      t,
      sandboxEnabled,
      savedSandboxEnabled,
      markSandboxSaved,
      setEnabled,
      message,
    ],
  );

  const { schedule: scheduleSave, flush: flushSave } = useAutoSave(() =>
    handleSave(true),
  );

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
      scheduleSave();
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
    setEnabled: (value: boolean) => {
      setEnabled(value);
      scheduleSave();
    },
    sandboxEnabled,
    setSandboxEnabled: (value: boolean) => {
      void setSandboxEnabled(value);
      scheduleSave();
    },
    sandboxEffective,
    sandboxReason,
    // Deny paths protection
    denyPathsActive,
    denyPathsLoading,
    denyPathsProtectedPaths,
    denyPathsPlatformSupported,
    toggleDenyPaths,
    toolOptions,
    saving,
    handleSave,
    scheduleSave,
    flushSave,
    handleReset,

    // Rules
    mergedRules,
    builtinRules,
    customRules,
    toggleRule: (...args: Parameters<typeof toggleRule>) => {
      toggleRule(...args);
      scheduleSave();
    },
    toggleAutoDeny: (...args: Parameters<typeof toggleAutoDeny>) => {
      toggleAutoDeny(...args);
      scheduleSave();
    },
    deleteCustomRule: (...args: Parameters<typeof deleteCustomRule>) => {
      deleteCustomRule(...args);
      scheduleSave();
    },
    openAddRule,
    openEditRule,

    // Shell Evasion
    shellEvasionChecks,
    toggleShellEvasionCheck: (
      ...args: Parameters<typeof toggleShellEvasionCheck>
    ) => {
      toggleShellEvasionCheck(...args);
      scheduleSave();
    },

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

    // AllowNoAuthHosts
    allowNoAuthHostsHandlers,
    onAllowNoAuthHostsHandlersReady,

    // Loading / Error
    loading,
    error,
    fetchAll,
  };
}
