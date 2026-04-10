import { useState, useEffect, useCallback, useRef } from "react";
import { message, Modal } from "@agentscope-ai/design";
import React from "react";
import api from "../../../api";
import { invalidateSkillCache } from "../../../api/modules/skill";
import type { SkillSpec } from "../../../api/types";
import type { SecurityScanErrorResponse } from "../../../api/modules/security";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import { parseErrorDetail } from "../../../utils/error";

type SkillActionResult =
  | { success: true; name?: string; imported?: string[] }
  | { success: false; conflict?: Record<string, any> };

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
    return null;
  }
  return null;
}

export function useSkills() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
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
      const msg =
        error instanceof Error && error.message ? error.message : defaultMsg;
      console.error(defaultMsg, error);
      message.error(msg);
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
        ) {
          return;
        }
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
        return;
      }
    },
    [t],
  );

  const fetchSkills = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listSkills(selectedAgent);
      setSkills(data || []);
    } catch (error) {
      console.error("Failed to load skills", error);
      message.error("Failed to load skills");
    } finally {
      setLoading(false);
    }
  }, [selectedAgent]);

  // Invalidate cache when agent changes
  useEffect(() => {
    invalidateSkillCache({ agentId: selectedAgent });
    void fetchSkills();
  }, [selectedAgent, fetchSkills]);

  const createSkill = async (
    name: string,
    content: string,
    config?: Record<string, unknown>,
    enable?: boolean,
  ): Promise<SkillActionResult> => {
    try {
      const result = await api.createSkill(name, content, config, enable);
      message.success("Created successfully");
      invalidateSkillCache({ agentId: selectedAgent }); // Clear cache after mutation
      await fetchSkills();
      await checkScanWarnings(result.name);
      return { success: true, name: result.name };
    } catch (error) {
      const detail = parseErrorDetail(error);
      if (detail?.suggested_name) {
        return { success: false, conflict: detail };
      }
      handleError(error, "Failed to save");
      return { success: false };
    }
  };

  const uploadSkill = async (
    file: File,
    targetName?: string,
    renameMap?: Record<string, string>,
  ): Promise<SkillActionResult> => {
    try {
      setUploading(true);
      const result = await api.uploadSkill(file, {
        enable: true,
        overwrite: false,
        target_name: targetName,
        rename_map: renameMap,
      });
      if (result?.count > 0) {
        message.success(
          t("skills.uploadSuccess") + `: ${result.imported.join(", ")}`,
        );
        invalidateSkillCache({ agentId: selectedAgent }); // Clear cache after mutation
        await fetchSkills();
        for (const name of result.imported) {
          await checkScanWarnings(name);
        }
      }
      if (!result?.count) {
        message.warning(t("skills.uploadNoChange"));
      }
      await fetchSkills();
      return { success: true, imported: result?.imported || [] };
    } catch (error) {
      const detail = parseErrorDetail(error);
      if (Array.isArray(detail?.conflicts) && detail.conflicts.length > 0) {
        return { success: false, conflict: detail };
      }
      handleError(error, t("skills.uploadFailed"));
      return { success: false };
    } finally {
      setUploading(false);
    }
  };

  const importFromHub = async (
    input: string,
    targetName?: string,
  ): Promise<SkillActionResult> => {
    const text = (input || "").trim();
    if (!text) {
      message.warning("Please provide a hub skill URL");
      return { success: false };
    }
    if (!text.startsWith("http://") && !text.startsWith("https://")) {
      message.warning(
        "Please enter a valid URL starting with http:// or https://",
      );
      return { success: false };
    }
    const timeoutMs = 90_000;
    const pollMs = 1_000;
    const startedAt = Date.now();
    try {
      setImporting(true);
      importCancelReasonRef.current = null;
      const payload = {
        bundle_url: text,
        enable: true,
        overwrite: false,
        target_name: targetName,
      };
      const task = await api.startHubSkillInstall(payload);
      importTaskIdRef.current = task.task_id;

      while (importTaskIdRef.current) {
        const status = await api.getHubSkillInstallStatus(task.task_id);

        if (status.status === "completed" && status.result?.installed) {
          message.success(`Imported skill: ${status.result.name}`);
          invalidateSkillCache({ agentId: selectedAgent }); // Clear cache after mutation
          await fetchSkills();
          if (status.result.name) {
            await checkScanWarnings(status.result.name);
          }
          return { success: true, name: String(status.result.name || "") };
        }

        if (status.status === "failed") {
          if (
            Array.isArray(status.result?.conflicts) &&
            status.result.conflicts.length > 0
          ) {
            return { success: false, conflict: status.result };
          }
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
          return { success: false };
        }

        if (Date.now() - startedAt >= timeoutMs) {
          importCancelReasonRef.current = "timeout";
          await api.cancelHubSkillInstall(task.task_id);
        }

        await new Promise((resolve) => window.setTimeout(resolve, pollMs));
      }

      return { success: false };
    } catch (error) {
      handleError(error, "Import failed");
      return { success: false };
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
      invalidateSkillCache({ agentId: selectedAgent }); // Clear cache after mutation
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
        content: `Are you sure you want to delete skill "${skill.name}"?`,
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
        invalidateSkillCache({ agentId: selectedAgent }); // Clear cache after mutation
        await fetchSkills();
        return true;
      }
    } catch (error) {
      console.error("Failed to delete skill", error);
      message.error("Failed to delete skill");
    }
    return false;
  };

  return {
    skills,
    loading,
    uploading,
    importing,
    createSkill,
    uploadSkill,
    importFromHub,
    cancelImport,
    toggleEnabled,
    deleteSkill,
    refreshSkills: fetchSkills,
  };
}
