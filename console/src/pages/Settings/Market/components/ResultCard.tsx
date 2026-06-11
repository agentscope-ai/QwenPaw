import { memo, useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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

  const showFooter = useCallback(() => setHover(true), []);
  const hideFooter = useCallback(() => setHover(false), []);
  const stopPropagation = useCallback(
    (e: React.MouseEvent | React.KeyboardEvent) => e.stopPropagation(),
    [],
  );

  return (
    <Card
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
        <Tooltip>
          <TooltipTrigger asChild>
            <h3 className={styles.skillTitle}>{item.name}</h3>
          </TooltipTrigger>
          <TooltipContent>{item.name}</TooltipContent>
        </Tooltip>
      </div>

      <p className={styles.descriptionText}>
        {item.description || t("market.noDescription")}
      </p>

      {hover && (
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
            size="sm"
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
