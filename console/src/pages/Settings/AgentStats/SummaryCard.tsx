import { Card, CardContent } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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
      <CardContent className="p-3">
        <div className={styles.cardValue}>{formatCompact(value ?? 0)}</div>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className={styles.cardLabel}>{label}</div>
          </TooltipTrigger>
          <TooltipContent side="bottom">{tooltip}</TooltipContent>
        </Tooltip>
      </CardContent>
    </Card>
  );
}
