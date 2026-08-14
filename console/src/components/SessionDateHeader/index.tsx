import type { ChatDateGroup } from "../../utils/chatGroups";
import styles from "./SessionDateHeader.module.less";

interface SessionDateHeaderProps {
  dateGroup: ChatDateGroup;
  label: string;
}

export default function SessionDateHeader({
  dateGroup,
  label,
}: SessionDateHeaderProps) {
  return (
    <div className={styles.header} data-date-group={dateGroup}>
      <span>{label}</span>
      <span className={styles.line} />
    </div>
  );
}
