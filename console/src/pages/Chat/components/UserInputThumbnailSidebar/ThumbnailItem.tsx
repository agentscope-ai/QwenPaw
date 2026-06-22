import React, { memo } from "react";
import { Popover } from "antd";
import { useTranslation } from "react-i18next";
import { formatMessageTime } from "../../utils";
import type { UserMessageSnapshot } from "./useUserMessageSnapshot";
import styles from "./index.module.less";

const MAX_THUMBNAIL_CHARS = 25;
const MAX_PREVIEW_CHARS = 200;

interface ThumbnailItemProps {
  snapshot: UserMessageSnapshot;
  active: boolean;
  onClick: () => void;
}

function truncateText(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "…";
}

const PopoverContent: React.FC<{ snapshot: UserMessageSnapshot }> = ({
  snapshot,
}) => {
  const { t } = useTranslation();
  const displayText = snapshot.text.trim()
    ? truncateText(snapshot.text, MAX_PREVIEW_CHARS)
    : `📎 ${t("chat.thumbnailSidebar.attachment")}`;

  return (
    <div className={styles.popoverContent}>
      <div className={styles.popoverHeader}>
        <span className={styles.popoverTitle}>
          {t("chat.thumbnailSidebar.previewTitle")}
        </span>
        {snapshot.createdAt ? (
          <span className={styles.popoverTime}>
            {formatMessageTime(snapshot.createdAt)}
          </span>
        ) : null}
      </div>
      <div className={styles.popoverBody}>{displayText}</div>
    </div>
  );
};

const ThumbnailItem: React.FC<ThumbnailItemProps> = memo(
  ({ snapshot, active, onClick }) => {
    const { t } = useTranslation();
    const displayText = snapshot.text.trim()
      ? truncateText(snapshot.text, MAX_THUMBNAIL_CHARS)
      : `📎 ${t("chat.thumbnailSidebar.attachment")}`;

    return (
      <Popover
        content={<PopoverContent snapshot={snapshot} />}
        placement="left"
        trigger="hover"
        mouseEnterDelay={0.3}
        overlayStyle={{ maxWidth: 280 }}
      >
        <div
          className={`${styles.thumbnailItem} ${active ? styles.thumbnailItemActive : ""}`}
          onClick={onClick}
          role="button"
          tabIndex={0}
          title={t("chat.thumbnailSidebar.gotoMessage")}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") onClick();
          }}
        >
          <span className={styles.thumbnailText}>{displayText}</span>
        </div>
      </Popover>
    );
  },
);

ThumbnailItem.displayName = "ThumbnailItem";

export default ThumbnailItem;
