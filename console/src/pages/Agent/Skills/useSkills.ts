import { useState, useEffect, useCallback, useRef } from "react";
import { message, Modal } from "@agentscope-ai/design";
import React from "react";
import api from "../../../api";
import type { SkillSpec } from "../../../api/types";
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
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const importTaskIdRef = useRef<string | null>(null);
  const importCancelReasonRef = useRef<"manual" | "timeout" | null>(null);

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
      await fetchSkills();
    };

    if (mounted) {
      loadSkills();
    }

    return () => {
      mounted = false;
    };
  }, [selectedAgent]);

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
    const timeoutMs = 90_000;
    const pollMs = 1_000;
    const startedAt = Date.now();
    try {
      setImporting(true);
      importCancelReasonRef.current = null;
      const payload = { bundle_url: text, enable: true, overwrite: false };
      const task = await api.startHubSkillInstall(payload);
      importTaskIdRef.current = task.task_id;

      while (importTaskIdRef.current) {
        const status = await api.getHubSkillInstallStatus(task.task_id);

        if (status.status === "completed" && status.result?.installed) {
          message.success(`Imported skill: ${status.result.name}`);
          await fetchSkills();
          if (status.result.name) await checkScanWarnings(status.result.name);
          return true;
        }

        if (status.status === "failed") {
          throw new Error(status.error || "Import failed");
        }

        if (status.status === "cancelled") {
          message.warning(
            t(
              importCancelReasonRef.current === "timeout"
                ? "skills.importTimeout"
                : "skills.importCancelled",
            ),
          );
          return false;
        }

        if (Date.now() - startedAt >= timeoutMs) {
          importCancelReasonRef.current = "timeout";
          await api.cancelHubSkillInstall(task.task_id);
        }

        await new Promise((resolve) => window.setTimeout(resolve, pollMs));
      }

      return false;
    } catch (error) {
      handleError(error, "Import failed");
      return false;
    } finally {
      importTaskIdRef.current = null;
      importCancelReasonRef.current = null;
      setImporting(false);
    }
  };

  const cancelImport = useCallback(() => {
    if (!importing) return;
    importCancelReasonRef.current = "manual";
    const taskId = importTaskIdRef.current;
    if (!taskId) return;
    void api.cancelHubSkillInstall(taskId);
  }, [importing]);

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

  return {
    skills,
    loading,
    importing,
    cancelImport,
    createSkill,
    importFromHub,
    toggleEnabled,
    deleteSkill,
  };
}
