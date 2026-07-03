import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, Tooltip } from "@agentscope-ai/design";
import { Download, Eye, Heart, Star } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { MarketResult } from "../../../../api/modules/market";
import { SkillIcon, sourceLabel } from "./SkillIcon";
import styles from "./ResultCard.module.less";

interface ResultCardProps {
  item: MarketResult;
  onInstall: () => void;
  onOpenDetail: () => void;
}

const useIsMobile = () => {
  const [isMobile, setIsMobile] = useState(
    typeof window !== "undefined" ? window.innerWidth <= 768 : false,
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const handleResize = () => setIsMobile(window.innerWidth <= 768);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return isMobile;
};

const CURSOR_STYLE = { cursor: "pointer" } as const;

export const ResultCard = memo(function ResultCard({
  item,
  onInstall,
  onOpenDetail,
}: ResultCardProps) {
  const { t } = useTranslation();
  const [hover, setHover] = useState(false);
  const isMobile = useIsMobile();

  const stats = useMemo(() => {
    const s = item.stats ?? {};
    const fmt = (v: string | number | undefined) =>
      typeof v === "number" ? v.toLocaleString() : v ?? "-";
    const rows: Array<{
      key: string;
      Icon: typeof Download;
      value?: string | number;
    }> = [
      { key: "downloads", Icon: Download, value: s.downloads ?? s.installs },
      { key: "stars", Icon: Star, value: s.stars },
      { key: "likes", Icon: Heart, value: s.likes },
      { key: "views", Icon: Eye, value: s.views },
    ];
    return rows
      .filter((r) => r.key === "downloads" || r.value != null)
      .map((r) => ({
        key: r.key,
        Icon: r.Icon,
        label: t(`market.stats.${r.key}`),
        value: fmt(r.value),
      }));
  }, [item.stats, t]);

  const showFooter = useCallback(() => setHover(true), []);
  const hideFooter = useCallback(() => setHover(false), []);
  const stopPropagation = useCallback(
    (e: React.MouseEvent | React.KeyboardEvent) => e.stopPropagation(),
    [],
  );

  return (
    <Card
      hoverable
      className={styles.skillCard}
      onClick={onOpenDetail}
      onMouseEnter={showFooter}
      onMouseLeave={hideFooter}
      style={CURSOR_STYLE}
    >
      <div className={styles.cardTopRow}>
        <SkillIcon url={item.icon_url} alt={item.name} source={item.source} />
        <span className={styles.sourceBadge}>{sourceLabel(item.source)}</span>
      </div>

      <div className={styles.titleRow}>
        <Tooltip title={item.name}>
          <h3 className={styles.skillTitle}>{item.name}</h3>
        </Tooltip>
      </div>

      <p className={styles.descriptionText}>
        {item.description || t("market.noDescription")}
      </p>

      <div className={styles.statsRow}>
        {stats.map(({ key, Icon, label, value }) => (
          <Tooltip key={key} title={label}>
            <span className={styles.statItem}>
              <Icon size={13} />
              <span className={styles.statValue}>{value}</span>
            </span>
          </Tooltip>
        ))}
      </div>

      {(hover || isMobile) && (
        <div
          className={styles.cardFooter}
          onClick={stopPropagation}
          onKeyDown={stopPropagation}
        >
          <Button
            type="primary"
            size="small"
            onClick={onInstall}
            className={styles.installButton}
          >
            {t("common.save")}
          </Button>
        </div>
      )}
    </Card>
  );
});
