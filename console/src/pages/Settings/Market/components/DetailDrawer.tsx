import { memo, useMemo } from "react";
import { Button, Drawer } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { MarketResult } from "../../../../api/modules/market";
import type { InstallTarget } from "../useMarketInstall";
import { SkillIcon, sourceLabel } from "./SkillIcon";
import { TargetToggle } from "./TargetToggle";
import styles from "./DetailDrawer.module.less";

interface DetailDrawerProps {
  item: MarketResult | null;
  target: InstallTarget;
  onTargetChange: (next: InstallTarget) => void;
  onInstall: () => void;
  onClose: () => void;
}

const STAT_KEY_LABELS: Record<string, string> = {
  downloads: "market.stats.downloads",
  installs: "market.stats.installs",
  likes: "market.stats.likes",
  views: "market.stats.views",
  category: "market.stats.category",
  updated_at: "market.stats.updatedAt",
};

function formatStatValue(key: string, value: string | number): string {
  if (key === "updated_at" && typeof value === "string") {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) return date.toLocaleDateString();
  }
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

export const DetailDrawer = memo(function DetailDrawer({
  item,
  target,
  onTargetChange,
  onInstall,
  onClose,
}: DetailDrawerProps) {
  const { t } = useTranslation();
  const open = !!item;
  const missing = t("market.detail.missing");

  const rows = useMemo<Array<[string, React.ReactNode]>>(() => {
    if (!item) return [];
    const result: Array<[string, React.ReactNode]> = [
      [t("market.detail.author"), item.author || missing],
      [t("market.detail.version"), item.version || missing],
      [
        t("market.detail.sourceUrl"),
        <code key="src" className={styles.mono}>
          {item.source_url}
        </code>,
      ],
      [
        t("market.detail.slug"),
        <code key="slug" className={styles.mono}>
          {item.slug}
        </code>,
      ],
    ];
    if (item.stats) {
      for (const [key, value] of Object.entries(item.stats)) {
        const labelKey = STAT_KEY_LABELS[key];
        const label = labelKey ? t(labelKey) : key;
        result.push([label, formatStatValue(key, value)]);
      }
    }
    return result;
  }, [item, t, missing]);

  return (
    <Drawer
      width={520}
      placement="right"
      title={t("market.detail.title")}
      open={open}
      onClose={onClose}
      destroyOnHidden
      footer={
        item ? (
          <div className={styles.drawerFooter}>
            <TargetToggle target={target} onChange={onTargetChange} />
            <Button type="primary" onClick={onInstall}>
              {t("market.install")}
            </Button>
          </div>
        ) : null
      }
    >
      {item && (
        <>
          <div className={styles.detailHeader}>
            <SkillIcon
              url={item.icon_url}
              alt={item.name}
              source={item.source}
            />
            <div className={styles.detailHeaderText}>
              <h3 className={styles.detailTitle}>{item.name}</h3>
              <div className={styles.detailMeta}>
                <span className={styles.sourceBadge}>
                  {sourceLabel(item.source)}
                </span>
              </div>
            </div>
          </div>

          <div className={styles.detailDescription}>
            {item.description || t("market.noDescription")}
          </div>

          <dl className={styles.detailRows}>
            {rows.map(([key, value]) => (
              <div className={styles.detailRow} key={key}>
                <dt className={styles.detailKey}>{key}</dt>
                <dd className={styles.detailValue}>{value}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </Drawer>
  );
});
