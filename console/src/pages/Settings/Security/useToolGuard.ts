import { useState, useEffect, useCallback, useRef } from "react";
import api from "../../../api";
import type {
  ToolGuardConfig,
  ToolGuardRule,
} from "../../../api/modules/security";

export interface MergedRule extends ToolGuardRule {
  source: "builtin" | "custom";
  disabled: boolean;
  autoDeny: boolean;
}

export function useToolGuard() {
  const [config, setConfig] = useState<ToolGuardConfig | null>(null);
  const [builtinRules, setBuiltinRules] = useState<ToolGuardRule[]>([]);
  const [customRules, setCustomRules] = useState<ToolGuardRule[]>([]);
  const [disabledRules, setDisabledRules] = useState<Set<string>>(new Set());
  const [autoDenyRules, setAutoDenyRules] = useState<Set<string>>(new Set());
  const [shellEvasionChecks, setShellEvasionChecks] = useState<
    Record<string, boolean>
  >({});
  const [enabled, setEnabled] = useState(true);
  const [sandboxEnabled, setSandboxEnabled] = useState(false);
  // Track the last *persisted* sandbox value so the save handler can
  // skip the API call when nothing changed (avoids unnecessary 403s
  // and partial-save side-effects).
  const savedSandboxEnabledRef = useRef(false);
  const [sandboxEffective, setSandboxEffective] = useState(true);
  const [sandboxReason, setSandboxReason] = useState<string | null>(null);

  // Wrapped setter: when the sandbox toggle changes, immediately re-fetch
  // the effective status from the backend so the degradation warning
  // (enabled but not effective due to non-admin) appears right away,
  // rather than only after a full page reload.
  const handleSandboxToggle = useCallback(async (val: boolean) => {
    setSandboxEnabled(val);
    try {
      // Pass the proposed value so the backend computes effective/reason
      // for the toggle target, not the current (unsaved) config value.
      const sandbox = await api.getSandbox(val);
      setSandboxEffective(sandbox.effective);
      setSandboxReason(sandbox.reason);
    } catch {
      // Best-effort: if the fetch fails, keep the previous effective/reason.
      // The save handler will surface any real errors.
    }
  }, []);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, builtin, sandbox] = await Promise.all([
        api.getToolGuard(),
        api.getBuiltinRules(),
        api.getSandbox(),
      ]);
      setConfig(cfg);
      setEnabled(cfg.enabled);
      setBuiltinRules(builtin);
      setCustomRules(cfg.custom_rules ?? []);
      setDisabledRules(new Set(cfg.disabled_rules ?? []));
      setAutoDenyRules(new Set(cfg.auto_denied_rules ?? []));
      setShellEvasionChecks(cfg.shell_evasion_checks ?? {});
      setSandboxEnabled(sandbox.enabled);
      savedSandboxEnabledRef.current = sandbox.enabled;
      setSandboxEffective(sandbox.effective);
      setSandboxReason(sandbox.reason);
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Failed to load security config";
      console.error("Failed to load tool guard:", err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const toggleRule = useCallback(
    (ruleId: string, currentlyDisabled: boolean) => {
      setDisabledRules((prev) => {
        const next = new Set(prev);
        if (currentlyDisabled) {
          next.delete(ruleId);
        } else {
          next.add(ruleId);
        }
        return next;
      });
    },
    [],
  );

  const toggleAutoDeny = useCallback(
    (ruleId: string, currentlyAutoDeny: boolean) => {
      setAutoDenyRules((prev) => {
        const next = new Set(prev);
        if (currentlyAutoDeny) {
          next.delete(ruleId);
        } else {
          next.add(ruleId);
        }
        return next;
      });
    },
    [],
  );

  const deleteCustomRule = useCallback((ruleId: string) => {
    setCustomRules((prev) => prev.filter((r) => r.id !== ruleId));
    setDisabledRules((prev) => {
      const next = new Set(prev);
      next.delete(ruleId);
      return next;
    });
    setAutoDenyRules((prev) => {
      const next = new Set(prev);
      next.delete(ruleId);
      return next;
    });
  }, []);

  const addCustomRule = useCallback((rule: ToolGuardRule) => {
    setCustomRules((prev) => [...prev, rule]);
  }, []);

  const updateCustomRule = useCallback(
    (ruleId: string, rule: ToolGuardRule) => {
      setCustomRules((prev) => prev.map((r) => (r.id === ruleId ? rule : r)));
    },
    [],
  );

  const mergedRules: MergedRule[] = [
    ...builtinRules.map((r) => ({
      ...r,
      source: "builtin" as const,
      disabled: disabledRules.has(r.id),
      autoDeny: autoDenyRules.has(r.id),
    })),
    ...customRules.map((r) => ({
      ...r,
      source: "custom" as const,
      disabled: disabledRules.has(r.id),
      autoDeny: autoDenyRules.has(r.id),
    })),
  ];

  const toggleShellEvasionCheck = useCallback(
    (checkName: string, checked: boolean) => {
      setShellEvasionChecks((prev) => ({ ...prev, [checkName]: checked }));
    },
    [],
  );

  const buildSaveBody = useCallback((): ToolGuardConfig => {
    return {
      enabled,
      guarded_tools: config?.guarded_tools ?? null,
      denied_tools: config?.denied_tools ?? [],
      custom_rules: customRules,
      disabled_rules: Array.from(disabledRules),
      auto_denied_rules: Array.from(autoDenyRules),
      shell_evasion_checks: shellEvasionChecks,
    };
  }, [
    enabled,
    config,
    customRules,
    disabledRules,
    autoDenyRules,
    shellEvasionChecks,
  ]);

  return {
    config,
    builtinRules,
    customRules,
    disabledRules,
    autoDenyRules,
    enabled,
    setEnabled,
    sandboxEnabled,
    savedSandboxEnabled: savedSandboxEnabledRef.current,
    markSandboxSaved: useCallback(() => {
      savedSandboxEnabledRef.current = sandboxEnabled;
    }, [sandboxEnabled]),
    setSandboxEnabled: handleSandboxToggle,
    sandboxEffective,
    sandboxReason,
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
  };
}
