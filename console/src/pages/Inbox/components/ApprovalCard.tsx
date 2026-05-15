import { Card, Button, Tag } from "antd";
import { Terminal, FileText, Settings, Check, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ApprovalItem } from "../types";
import styles from "./ApprovalCard.module.less";

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

const PRIORITY_COLORS = {
  low: "default",
  normal: "processing",
  high: "warning",
  urgent: "error",
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
      className={`${styles.approvalCard} ${
        styles[`priority-${approval.priority}`]
      }`}
      hoverable
      bodyStyle={{ padding: 14 }}
    >
      <div className={styles.cardHeader}>
        <div className={styles.typeInfo}>
          <div className={styles.iconWrapper}>
            <IconComponent size={18} />
          </div>
          <div>
            <div className={styles.typeLabel}>{TYPE_LABELS[approval.type]}</div>
            <div className={styles.requestedBy}>
              {t("inbox.requestedBy")} {approval.requestedBy}
            </div>
          </div>
        </div>
        <Tag color={PRIORITY_COLORS[approval.priority]}>
          {approval.priority.toUpperCase()}
        </Tag>
      </div>
      <div className={styles.cardBody}>
        <h4 className={styles.title}>{approval.title}</h4>
        <p className={styles.description}>{approval.description}</p>
      </div>
      <div className={styles.cardFooter}>
        <span className={styles.timestamp}>{timeText}</span>
        <div className={styles.actions}>
          <Button
            danger
            icon={<X size={16} />}
            onClick={() => onReject(approval.id)}
          >
            {t("inbox.reject")}
          </Button>
          <Button
            type="primary"
            icon={<Check size={16} />}
            onClick={() => onApprove(approval.id)}
          >
            {t("inbox.approve")}
          </Button>
        </div>
      </div>
    </Card>
  );
}
