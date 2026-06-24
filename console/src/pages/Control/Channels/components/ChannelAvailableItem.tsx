import React from "react";
import { useTranslation } from "react-i18next";
import { ChannelIcon } from "./ChannelIcon";
import { getChannelLabel, type ChannelKey } from "./constants";
import styles from "../index.module.less";

interface ChannelAvailableItemProps {
  channelKey: ChannelKey;
  onClick: () => void;
}

export const ChannelAvailableItem = React.memo(function ChannelAvailableItem({
  channelKey,
  onClick,
}: ChannelAvailableItemProps) {
  const { t } = useTranslation();
  const label = getChannelLabel(channelKey, t);

  return (
    <div className={styles.availableItem} onClick={onClick}>
      <ChannelIcon channelKey={channelKey} size={24} />
      <span className={styles.availableItemName}>{label}</span>
      <span className={styles.availableItemAction}>
        {t("channels.enableAction")}
      </span>
    </div>
  );
});
