import React from "react";
import { useTranslation } from "react-i18next";
import { ChannelIcon } from "./ChannelIcon";
import { getChannelLabel, type ChannelKey } from "./constants";
import styles from "../index.module.less";

interface ChannelAvailableItemProps {
  channelKey: ChannelKey;
  onClick: () => void;
  iconUrl?: string;
}

export const ChannelAvailableItem = React.memo(function ChannelAvailableItem({
  channelKey,
  onClick,
  iconUrl,
}: ChannelAvailableItemProps) {
  const { t } = useTranslation();
  const label = getChannelLabel(channelKey, t);

  return (
    <button
      type="button"
      data-press
      className={styles.availableItem}
      onClick={onClick}
    >
      <ChannelIcon channelKey={channelKey} size={24} iconUrl={iconUrl} />
      <span className={styles.availableItemName}>{label}</span>
      <span className={styles.availableItemAction}>
        {t("channels.configureAction")}
      </span>
    </button>
  );
});
