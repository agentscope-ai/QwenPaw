/**
 * AppCard.tsx — Individual app card for the App Center grid.
 */
import { Card, Tag, Typography, Tooltip } from "antd";
import { AppWindow, Trash2 } from "lucide-react";
import type { FC } from "react";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

const { Text, Paragraph } = Typography;

export interface AppCardData {
  id: string;
  name: string;
  version: string;
  description: string;
  category: string;
  icon: string;
  entry_page: string;
  launch_scope?: string;
  status: string;
}

interface AppCardProps {
  app: AppCardData;
  onClick: (app: AppCardData) => void;
  /** When provided, renders an uninstall action on the card. */
  onUninstall?: (app: AppCardData) => void;
}

export const AppCard: FC<AppCardProps> = ({ app, onClick, onUninstall }) => {
  const { t } = useTranslation();
  return (
    <Card className={styles.appCardLarge} onClick={() => onClick(app)}>
      {onUninstall && (
        <Tooltip title={t("appCenter.uninstall", "卸载")}>
          <button
            type="button"
            className={styles.cardUninstall}
            onClick={(e) => {
              e.stopPropagation();
              onUninstall(app);
            }}
          >
            <Trash2 size={18} />
          </button>
        </Tooltip>
      )}
      <div className={styles.appCardIconLarge}>
        {app.icon ? (
          <span className={styles.appEmojiLarge}>{app.icon}</span>
        ) : (
          <AppWindow size={48} strokeWidth={1.5} />
        )}
      </div>
      <div className={styles.appCardBody}>
        <div className={styles.appCardHeader}>
          <Text strong className={styles.appCardTitleLarge}>
            {app.name}
          </Text>
          {app.version && (
            <span className={styles.appCardVersionLarge}>{app.version}</span>
          )}
        </div>
        <Paragraph
          type="secondary"
          className={styles.appCardDescLarge}
          ellipsis={{ rows: 2 }}
        >
          {app.description || "No description"}
        </Paragraph>
        {app.category && (
          <Tag bordered={false} className={styles.appCardTagLarge}>
            {app.category}
          </Tag>
        )}
      </div>
    </Card>
  );
};
