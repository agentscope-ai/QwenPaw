import React from "react";
import { AlertCircle, Loader2, Terminal } from "lucide-react";
import { useRuntimeStatus } from "./useRuntimeStatus";
import styles from "./index.module.less";

interface RuntimeStatusPanelProps {
  enabled: boolean;
}

function stageLabel(stage: string): string {
  switch (stage) {
    case "agent_starting":
      return "启动中";
    case "waiting_model_first_event":
      return "等待模型";
    case "tool_running":
      return "工具运行中";
    case "tool_timeout":
      return "工具超时";
    case "tool_failed":
      return "工具失败";
    default:
      return "执行中";
  }
}

const RuntimeStatusPanel: React.FC<RuntimeStatusPanelProps> = ({
  enabled,
}) => {
  const { status } = useRuntimeStatus(enabled);

  if (!enabled || !status) return null;

  const failed = status.status === "failed";
  const command = String(status.detail?.command || "");
  const tool = status.detail?.tool ? String(status.detail.tool) : "";

  return (
    <section className={`${styles.panel} ${failed ? styles.failed : ""}`}>
      <div className={styles.header}>
        <div className={styles.title}>
          {failed ? <AlertCircle size={15} /> : <Loader2 size={15} />}
          <span>{stageLabel(status.stage)}</span>
        </div>
        {tool && (
          <span className={styles.tool}>
            <Terminal size={13} />
            {tool}
          </span>
        )}
      </div>
      <div className={styles.message}>
        {status.message || "任务仍在执行，请稍候。"}
      </div>
      {command && <div className={styles.command}>{command}</div>}
    </section>
  );
};

export default RuntimeStatusPanel;
