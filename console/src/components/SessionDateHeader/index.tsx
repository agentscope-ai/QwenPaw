import { ChevronDown } from "lucide-react";

import type { ChatDateGroup } from "../../utils/chatGroups";
import styles from "./SessionDateHeader.module.less";

interface SessionDateHeaderProps {
  dateGroup: ChatDateGroup;
  label: string;
  count: number;
  collapsed?: boolean;
  onToggle: () => void;
}

/**
 * Collapsible section header for date groups. Mirrors the group
 * header chip (geometry, hover, chevron, label and count pill) so
 * both grouping modes read as the same control family.
 */
export default function SessionDateHeader({
  dateGroup,
  label,
  count,
  collapsed = false,
  onToggle,
}: SessionDateHeaderProps) {
  return (
    <div
      className={styles.header}
      data-date-group={dateGroup}
      role="button"
      tabIndex={0}
      aria-expanded={!collapsed}
      onClick={onToggle}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onToggle();
        }
      }}
    >
      <span
        className={`${styles.chevron} ${collapsed ? styles.collapsed : ""}`}
      >
        <ChevronDown size={13} />
      </span>
      <span className={styles.label}>{label}</span>
      <span className={styles.count}>{count}</span>
    </div>
  );
}
