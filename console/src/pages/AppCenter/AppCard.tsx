import { pickAppDescription } from "./appDescription";
import { InteractiveCard } from "@/components/interaction/InteractiveCard";
/**
 * AppCard.tsx — Individual app card for the App Center grid.
 */
import { Button, Card, Dropdown, Typography } from "antd";
import { AppWindow, Play, Trash2, MoreHorizontal } from "lucide-react";
import type { FC, KeyboardEvent } from "react";
import { useEffect, useState } from "react";
import { buildAuthHeaders } from "../../api/authHeaders";
import { getApiUrl } from "../../api/config";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

const { Text, Paragraph } = Typography;

export interface AppCardData {
  id: string;
  name: string;
  author?: string;
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
  // built ui/dist). Apps without an image icon use a Lucide glyph.
  // kick in.
  const imageRef = /^(https?:\/\/|\/|data:image\/)/;
  const iconSrc = [app.icon_url ?? "", app.icon].find((ref) =>
    imageRef.test(ref),
  );
  const protectedIcon = iconSrc?.startsWith("/api/frontend_plugin/");
  const [iconBlob, setIconBlob] = useState<{ src: string; url: string } | null>(
    null,
  );
  useEffect(() => {
    if (!protectedIcon || !iconSrc) return;
    const controller = new AbortController();
    let objectUrl: string | undefined;
    setIconFailed(false);
    void fetch(getApiUrl(iconSrc.slice(4)), {
      headers: buildAuthHeaders(),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("App icon unavailable");
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setIconBlob({ src: iconSrc, url: objectUrl });
      })
      .catch(() => {
        if (!controller.signal.aborted) setIconFailed(true);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [iconSrc, protectedIcon]);
  const displayIcon = protectedIcon
    ? iconBlob && iconBlob.src === iconSrc
      ? iconBlob.url
      : undefined
    : iconSrc;
  const isImageIcon = !!iconSrc && !iconFailed;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onClick(app);
  };

  return (
    <InteractiveCard tilt={3} style={{ width: "100%" }}>
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
                src={displayIcon}
                alt=""
                className={styles.cardIconImage}
                onError={() => setIconFailed(true)}
              />
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
        <div className={styles.cardActions}>
          <Button icon={<Play size={14} />} onClick={() => onClick(app)}>
            {t("appCenter.openApp", "打开应用")}
          </Button>
          {onUninstall && (
            <Dropdown
              menu={{
                items: [
                  {
                    key: "uninstall",
                    label: t("appCenter.uninstall", "卸载"),
                    danger: true,
                    icon: <Trash2 size={14} />,
                    onClick: () => onUninstall(app),
                  },
                ],
              }}
              trigger={["click"]}
            >
              <Button
                aria-label={t("appCenter.moreActions")}
                icon={<MoreHorizontal size={16} />}
              />
            </Dropdown>
          )}
        </div>
      </Card>
    </InteractiveCard>
  );
};
