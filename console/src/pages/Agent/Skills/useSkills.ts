import { useState, useEffect, useCallback } from "react";
import { message, Modal } from "@agentscope-ai/design";
import React from "react";
import api from "../../../api";
import type { SkillSpec } from "../../../api/types";
import type {
  MarketError,
  MarketplaceItem,
  MarketplaceMeta,
  SkillsMarketSpec,
  SkillsMarketsPayload,
} from "../../../api/types/skill";
import type { SecurityScanErrorResponse } from "../../../api/modules/security";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";

function tryParseScanError(error: unknown): SecurityScanErrorResponse | null {
  if (!(error instanceof Error)) return null;
  const msg = error.message || "";
  const jsonStart = msg.indexOf("{");
  if (jsonStart === -1) return null;
  try {
    const parsed = JSON.parse(msg.substring(jsonStart));
    if (parsed?.type === "security_scan_failed") {
      return parsed as SecurityScanErrorResponse;
    }
  } catch {
    // not JSON
  }
  return null;
}

export function useSkills() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [markets, setMarkets] = useState<SkillsMarketSpec[]>([]);
  const [marketConfig, setMarketConfig] = useState<SkillsMarketsPayload | null>(
    null,
  );
  const [marketplace, setMarketplace] = useState<MarketplaceItem[]>([]);
  const [marketErrors, setMarketErrors] = useState<MarketError[]>([]);
  const [marketMeta, setMarketMeta] = useState<MarketplaceMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [marketplaceLoading, setMarketplaceLoading] = useState(false);
  const [installingSkillKey, setInstallingSkillKey] = useState<string | null>(
    null,
  );
  const [importing, setImporting] = useState(false);

  const showScanErrorModal = useCallback(
    (scanError: SecurityScanErrorResponse) => {
      const findings = scanError.findings || [];
      Modal.error({
        title: t("security.skillScanner.scanError.title"),
        width: 640,
        content: React.createElement(
          "div",
          null,
          React.createElement(
            "p",
            null,
            t("security.skillScanner.scanError.description"),
          ),
          React.createElement(
            "div",
            {
              style: {
                maxHeight: 300,
                overflow: "auto",
                marginTop: 8,
              },
            },
            findings.map((f, i) =>
              React.createElement(
                "div",
                {
                  key: i,
                  style: {
                    padding: "8px 12px",
                    marginBottom: 4,
                    background: "#fafafa",
                    borderRadius: 6,
                    border: "1px solid #f0f0f0",
                  },
                },
                React.createElement(
                  "strong",
                  { style: { marginBottom: 4, display: "block" } },
                  f.title,
                ),
                React.createElement(
                  "div",
                  { style: { fontSize: 12, color: "#666" } },
                  f.file_path + (f.line_number ? `:${f.line_number}` : ""),
                ),
                f.description &&
                  React.createElement(
                    "div",
                    {
                      style: {
                        fontSize: 12,
                        color: "#999",
                        marginTop: 2,
                      },
                    },
                    f.description,
                  ),
              ),
            ),
          ),
        ),
      });
    },
    [t],
  );

  const handleError = useCallback(
    (error: unknown, defaultMsg: string): boolean => {
      const scanError = tryParseScanError(error);
      if (scanError) {
        showScanErrorModal(scanError);
        return true;
      }
      console.error(defaultMsg, error);
      message.error(defaultMsg);
      return false;
    },
    [showScanErrorModal],
  );

  const checkScanWarnings = useCallback(
    async (skillName: string) => {
      try {
        const [alerts, scannerCfg] = await Promise.all([
          api.getBlockedHistory(),
          api.getSkillScanner(),
        ]);
        if (!alerts.length) return;
        if (
          scannerCfg?.whitelist?.some(
            (w: { skill_name: string }) => w.skill_name === skillName,
          )
        )
          return;
        const latestForSkill = alerts
          .filter((a) => a.skill_name === skillName && a.action === "warned")
          .pop();
        if (!latestForSkill) return;
        const findings = latestForSkill.findings || [];
        Modal.warning({
          title: t("security.skillScanner.scanError.title"),
          width: 640,
          content: React.createElement(
            "div",
            null,
            React.createElement(
              "p",
              null,
              t("security.skillScanner.scanError.warnDescription"),
            ),
            React.createElement(
              "div",
              { style: { maxHeight: 300, overflow: "auto", marginTop: 8 } },
              findings.map((f, i) =>
                React.createElement(
                  "div",
                  {
                    key: i,
                    style: {
                      padding: "8px 12px",
                      marginBottom: 4,
                      background: "#fafafa",
                      borderRadius: 6,
                      border: "1px solid #f0f0f0",
                    },
                  },
                  React.createElement(
                    "strong",
                    { style: { marginBottom: 4, display: "block" } },
                    f.title,
                  ),
                  React.createElement(
                    "div",
                    { style: { fontSize: 12, color: "#666" } },
                    f.file_path + (f.line_number ? `:${f.line_number}` : ""),
                  ),
                  f.description &&
                    React.createElement(
                      "div",
                      { style: { fontSize: 12, color: "#999", marginTop: 2 } },
                      f.description,
                    ),
                ),
              ),
            ),
          ),
        });
      } catch {
        // non-critical
      }
    },
    [t],
  );

  const fetchSkills = async () => {
    setLoading(true);
    try {
      const data = await api.listSkills();
      if (data) {
        setSkills(data);
      }
    } catch (error) {
      console.error("Failed to load skills", error);
      message.error("Failed to load skills");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let mounted = true;

    const loadSkills = async () => {
      await Promise.all([fetchSkills(), fetchMarkets(), fetchMarketplace()]);
    };

    if (mounted) {
      loadSkills();
    }

    return () => {
      mounted = false;
    };
  }, [selectedAgent]);

  const fetchMarkets = async () => {
    try {
      const data = await api.getSkillsMarkets();
      setMarketConfig(data);
      setMarkets(data?.markets ?? []);
    } catch (error) {
      console.error("Failed to load markets", error);
      message.error(t("skills.loadMarketsFailed"));
    }
  };

  const validateMarket = async (market: SkillsMarketSpec) => {
    try {
      const result = await api.validateSkillsMarket(market);
      message.success(
        t("skills.validateMarketSuccess", {
          name: market.name || market.id,
        }),
      );
      return result;
    } catch (error) {
      console.error("Failed to validate market", error);
      message.error(t("skills.validateMarketFailed"));
      return null;
    }
  };

  const saveMarkets = async (nextMarkets: SkillsMarketSpec[]) => {
    const config = marketConfig ?? {
      version: 1,
      cache: { ttl_sec: 600 },
      install: { overwrite_default: false },
      markets: [],
    };
    try {
      const payload: SkillsMarketsPayload = {
        ...config,
        markets: nextMarkets,
      };
      const updated = await api.updateSkillsMarkets(payload);
      setMarketConfig(updated);
      setMarkets(updated.markets);
      message.success(t("skills.saveMarketsSuccess"));
      await fetchMarketplace(true);
      return true;
    } catch (error) {
      console.error("Failed to save markets", error);
      message.error(t("skills.saveMarketsFailed"));
      return false;
    }
  };

  const fetchMarketplace = async (refresh = false) => {
    try {
      setMarketplaceLoading(true);
      const data = await api.getMarketplace(refresh);
      setMarketplace(data?.items ?? []);
      setMarketErrors(data?.market_errors ?? []);
      setMarketMeta(data?.meta ?? null);
    } catch (error) {
      console.error("Failed to load marketplace", error);
      message.error(t("skills.loadMarketplaceFailed"));
    } finally {
      setMarketplaceLoading(false);
    }
  };

  const createSkill = async (name: string, content: string) => {
    try {
      await api.createSkill(name, content);
      message.success("Created successfully");
      await fetchSkills();
      await checkScanWarnings(name);
      return true;
    } catch (error) {
      handleError(error, "Failed to save");
      return false;
    }
  };

  const importFromHub = async (input: string) => {
    const text = (input || "").trim();
    if (!text) {
      message.warning("Please provide a hub skill URL");
      return false;
    }
    if (!text.startsWith("http://") && !text.startsWith("https://")) {
      message.warning(
        "Please enter a valid URL starting with http:// or https://",
      );
      return false;
    }
    try {
      setImporting(true);
      const payload = { bundle_url: text, enable: true, overwrite: false };
      const result = await api.installHubSkill(payload);
      if (result?.installed) {
        message.success(`Imported skill: ${result.name}`);
        await fetchSkills();
        if (result.name) await checkScanWarnings(result.name);
        return true;
      }
      message.error("Import failed");
      return false;
    } catch (error) {
      handleError(error, "Import failed");
      return false;
    } finally {
      setImporting(false);
    }
  };

  const toggleEnabled = async (skill: SkillSpec) => {
    try {
      if (skill.enabled) {
        await api.disableSkill(skill.name);
        setSkills((prev) =>
          prev.map((s) =>
            s.name === skill.name ? { ...s, enabled: false } : s,
          ),
        );
        message.success("Disabled successfully");
      } else {
        await api.enableSkill(skill.name);
        setSkills((prev) =>
          prev.map((s) =>
            s.name === skill.name ? { ...s, enabled: true } : s,
          ),
        );
        message.success("Enabled successfully");
        await checkScanWarnings(skill.name);
      }
      return true;
    } catch (error) {
      handleError(error, "Operation failed");
      return false;
    }
  };

  const deleteSkill = async (skill: SkillSpec) => {
    const confirmed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: "Confirm Delete",
        content: `Are you sure you want to delete skill "${skill.name}"? This action cannot be undone.`,
        okText: "Delete",
        okType: "danger",
        cancelText: "Cancel",
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });

    if (!confirmed) return false;

    try {
      const result = await api.deleteSkill(skill.name);
      if (result.deleted) {
        message.success("Deleted successfully");
        await fetchSkills();
        return true;
      } else {
        message.error("Failed to delete skill");
        return false;
      }
    } catch (error) {
      console.error("Failed to delete skill", error);
      message.error("Failed to delete skill");
      return false;
    }
  };

  const installFromMarketplace = async (item: MarketplaceItem) => {
    const skillKey = `${item.market_id}/${item.skill_id}`;

    // Check if a skill with the same name is already installed
    const alreadyInstalled = skills.some(
      (s) => s.name === item.skill_id || s.name === item.name,
    );

    let overwrite = false;
    if (alreadyInstalled) {
      const confirmed = await new Promise<boolean>((resolve) => {
        Modal.confirm({
          title: t("skills.overwriteConfirmTitle"),
          content: t("skills.overwriteConfirmContent", { name: item.name }),
          okText: t("skills.overwriteConfirmOk"),
          okType: "danger",
          cancelText: t("skills.overwriteConfirmCancel"),
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        });
      });
      if (!confirmed) return false;
      overwrite = true;
    }

    try {
      setInstallingSkillKey(skillKey);
      const result = await api.installMarketplaceSkill({
        market_id: item.market_id,
        skill_id: item.skill_id,
        enable: true,
        overwrite,
      });
      if (result?.installed) {
        message.success(
          t("skills.installMarketplaceSuccess", { name: result.name }),
        );
        await fetchSkills();
        return true;
      }
      message.error(t("skills.installMarketplaceFailed"));
      return false;
    } catch (error) {
      console.error("Failed to install marketplace skill", error);
      message.error(t("skills.installMarketplaceFailed"));
      return false;
    } finally {
      setInstallingSkillKey(null);
    }
  };

  return {
    skills,
    markets,
    marketplace,
    marketErrors,
    marketMeta,
    loading,
    marketplaceLoading,
    installingSkillKey,
    importing,
    createSkill,
    importFromHub,
    validateMarket,
    saveMarkets,
    fetchMarketplace,
    installFromMarketplace,
    toggleEnabled,
    deleteSkill,
  };
}
