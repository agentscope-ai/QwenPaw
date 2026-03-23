import { Modal, Button, Tag } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { ToolGuardRule } from "../../../../api/modules/security";
import { useTheme } from "../../../../contexts/ThemeContext";

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "red",
  HIGH: "orange",
  MEDIUM: "gold",
  LOW: "blue",
  INFO: "default",
};

interface PreviewModalProps {
  rule: ToolGuardRule | null;
  onClose: () => void;
}

export function PreviewModal({ rule, onClose }: PreviewModalProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();

  if (!rule) return null;

  const preStyle: React.CSSProperties = {
    background: isDark ? "#1a1a1a" : "#f5f5f5",
    color: isDark ? "rgba(255,255,255,0.85)" : "#333",
    padding: 12,
    borderRadius: 6,
    fontSize: 13,
    border: isDark ? "1px solid rgba(255,255,255,0.12)" : "1px solid #e8e8e8",
  };

  return (
    <Modal
      title={t("security.rules.previewTitle")}
      open={!!rule}
      onCancel={onClose}
      footer={<Button onClick={onClose}>{t("common.close")}</Button>}
      width={640}
    >
      <div style={{ marginTop: 16 }}>
        <p>
          <strong>{t("security.rules.ruleId")}:</strong> {rule.id}
        </p>
        <p>
          <strong>{t("security.rules.severityLabel")}:</strong>{" "}
          <Tag color={SEVERITY_COLORS[rule.severity] ?? "default"}>
            {rule.severity}
          </Tag>
        </p>
        <p>
          <strong>{t("security.rules.tools")}:</strong>{" "}
          {rule.tools.length > 0
            ? rule.tools.join(", ")
            : t("security.rules.allTools")}
        </p>
        <p>
          <strong>{t("security.rules.params")}:</strong>{" "}
          {rule.params.length > 0
            ? rule.params.join(", ")
            : t("security.rules.allParams")}
        </p>
        <p>
          <strong>{t("security.rules.actionLabel")}:</strong>{" "}
          <Tag color="orange">{t("security.rules.actionApproval")}</Tag>
        </p>
        <p style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          <strong>{t("security.rules.descriptionLabel")}:</strong>{" "}
          {t(`security.rules.descriptions.${rule.id}`, {
            defaultValue: "",
          }) || rule.description}
        </p>
        <p>
          <strong>{t("security.rules.patterns")}:</strong>
        </p>
        <pre style={preStyle}>{rule.patterns.join("\n")}</pre>
        {rule.exclude_patterns.length > 0 && (
          <>
            <p>
              <strong>{t("security.rules.excludePatterns")}:</strong>
            </p>
            <pre style={preStyle}>{rule.exclude_patterns.join("\n")}</pre>
          </>
        )}
      </div>
    </Modal>
  );
}
