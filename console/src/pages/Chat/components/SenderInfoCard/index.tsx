import React from "react";
import styles from "./index.module.less";

interface SenderInfoCardProps {
  data: {
    name: string;
    role: "user" | "assistant" | string;
    timestamp: string | null;
  };
}

/**
 * CoPawSenderInfoCard — displays sender name and message timestamp
 * in the conversation history.
 *
 * Rendered as a custom card before each AgentScopeRuntimeRequestCard
 * or AgentScopeRuntimeResponseCard.
 */
const SenderInfoCard: React.FC<SenderInfoCardProps> = ({ data }) => {
  const { name, timestamp } = data;

  const formattedTime = React.useMemo(() => {
    if (!timestamp) return null;
    try {
      const date = new Date(timestamp);
      if (isNaN(date.getTime())) return null;
      return date.toLocaleString(undefined, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
    } catch {
      return null;
    }
  }, [timestamp]);

  return (
    <div className={styles.senderInfo}>
      <span className={styles.senderName}>{name}</span>
      {formattedTime && (
        <span className={styles.timestamp}>{formattedTime}</span>
      )}
    </div>
  );
};

export default SenderInfoCard;
