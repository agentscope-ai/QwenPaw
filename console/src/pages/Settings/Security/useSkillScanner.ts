import { useState, useEffect, useCallback } from "react";
import api from "../../../api";
import type {
  SkillScannerConfig,
  BlockedSkillRecord,
  SkillScannerWhitelistEntry,
} from "../../../api/modules/security";

export function useSkillScanner() {
  const [config, setConfig] = useState<SkillScannerConfig | null>(null);
  const [blockedHistory, setBlockedHistory] = useState<BlockedSkillRecord[]>(
    [],
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, history] = await Promise.all([
        api.getSkillScanner(),
        api.getBlockedHistory(),
      ]);
      setConfig(cfg);
      setBlockedHistory(history);
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : "Failed to load skill scanner config";
      console.error("Failed to load skill scanner:", err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const updateConfig = useCallback(
    async (updates: Partial<SkillScannerConfig>) => {
      if (!config) return;
      const newConfig = { ...config, ...updates };
      try {
        const saved = await api.updateSkillScanner(newConfig);
        setConfig(saved);
        return true;
      } catch (err) {
        console.error("Failed to update skill scanner config:", err);
        return false;
      }
    },
    [config],
  );

  const addToWhitelist = useCallback(
    async (skillName: string, contentHash: string = "") => {
      try {
        await api.addToWhitelist(skillName, contentHash);
        await fetchAll();
        return true;
      } catch (err) {
        console.error("Failed to add to whitelist:", err);
        return false;
      }
    },
    [fetchAll],
  );

  const removeFromWhitelist = useCallback(
    async (skillName: string) => {
      try {
        await api.removeFromWhitelist(skillName);
        await fetchAll();
        return true;
      } catch (err) {
        console.error("Failed to remove from whitelist:", err);
        return false;
      }
    },
    [fetchAll],
  );

  const removeBlockedEntry = useCallback(
    async (index: number) => {
      try {
        await api.removeBlockedEntry(index);
        await fetchAll();
        return true;
      } catch (err) {
        console.error("Failed to remove blocked entry:", err);
        return false;
      }
    },
    [fetchAll],
  );

  const clearBlockedHistory = useCallback(async () => {
    try {
      await api.clearBlockedHistory();
      setBlockedHistory([]);
      return true;
    } catch (err) {
      console.error("Failed to clear blocked history:", err);
      return false;
    }
  }, []);

  const whitelist: SkillScannerWhitelistEntry[] = config?.whitelist ?? [];

  return {
    config,
    blockedHistory,
    whitelist,
    loading,
    error,
    fetchAll,
    updateConfig,
    addToWhitelist,
    removeFromWhitelist,
    removeBlockedEntry,
    clearBlockedHistory,
  };
}
