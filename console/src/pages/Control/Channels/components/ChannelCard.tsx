import { Card, Tooltip } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { getChannelLabel, type ChannelKey } from "./constants";
import styles from "../index.module.less";

interface ChannelCardProps {
  channelKey: ChannelKey;
  config: Record<string, unknown>;
  isHover: boolean;
  onClick: () => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function ChannelCard({
  channelKey,
  config,
  isHover,
  onClick,
  onMouseEnter,
  onMouseLeave,
}: ChannelCardProps) {
  const { t } = useTranslation();
  const enabled = Boolean(config.enabled);
  const isBuiltin = Boolean(config.isBuiltin);
  const label = getChannelLabel(channelKey);
  const getConfigString = (key: string) =>
    typeof config[key] === "string" ? config[key] : "";
  const phoneNumber = getConfigString("phone_number");
  const botPrefix = getConfigString("bot_prefix");

  const getCardClassNames = () => {
    if (isHover) return `${styles.channelCard} ${styles.hover}`;
    if (enabled) return `${styles.channelCard} ${styles.enabled}`;
    return `${styles.channelCard} ${styles.normal}`;
  };

  return (
    <Card
      hoverable
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={getCardClassNames()}
      bodyStyle={{ padding: 20 }}
    >
      <div className={styles.cardHeader}>
        <Tooltip title={label} placement="top">
          <div className={styles.cardTitleRow}>
            <div className={styles.cardTitle}>{label}</div>
            {isBuiltin ? (
              <span className={styles.builtinTag}>{t("channels.builtin")}</span>
            ) : (
              <span className={styles.customTag}>{t("channels.custom")}</span>
            )}
          </div>
        </Tooltip>

        <div className={styles.statusContainer}>
          <div
            className={`${styles.statusDot} ${
              enabled ? styles.enabled : styles.disabled
            }`}
          />
          <div>{enabled ? t("common.enabled") : t("common.disabled")}</div>
        </div>
      </div>

      <div className={styles.cardDescription}>
        {channelKey === "voice" ? (
          <>
            {t("channels.phoneNumber")}: {phoneNumber || t("channels.notSet")}
          </>
        ) : (
          <>
            {t("channels.botPrefix")}: {botPrefix || t("channels.notSet")}
          </>
        )}
      </div>

      <div className={styles.cardFooter}>
        <span className={styles.cardHint}>{t("channels.clickCardToEdit")}</span>
      </div>
    </Card>
  );
}
