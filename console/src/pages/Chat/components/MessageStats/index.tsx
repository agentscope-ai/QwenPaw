import React from "react";
import { Tooltip } from "antd";
import { BarChartOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { IconButton } from "@agentscope-ai/design";
import styles from "./index.module.less";

export interface MessageStatsProps {
  /** Total duration in seconds (computed from backend created_at / completed_at). */
  durationSeconds?: number | null;
}

function formatDuration(seconds: number): string {
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)}ms`;
  }
  return `${seconds.toFixed(2)}s`;
}

const MessageStats: React.FC<MessageStatsProps> = ({ durationSeconds }) => {
  const { t } = useTranslation();

  if (typeof durationSeconds !== "number" || durationSeconds <= 0) {
    return null;
  }

  const tooltipContent = (
    <div className={styles.statsTooltip}>
      <div className={styles.statsRow}>
        <span className={styles.statsLabel}>{t("chat.stats.totalTime")}:</span>
        <span className={styles.statsValue}>
          {formatDuration(durationSeconds)}
        </span>
      </div>
    </div>
  );

  return (
    <Tooltip title={tooltipContent} placement="top">
      <IconButton bordered={false} icon={<BarChartOutlined />} />
    </Tooltip>
  );
};

export default MessageStats;
