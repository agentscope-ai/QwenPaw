import { memo, useCallback, useEffect, useState } from "react";
import { Button, Card, Tooltip } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { MarketResult } from "../../../../api/modules/market";
import type { InstallTarget } from "../useMarketInstall";
import { SkillIcon, sourceLabel } from "./SkillIcon";
import { TargetToggle } from "./TargetToggle";
import styles from "./ResultCard.module.less";

interface ResultCardProps {
  item: MarketResult;
  target: InstallTarget;
  onTargetChange: (next: InstallTarget) => void;
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
  target,
  onTargetChange,
  onInstall,
  onOpenDetail,
}: ResultCardProps) {
  const { t } = useTranslation();
  const [hover, setHover] = useState(false);
  const isMobile = useIsMobile();

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

      {(hover || isMobile) && (
        <div
          className={styles.cardFooter}
          onClick={stopPropagation}
          onKeyDown={stopPropagation}
        >
          <TargetToggle
            target={target}
            onChange={onTargetChange}
            size="small"
          />
          <Button
            type="primary"
            size="small"
            onClick={onInstall}
            className={styles.installButton}
          >
            {t("market.install")}
          </Button>
        </div>
      )}
    </Card>
  );
});
