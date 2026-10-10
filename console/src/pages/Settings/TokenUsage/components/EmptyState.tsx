import { ChartNoAxesCombined } from "lucide-react";
import styles from "../index.module.less";

interface EmptyStateProps {
  message: string;
  className?: string;
}

export function EmptyState({ message, className }: EmptyStateProps) {
  return (
    <div className={`${styles.emptyState} ${className ?? ""}`}>
      <ChartNoAxesCombined className={styles.emptyIcon} size={32} aria-hidden />
      <span>{message}</span>
    </div>
  );
}
