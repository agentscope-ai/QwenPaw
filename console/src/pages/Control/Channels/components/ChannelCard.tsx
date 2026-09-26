import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import { Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import React from "react";
import { ArrowUpRight } from "lucide-react";
import { ChannelIcon } from "./ChannelIcon";
import { getChannelLabel, type ChannelKey } from "./constants";
import styles from "../index.module.less";

interface ChannelCardProps {
  channelKey: ChannelKey;
  config: Record<string, unknown>;
  onClick: () => void;
  iconUrl?: string;
}

export const ChannelCard = React.memo(function ChannelCard({
  channelKey,
  config,
  onClick,
  iconUrl,
}: ChannelCardProps) {
  const { t } = useTranslation();
  const enabled = Boolean(config.enabled);
  const isBuiltin = Boolean(config.isBuiltin);
  const label = getChannelLabel(channelKey, t);
  const getConfigString = (key: string) =>
    typeof config[key] === "string" ? config[key] : "";
  const botPrefix = getConfigString("bot_prefix");

  const getChannelIcon = () => (
    <ChannelIcon channelKey={channelKey} size={32} iconUrl={iconUrl} />
  );

  return (
    <InteractiveCard tilt={2} className={styles.channelSurface}>
      <Card
        onClick={onClick}
        role="button"
        tabIndex={0}
        aria-label={label}
        onKeyDown={(event) => {
          if (
            event.target === event.currentTarget &&
            ["Enter", " "].includes(event.key)
          ) {
            event.preventDefault();
            onClick();
          }
        }}
        className={styles.channelCard}
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
          <span className={styles.configureAction}>
            {t("channels.configureAction")}{" "}
            <ArrowUpRight size={16} aria-hidden />
          </span>
        </div>
      </Card>
    </InteractiveCard>
  );
});
