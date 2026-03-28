import { Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { getChannelLabel, type ChannelKey } from "./constants";
import styles from "../index.module.less";

const CHANNEL_ICON_MAP: Record<string, string> = {
  dingtalk:
    "https://gw.alicdn.com/imgextra/i4/O1CN01g1u9vB1KdEreWzDdv_!!6000000001186-2-tps-400-400.png",
  voice:
    "https://gw.alicdn.com/imgextra/i1/O1CN016SJ9AO1SpA6L3j0KH_!!6000000002295-2-tps-400-400.png",
  qq: "https://gw.alicdn.com/imgextra/i3/O1CN014wGNgd27PsTzAyrcj_!!6000000007790-2-tps-400-400.png",
  feishu:
    "https://gw.alicdn.com/imgextra/i4/O1CN01jsn08m225euyUoaFN_!!6000000007069-2-tps-400-400.png",
  xiaoyi:
    "https://gw.alicdn.com/imgextra/i1/O1CN01EPS9Z81OKhIEcwpCd_!!6000000001687-2-tps-476-476.png",
  telegram:
    "https://gw.alicdn.com/imgextra/i2/O1CN0100jIva25Dqqq1VqJN_!!6000000007493-2-tps-400-400.png",
  mqtt: "https://gw.alicdn.com/imgextra/i2/O1CN0117Adu3282o9G5ZNCd_!!6000000007875-2-tps-400-400.png",
  imessage:
    "https://gw.alicdn.com/imgextra/i1/O1CN016pwG4m1uEntwJKsGl_!!6000000006006-2-tps-400-400.png",
  discord:
    "https://gw.alicdn.com/imgextra/i4/O1CN01BQFnBu21PWTtKbPmU_!!6000000006977-2-tps-400-400.png",
  mattermost:
    "https://gw.alicdn.com/imgextra/i2/O1CN01A2bvSh1eVig4fDBEF_!!6000000003877-2-tps-400-400.png",
  matrix:
    "https://gw.alicdn.com/imgextra/i4/O1CN01LF8Tv61tAqrsI5yMY_!!6000000005862-2-tps-400-400.png",
  console:
    "https://gw.alicdn.com/imgextra/i4/O1CN01eeLWyo1ZgBePACyWf_!!6000000003223-2-tps-320-320.png",
  wecom:
    "https://gw.alicdn.com/imgextra/i1/O1CN01HWtzmr1hkK9beQICJ_!!6000000004315-2-tps-400-400.png",
  weixin:
    "https://gw.alicdn.com/imgextra/i1/O1CN01HWtzmr1hkK9beQICJ_!!6000000004315-2-tps-400-400.png",
};

const DEFAULT_ICON =
  "https://gw.alicdn.com/imgextra/i3/O1CN01CQSF5R29JaGuuzZ5X_!!6000000008047-2-tps-320-320.png";

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
  const botPrefix = getConfigString("bot_prefix");

  // Get channel icon from CHANNEL_ICON_MAP or use default
  const getChannelIcon = () => {
    const iconUrl = CHANNEL_ICON_MAP[channelKey] || DEFAULT_ICON;
    return <img src={iconUrl} alt={channelKey} width={32} height={32} />;
  };

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
}
