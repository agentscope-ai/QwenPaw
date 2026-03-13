import { useState, useEffect, useCallback } from "react";
import api from "../../../api";
import type {
  ToolGuardConfig,
  ToolGuardRule,
} from "../../../api/modules/security";

export interface MergedRule extends ToolGuardRule {
  source: "builtin" | "custom";
  disabled: boolean;
}

export function useToolGuard() {
  const [config, setConfig] = useState<ToolGuardConfig | null>(null);
  const [builtinRules, setBuiltinRules] = useState<ToolGuardRule[]>([]);
  const [customRules, setCustomRules] = useState<ToolGuardRule[]>([]);
  const [disabledRules, setDisabledRules] = useState<Set<string>>(new Set());
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, builtin] = await Promise.all([
        api.getToolGuard(),
        api.getBuiltinRules(),
      ]);
      setConfig(cfg);
      setEnabled(cfg.enabled);
      setBuiltinRules(builtin);
      setCustomRules(cfg.custom_rules ?? []);
      setDisabledRules(new Set(cfg.disabled_rules ?? []));
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

  const deleteCustomRule = useCallback((ruleId: string) => {
    setCustomRules((prev) => prev.filter((r) => r.id !== ruleId));
    setDisabledRules((prev) => {
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
    })),
    ...customRules.map((r) => ({
      ...r,
      source: "custom" as const,
      disabled: disabledRules.has(r.id),
    })),
  ];

  const buildSaveBody = useCallback((): ToolGuardConfig => {
    return {
      enabled,
      guarded_tools: config?.guarded_tools ?? null,
      denied_tools: config?.denied_tools ?? [],
      custom_rules: customRules,
      disabled_rules: Array.from(disabledRules),
    };
  }, [enabled, config, customRules, disabledRules]);

  return {
    config,
    builtinRules,
    customRules,
    disabledRules,
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
  };
}
