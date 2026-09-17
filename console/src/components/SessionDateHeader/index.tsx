import { ChevronDown } from "lucide-react";

import type { ChatDateGroup } from "../../utils/chatGroups";
import styles from "./SessionDateHeader.module.less";

interface SessionDateHeaderProps {
  dateGroup: ChatDateGroup;
  label: string;
  /** Present in the sidebar list, where headers fold their section. */
  collapsed?: boolean;
  onToggle?: () => void;
}

export default function SessionDateHeader({
  dateGroup,
  label,
  collapsed = false,
  onToggle,
}: SessionDateHeaderProps) {
  const interactive = typeof onToggle === "function";

  return (
    <div
      className={`${styles.header} ${interactive ? styles.interactive : ""}`}
      data-date-group={dateGroup}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-expanded={interactive ? !collapsed : undefined}
      onClick={interactive ? onToggle : undefined}
      onKeyDown={
        interactive
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onToggle?.();
              }
            }
          : undefined
      }
    >
      {interactive && (
        <span
          className={`${styles.chevron} ${
            collapsed ? styles.chevronCollapsed : ""
          }`}
        >
          <ChevronDown size={12} />
        </span>
      )}
      <span className={styles.label}>{label}</span>
      <span className={styles.line} />
    </div>
  );
}
