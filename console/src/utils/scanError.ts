import { Modal } from "@agentscope-ai/design";
import React from "react";
import type {
  SecurityScanErrorResponse,
  BlockedSkillFinding,
  BlockedSkillRecord,
  SkillScannerConfig,
} from "../api/modules/security";
import type { TFunction } from "i18next";

export function tryParseScanError(
  error: unknown,
): SecurityScanErrorResponse | null {
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

/** Cap long finding lists so modals stay readable; full history remains in alerts. */
const MAX_FINDINGS_IN_MODAL = 5;

function renderFindings(findings: BlockedSkillFinding[], t: TFunction) {
  const total = findings.length;
  const shown = findings.slice(0, MAX_FINDINGS_IN_MODAL);
  const moreCount = total - shown.length;
  return React.createElement(
    "div",
    { style: { maxHeight: 300, overflow: "auto", marginTop: 8 } },
    shown.map((f, i) =>
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
    moreCount > 0 &&
      React.createElement(
        "div",
        {
          key: "more",
          style: {
            fontSize: 12,
            color: "#888",
            marginTop: 8,
            padding: "8px 12px",
          },
        },
        t("security.skillScanner.scanError.moreFindings", { count: moreCount }),
      ),
  );
}

export function showScanErrorModal(
  scanError: SecurityScanErrorResponse,
  t: TFunction,
) {
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
      renderFindings(findings, t),
    ),
  });
}

export function showScanWarnModal(
  findings: BlockedSkillFinding[],
  t: TFunction,
) {
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
      renderFindings(findings, t),
    ),
  });
}

/**
 * Check an error for a scan failure, show the modal if found, and return
 * whether it was handled.
 */
export function handleScanError(error: unknown, t: TFunction): boolean {
  const scanError = tryParseScanError(error);
  if (scanError) {
    showScanErrorModal(scanError, t);
    return true;
  }
  return false;
}

/**
 * After a successful operation, check if the scanner recorded any
 * warn-mode findings and show a warning modal if so.
 */
export async function checkScanWarnings(
  skillName: string,
  fetchAlerts: () => Promise<BlockedSkillRecord[]>,
  fetchScannerCfg: () => Promise<SkillScannerConfig>,
  t: TFunction,
): Promise<void> {
  try {
    const [alerts, scannerCfg] = await Promise.all([
      fetchAlerts(),
      fetchScannerCfg(),
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
    showScanWarnModal(latestForSkill.findings || [], t);
  } catch {
    // best-effort; don't break the caller on failure
  }
}
