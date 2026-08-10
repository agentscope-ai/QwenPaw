/**
 * AppCard.tsx — Individual app card for the App Center grid.
 */
import { Button, Card, Typography } from "antd";
import { AppWindow, Play, Trash2 } from "lucide-react";
import type { FC, KeyboardEvent } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

const { Text, Paragraph } = Typography;

// Curated translations for known apps whose plugin.json ships no (or
// English-only) description_i18n, keyed by installed plugin id and language
// prefix. Mirrors FEATURED_APP_DESCRIPTIONS in AppMarket so installed and
// marketplace cards use the same copy.
const CURATED_APP_DESCRIPTIONS: Record<string, Record<string, string>> = {
  "agent-kanban": {
    zh: "一个看板应用：创建任务并分配给智能体，由指定智能体自动执行，并实时查看其输出流。",
  },
};

export interface AppCardData {
  id: string;
  name: string;
  version: string;
  description: string;
  /** Per-locale descriptions from plugin.json, e.g. { "zh-CN": "..." }. */
  description_i18n?: Record<string, string>;
  category: string;
  icon: string;
  icon_url?: string;
  entry_page: string;
  launch_scope?: string;
  status: string;
}

/**
 * Resolve the app description for the active UI language: exact locale key
 * first, then language-prefix match (zh → zh-CN), then curated translations
 * for known apps, then an English variant, finally the plain `description`
 * field.
 */
export function pickAppDescription(app: AppCardData, language: string): string {
  const prefix = language.split("-")[0].toLowerCase();
  const i18nMap = app.description_i18n;
  if (i18nMap && Object.keys(i18nMap).length > 0) {
    if (i18nMap[language]) return i18nMap[language];
    for (const key of Object.keys(i18nMap)) {
      if (key.toLowerCase().startsWith(prefix)) return i18nMap[key];
    }
  }
  const curated = CURATED_APP_DESCRIPTIONS[app.id];
  if (curated?.[prefix]) return curated[prefix];
  if (i18nMap) {
    for (const key of Object.keys(i18nMap)) {
      if (key.toLowerCase().startsWith("en")) return i18nMap[key];
    }
  }
  return app.description;
}

interface AppCardProps {
  app: AppCardData;
  onClick: (app: AppCardData) => void;
  /** When provided, renders an uninstall action on the card. */
  onUninstall?: (app: AppCardData) => void;
}

export const AppCard: FC<AppCardProps> = ({ app, onClick, onUninstall }) => {
  const { t, i18n } = useTranslation();
  const [iconFailed, setIconFailed] = useState(false);
  // icon_url points to an image while icon stays a legacy glyph. plugin.json
  // is developer-controlled, but reject script-like schemes anyway and fall
  // back when the image cannot load (e.g. the plugin was installed without a
  // built ui/dist). Apps without an image icon show their plugin.json emoji
  // (e.g. Kanban's 📋); only when that is missing too does the Lucide glyph
  // kick in.
  const imageRef = /^(https?:\/\/|\/|data:image\/)/;
  const iconSrc = [app.icon_url ?? "", app.icon].find((ref) =>
    imageRef.test(ref),
  );
  const isImageIcon = !!iconSrc && !iconFailed;
  const emojiIcon = !isImageIcon && !imageRef.test(app.icon) ? app.icon : "";

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onClick(app);
  };

  return (
    <Card className={`${styles.appCard} ${styles.appCardClickable}`}>
      <div
        className={styles.cardOpenButton}
        onClick={() => onClick(app)}
        onKeyDown={handleKeyDown}
        role="button"
        tabIndex={0}
        aria-label={app.name}
      >
        <div className={styles.cardIcon}>
          {isImageIcon ? (
            <img
              src={iconSrc}
              alt=""
              className={styles.cardIconImage}
              onError={() => setIconFailed(true)}
            />
          ) : emojiIcon ? (
            <span className={styles.cardIconEmoji} aria-hidden>
              {emojiIcon}
            </span>
          ) : (
            <AppWindow size={32} strokeWidth={1.75} />
          )}
        </div>
        <div className={styles.cardBody}>
          <div className={styles.cardHeader}>
            <Text strong className={styles.cardTitle} ellipsis>
              {app.name}
            </Text>
            {app.version && (
              <span className={styles.versionBadge}>v{app.version}</span>
            )}
          </div>
          <Paragraph
            type="secondary"
            className={styles.cardDesc}
            ellipsis={{ rows: 2 }}
          >
            {pickAppDescription(app, i18n.language) ||
              t("appCenter.noDescription", "No description")}
          </Paragraph>
          <div className={styles.cardFooter}>
            {app.category && (
              <span className={styles.cardMeta}>{app.category}</span>
            )}
          </div>
        </div>
      </div>
      <div className={`${styles.cardActions} ${styles.cardHoverActions}`}>
        <Button icon={<Play size={14} />} onClick={() => onClick(app)}>
          {t("appCenter.openApp", "打开应用")}
        </Button>
        {onUninstall && (
          <Button
            danger
            icon={<Trash2 size={14} />}
            onClick={() => onUninstall(app)}
          >
            {t("appCenter.uninstall", "卸载")}
          </Button>
        )}
      </div>
    </Card>
  );
};
