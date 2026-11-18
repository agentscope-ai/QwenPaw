import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import type { AgentStartupStatus } from "@/api/types/agents";
import { resolveAgentStatus } from "./status";
import styles from "./index.module.less";

interface AgentStatusIndicatorProps {
  status?: AgentStartupStatus;
  enabled?: boolean;
}

export function AgentStatusIndicator({
  status,
  enabled = true,
}: AgentStatusIndicatorProps) {
  const { t } = useTranslation();
  const resolvedStatus = resolveAgentStatus(status, enabled);
  const label = t(`agent.status.${resolvedStatus}`);

  return (
    <Tooltip title={label}>
      <span
        className={`${styles.indicator} ${styles[resolvedStatus]}`}
        role="status"
        aria-label={label}
        data-status={resolvedStatus}
      />
    </Tooltip>
  );
}
