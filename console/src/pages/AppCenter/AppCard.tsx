/**
 * AppCard.tsx — Individual app card for the App Center grid.
 */
import { Card, Dropdown, Tag, Typography } from "antd";
import type { MenuProps } from "antd";
import { AppWindow, MoreHorizontal, Trash2 } from "lucide-react";
import type { FC, KeyboardEvent } from "react";
import { useState } from "react";
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
  icon_url?: string;
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
  const [iconFailed, setIconFailed] = useState(false);
  // icon_url points to an image while icon stays a legacy glyph. plugin.json
  // is developer-controlled, but reject script-like schemes anyway and fall
  // back to the Lucide glyph when the image cannot load (e.g. the plugin was
  // installed without a built ui/dist). Arbitrary text/emoji icons are
  // disallowed by the design system, so non-image icons use the glyph too.
  const imageRef = /^(https?:\/\/|\/|data:image\/)/;
  const iconSrc = [app.icon_url ?? "", app.icon].find((ref) =>
    imageRef.test(ref),
  );
  const isImageIcon = !!iconSrc && !iconFailed;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onClick(app);
  };

  const menuItems: MenuProps["items"] = [
    {
      key: "uninstall",
      danger: true,
      icon: <Trash2 size={14} />,
      label: t("appCenter.uninstall", "卸载"),
      onClick: ({ domEvent }) => {
        domEvent.stopPropagation();
        onUninstall?.(app);
      },
    },
  ];

  return (
    <Card className={`${styles.appCard} ${styles.appCardClickable}`}>
      {onUninstall && (
        <Dropdown
          menu={{ items: menuItems }}
          trigger={["click"]}
          placement="bottomRight"
        >
          <button
            type="button"
            className={styles.moreBtn}
            aria-label={t("appCenter.moreActions", "更多操作")}
            onClick={(e) => e.stopPropagation()}
          >
            <MoreHorizontal size={16} />
          </button>
        </Dropdown>
      )}
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
          ) : (
            <AppWindow size={22} strokeWidth={1.75} />
          )}
        </div>
        <div className={styles.cardBody}>
          <div className={styles.cardHeader}>
            <Text strong className={styles.cardTitle} ellipsis>
              {app.name}
            </Text>
            {app.version && (
              <span className={styles.cardVersion}>v{app.version}</span>
            )}
          </div>
          <Paragraph
            type="secondary"
            className={styles.cardDesc}
            ellipsis={{ rows: 2 }}
          >
            {app.description || t("appCenter.noDescription", "No description")}
          </Paragraph>
          {app.category && (
            <Tag bordered={false} className={styles.cardTag}>
              {app.category}
            </Tag>
          )}
        </div>
      </div>
    </Card>
  );
};
