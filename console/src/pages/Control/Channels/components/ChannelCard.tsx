import { Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import React, { useState } from "react";
import { getChannelIconUrl } from "./channelIcons";
import { getChannelLabel, type ChannelKey } from "./constants";
import styles from "../index.module.less";

interface ChannelCardProps {
  channelKey: ChannelKey;
  config: Record<string, unknown>;
  onClick: () => void;
}

export const ChannelCard = React.memo(function ChannelCard({
  channelKey,
  config,
  onClick,
}: ChannelCardProps) {
  const { t } = useTranslation();
  const [isHover, setIsHover] = useState(false);
  const enabled = Boolean(config.enabled);
  const isBuiltin = Boolean(config.isBuiltin);
  const label = getChannelLabel(channelKey, t);
  const getConfigString = (key: string) =>
    typeof config[key] === "string" ? config[key] : "";
  const botPrefix = getConfigString("bot_prefix");

  const getChannelIcon = () => (
    <img
      src={getChannelIconUrl(channelKey)}
      alt={channelKey}
      width={32}
      height={32}
    />
  );

  const getCardClassNames = () => {
    if (isHover) return `${styles.channelCard} ${styles.hover}`;
    if (enabled) return `${styles.channelCard} ${styles.enabled}`;
    return `${styles.channelCard} ${styles.normal}`;
  };

  return (
    <Card
      hoverable
      onClick={onClick}
      onMouseEnter={() => setIsHover(true)}
      onMouseLeave={() => setIsHover(false)}
      className={getCardClassNames()}
      bodyStyle={{ padding: 24 }}
    >
      {/* Top section: Icon and Status */}
      <div className={styles.cardTopSection}>
        <div className={styles.channelIcon}>{getChannelIcon()}</div>
        <div className={styles.statusIndicator}>
          <div
            className={`${styles.statusDot} ${
              enabled ? styles.enabled : styles.disabled
            }`}
          />
          <span
            className={`${styles.statusText} ${
              enabled ? styles.enabled : styles.disabled
            }`}
          >
            {enabled ? t("common.enabled") : t("common.disabled")}
          </span>
        </div>
      </div>

      {/* Middle section: Name and Tag */}
      <div className={styles.cardMiddleSection}>
        <div className={styles.cardTitle}>{label}</div>
        {isBuiltin ? (
          <span className={styles.builtinTag}>{t("channels.builtin")}</span>
        ) : (
          <span className={styles.customTag}>{t("channels.custom")}</span>
        )}
      </div>

      {/* Bottom section: Bot Prefix */}
      <div className={styles.cardBottomSection}>
        <div className={styles.cardDescription}>
          {t("channels.botPrefix")}: {botPrefix || t("channels.notSet")}
        </div>
      </div>
    </Card>
  );
});
