import React from "react";
import { useTranslation } from "react-i18next";
import { ChannelIcon } from "./ChannelIcon";
import { getChannelLabel, type ChannelKey } from "./constants";
import type { ChannelDependencyStatus } from "../../../../api/modules/channel";
import styles from "../index.module.less";

interface ChannelAvailableItemProps {
  channelKey: ChannelKey;
  onClick: () => void;
  iconUrl?: string;
  dependencyStatus?: ChannelDependencyStatus;
  dependencyCheckState?: "ready" | "checking" | "failed";
}

export const ChannelAvailableItem = React.memo(function ChannelAvailableItem({
  channelKey,
  onClick,
  iconUrl,
  dependencyStatus,
  dependencyCheckState = "ready",
}: ChannelAvailableItemProps) {
  const { t } = useTranslation();
  const label = getChannelLabel(channelKey, t);
  const status = dependencyStatus?.status ?? "ready";
  const disabled =
    dependencyCheckState !== "ready" ||
    status === "installing" ||
    status === "platform_unsupported" ||
    status === "load_error";
  const actionLabel =
    dependencyCheckState === "checking"
      ? t("channels.dependencyCheckingAction")
      : dependencyCheckState === "failed"
      ? t("channels.dependencyCheckFailedAction")
      : status === "missing"
      ? t("channels.installAction")
      : status === "failed"
      ? t("channels.retryInstallAction")
      : status === "installing"
      ? t("channels.installingAction")
      : status === "platform_unsupported"
      ? t("channels.macosOnlyAction")
      : status === "load_error"
      ? t("channels.loadFailedAction")
      : t("channels.enableAction");

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!disabled) onClick();
    }
  };

  return (
    <div
      className={styles.availableItem}
      onClick={disabled ? undefined : onClick}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
    >
      <ChannelIcon channelKey={channelKey} size={24} iconUrl={iconUrl} />
      <span className={styles.availableItemName}>{label}</span>
      <span className={styles.availableItemAction}>{actionLabel}</span>
    </div>
  );
});
