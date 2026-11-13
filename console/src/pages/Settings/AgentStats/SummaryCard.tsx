import { Card } from "@agentscope-ai/design";
import { Tooltip } from "antd";
import { formatCompact } from "../../../utils/formatNumber";
import styles from "./index.module.less";

interface SummaryCardProps {
  value: number | null | undefined;
  label: string;
  tooltip: string;
  formatValue?: (value: number | null | undefined) => string;
}

export function SummaryCard({
  value,
  label,
  tooltip,
  formatValue = (current) => formatCompact(current ?? 0),
}: SummaryCardProps) {
  return (
    <Card className={styles.card}>
      <div className={styles.cardValue}>{formatValue(value)}</div>
      <Tooltip title={tooltip} placement="bottom">
        <div className={styles.cardLabel}>{label}</div>
      </Tooltip>
    </Card>
  );
}
