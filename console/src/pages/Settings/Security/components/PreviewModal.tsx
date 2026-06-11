import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { useTranslation } from "react-i18next";
import type { ToolGuardRule } from "../../../../api/modules/security";

const SEVERITY_VARIANT: Record<string, { className: string }> = {
  CRITICAL: {
    className:
      "border-red-400 text-red-600 bg-red-50 dark:bg-red-950 dark:text-red-400",
  },
  HIGH: {
    className:
      "border-orange-400 text-orange-600 bg-orange-50 dark:bg-orange-950 dark:text-orange-400",
  },
  MEDIUM: {
    className:
      "border-yellow-400 text-yellow-600 bg-yellow-50 dark:bg-yellow-950 dark:text-yellow-400",
  },
  LOW: {
    className:
      "border-blue-400 text-blue-600 bg-blue-50 dark:bg-blue-950 dark:text-blue-400",
  },
  INFO: { className: "" },
};

interface PreviewModalProps {
  rule: ToolGuardRule | null;
  onClose: () => void;
}

export function PreviewModal({ rule, onClose }: PreviewModalProps) {
  const { t } = useTranslation();
  const preClass = "bg-muted text-foreground border border-border";

  return (
    <Dialog
      open={!!rule}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <DialogContent className="max-w-[640px]">
        <DialogHeader>
          <DialogTitle>{t("security.rules.previewTitle")}</DialogTitle>
        </DialogHeader>

        {rule && (
          <div className="mt-2 flex flex-col gap-2 text-sm">
            <p>
              <strong>{t("security.rules.ruleId")}:</strong> {rule.id}
            </p>
            <p className="flex items-center gap-2">
              <strong>{t("security.rules.severityLabel")}:</strong>
              <Badge
                variant="outline"
                className={`text-xs ${
                  SEVERITY_VARIANT[rule.severity]?.className ?? ""
                }`}
              >
                {rule.severity}
              </Badge>
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
            <p className="flex items-center gap-2">
              <strong>{t("security.rules.actionLabel")}:</strong>
              <Badge
                variant="outline"
                className="text-xs border-border text-foreground"
              >
                {t("security.rules.actionApproval")}
              </Badge>
            </p>
            <p className="whitespace-pre-wrap break-words">
              <strong>{t("security.rules.descriptionLabel")}:</strong>{" "}
              {t(`security.rules.descriptions.${rule.id}`, {
                defaultValue: "",
              }) || rule.description}
            </p>
            <p>
              <strong>{t("security.rules.patterns")}:</strong>
            </p>
            <pre className={`rounded-md p-3 text-[13px] font-mono ${preClass}`}>
              {rule.patterns.join("\n")}
            </pre>
            {rule.exclude_patterns.length > 0 && (
              <>
                <p>
                  <strong>{t("security.rules.excludePatterns")}:</strong>
                </p>
                <pre
                  className={`rounded-md p-3 text-[13px] font-mono ${preClass}`}
                >
                  {rule.exclude_patterns.join("\n")}
                </pre>
              </>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
