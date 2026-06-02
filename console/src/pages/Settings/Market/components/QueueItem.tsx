import { memo, useCallback } from "react";
import { Button } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { InstallQueueItem } from "../useMarketInstall";
import { sourceLabel } from "./SkillIcon";
import styles from "./QueueItem.module.less";

interface QueueItemProps {
  item: InstallQueueItem;
  /** Accepts item id so parent can pass a stable reference */
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
}

export const QueueItem = memo(function QueueItem({
  item,
  onCancel,
  onRetry,
}: QueueItemProps) {
  const { t } = useTranslation();

  const isTerminal =
    item.status === "completed" ||
    item.status === "failed" ||
    item.status === "cancelled";
  const canCancel =
    !isTerminal && !(item.target === "pool" && item.status === "installing");
  const canRetry = item.status === "failed" || item.status === "cancelled";
  const targetLabel = t(
    item.target === "pool" ? "market.targetPool" : "market.targetWorkspace",
  );

  const handleCancel = useCallback(
    () => onCancel(item.id),
    [onCancel, item.id],
  );
  const handleRetry = useCallback(() => onRetry(item.id), [onRetry, item.id]);

  let displayMessage = "";
  if (item.message === "__TIMED_OUT__") {
    displayMessage = t("market.queueMsg.timedOut");
  } else if (item.message) {
    displayMessage =
      item.status === "failed"
        ? t("market.queueMsg.failedPrefix", { msg: item.message })
        : item.message;
  }

  return (
    <div className={styles.queueItem}>
      <div className={styles.queueItemTop}>
        <strong>{item.result.name}</strong>
        <span className={`${styles.statusTag} ${styles[item.status]}`}>
          {t(`market.status.${item.status}`)}
        </span>
      </div>
      <div className={styles.queueItemMeta}>
        {sourceLabel(item.result.source)} → {targetLabel}
      </div>
      {displayMessage && (
        <div className={styles.queueItemMessage}>{displayMessage}</div>
      )}
      <div className={styles.queueItemActions}>
        {canCancel && (
          <Button size="small" onClick={handleCancel}>
            {t("common.cancel")}
          </Button>
        )}
        {canRetry && (
          <Button size="small" type="primary" onClick={handleRetry}>
            {t("market.retry")}
          </Button>
        )}
      </div>
    </div>
  );
});
