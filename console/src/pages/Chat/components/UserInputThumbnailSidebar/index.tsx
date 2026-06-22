import React, { useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { IAgentScopeRuntimeWebUIRef } from "@agentscope-ai/chat";
import { useUserMessageSnapshot } from "./useUserMessageSnapshot";
import { useActiveUserMessageIndex } from "./useActiveUserMessageIndex";
import ThumbnailItem from "./ThumbnailItem";
import styles from "./index.module.less";

const USER_BUBBLE_SELECTOR = '[class*="bubble-end"]';

interface UserInputThumbnailSidebarProps {
  /** Same ref passed to AgentScopeRuntimeWebUI */
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>;
  /** Whether the sidebar is visible (controlled externally) */
  visible?: boolean;
}

const UserInputThumbnailSidebar: React.FC<UserInputThumbnailSidebarProps> = ({
  chatRef,
  visible = true,
}) => {
  const { t } = useTranslation();
  const { snapshots } = useUserMessageSnapshot(chatRef);
  const activeIndex = useActiveUserMessageIndex(snapshots.length);

  const handleClick = useCallback((index: number) => {
    const scrollContainer = document.querySelector(
      '[class*="chatMessagesArea"]',
    );
    if (!scrollContainer) return;

    const bubbles = scrollContainer.querySelectorAll(USER_BUBBLE_SELECTOR);
    const target = bubbles[index];
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, []);

  if (!visible) return null;

  return (
    <div className={styles.sidebarRoot}>
      {snapshots.length === 0 ? (
        <div className={styles.emptyState}>
          <span className={styles.emptyText}>
            {t("chat.thumbnailSidebar.noMessages")}
          </span>
        </div>
      ) : (
        <div className={styles.thumbnailList}>
          {snapshots.map((snap) => (
            <ThumbnailItem
              key={snap.id}
              snapshot={snap}
              active={activeIndex === snap.index}
              onClick={() => handleClick(snap.index)}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default UserInputThumbnailSidebar;
