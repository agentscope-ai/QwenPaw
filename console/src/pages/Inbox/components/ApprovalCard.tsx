import { Terminal, FileText, Settings, Check, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ApprovalItem } from "../types";

interface ApprovalCardProps {
  approval: ApprovalItem;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}

const TYPE_ICONS = {
  tool_call: Terminal,
  config_change: Settings,
  file_access: FileText,
};

const TYPE_LABELS = {
  tool_call: "Tool Call",
  config_change: "Config Change",
  file_access: "File Access",
};

const PRIORITY_BADGE_CLASS: Record<string, string> = {
  low: "bg-secondary text-secondary-foreground border-0",
  normal:
    "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400 border-0",
  high: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400 border-0",
  urgent: "bg-destructive/10 text-destructive border-0",
};

export function ApprovalCard({
  approval,
  onApprove,
  onReject,
}: ApprovalCardProps) {
  const { t } = useTranslation();
  const IconComponent = TYPE_ICONS[approval.type];
  const timeText = approval.requestedAt.toLocaleString();

  return (
    <Card
      className={cn(
        "rounded-2xl shadow-sm hover:shadow-md transition-shadow cursor-pointer",
        approval.priority === "urgent" && "border-destructive/50",
        approval.priority === "high" && "border-orange-400/50",
      )}
    >
      <CardContent className="p-3.5 flex flex-col gap-0">
        <div className="flex justify-between items-start gap-3">
          <div className="flex gap-3 min-w-0">
            <div className="w-[34px] h-[34px] rounded-lg flex items-center justify-center bg-muted shrink-0">
              <IconComponent size={18} className="text-muted-foreground" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">
                {TYPE_LABELS[approval.type]}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {t("inbox.requestedBy")} {approval.requestedBy}
              </div>
            </div>
          </div>
          <Badge
            variant="secondary"
            className={cn(
              "text-[11px] font-semibold shrink-0",
              PRIORITY_BADGE_CLASS[approval.priority] ??
                PRIORITY_BADGE_CLASS["normal"],
            )}
          >
            {approval.priority.toUpperCase()}
          </Badge>
        </div>

        <div className="mt-3.5">
          <h4 className="text-sm font-semibold text-foreground mb-2 leading-snug">
            {approval.title}
          </h4>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {approval.description}
          </p>
        </div>

        <div className="mt-3.5 flex justify-between items-center">
          <span className="text-xs text-muted-foreground">{timeText}</span>
          <div className="flex gap-2.5">
            <Button
              variant="outline"
              size="sm"
              className="text-destructive border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
              onClick={() => onReject(approval.id)}
            >
              <X size={14} />
              {t("inbox.reject")}
            </Button>
            <Button
              size="sm"
              className="bg-orange-500 hover:bg-orange-600 text-white border-0"
              onClick={() => onApprove(approval.id)}
            >
              <Check size={14} />
              {t("inbox.approve")}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
