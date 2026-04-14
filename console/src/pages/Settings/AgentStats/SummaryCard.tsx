import { Card } from "@agentscope-ai/design";
import { Tooltip } from "antd";
import { formatCompact } from "../../../utils/formatNumber";
import styles from "./index.module.less";

interface SummaryCardProps {
  value: number | null | undefined;
  label: string;
  tooltip: string;
}

export function SummaryCard({ value, label, tooltip }: SummaryCardProps) {
  return (
    <Card className={styles.card}>
      <div className={styles.cardValue}>{formatCompact(value ?? 0)}</div>
      <Tooltip title={tooltip} placement="bottom">
        <div className={styles.cardLabel}>{label}</div>
      </Tooltip>
    </Card>
  );
}
