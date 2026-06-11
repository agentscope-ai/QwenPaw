import { Zap, BookOpen, Settings, Clock, Trophy } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { HarvestInstance } from "../types";
import { useHarvestCountdown } from "../hooks/useHarvestCountdown";
import styles from "./HarvestCard.module.less";

interface HarvestCardProps {
  harvest: HarvestInstance;
  onTrigger: (id: string) => void;
  onViewAll: (id: string) => void;
  onSettings: (id: string) => void;
}

/** Circular progress using SVG — replaces antd Progress type="circle" */
function CircularProgress({
  percent,
  label,
  isOverdue,
}: {
  percent: number;
  label: string;
  isOverdue: boolean;
}) {
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percent / 100) * circumference;
  const color = isOverdue ? "#FFD700" : "var(--primary)";

  return (
    <div className="relative inline-flex items-center justify-center w-[90px] h-[90px]">
      <svg width="90" height="90" viewBox="0 0 90 90" className="-rotate-90">
        <circle
          cx="45"
          cy="45"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          className="text-muted/40"
        />
        <circle
          cx="45"
          cy="45"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-500"
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-xs font-mono font-semibold text-foreground text-center leading-none px-1">
        {label}
      </span>
    </div>
  );
}

export function HarvestCard({
  harvest,
  onTrigger,
  onViewAll,
  onSettings,
}: HarvestCardProps) {
  const { t } = useTranslation();
  const countdown = useHarvestCountdown(harvest.schedule.nextRun);
  const timeText = countdown.isOverdue
    ? t("inbox.ready")
    : `${String(countdown.hours).padStart(2, "0")}:${String(
        countdown.minutes,
      ).padStart(2, "0")}:${String(countdown.seconds).padStart(2, "0")}`;

  return (
    <Card
      className={cn(
        "hover:shadow-md transition-shadow",
        countdown.isOverdue && "border-yellow-400/60",
        styles.harvestCard,
        countdown.isOverdue && styles.harvestCardReady,
      )}
    >
      <CardContent className="p-3.5 flex flex-col gap-0">
        <div className="flex justify-between items-start">
          <div className="flex items-center gap-2">
            <span className="text-xl">{harvest.emoji}</span>
            <h3 className="text-sm font-semibold text-foreground">
              {harvest.name}
            </h3>
          </div>
          <Badge
            variant="outline"
            className={cn(
              "text-[11px] border-0",
              harvest.status === "active"
                ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                : "bg-muted text-muted-foreground",
            )}
          >
            {harvest.status}
          </Badge>
        </div>

        <div className="mt-3 flex items-center gap-4">
          <CircularProgress
            percent={Math.round(countdown.percentage)}
            label={timeText}
            isOverdue={countdown.isOverdue}
          />
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock size={13} />
              <span>
                {countdown.isOverdue
                  ? t("inbox.statusReadyToHarvest")
                  : t("inbox.statusGrowing")}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Zap size={13} />
              <span>
                {t("inbox.harvestedTimes", {
                  count: harvest.stats.totalGenerated,
                })}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Trophy size={13} />
              <span>
                {t("inbox.harvestSuccessRate", {
                  rate: harvest.stats.successRate,
                })}
              </span>
            </div>
          </div>
        </div>

        <div className="mt-3 flex gap-2">
          <Button
            size="sm"
            className="bg-orange-500 hover:bg-orange-600 text-white border-0 flex-1"
            onClick={() => onTrigger(harvest.id)}
          >
            <Zap size={14} />
            {t("inbox.harvestNow")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onViewAll(harvest.id)}
          >
            <BookOpen size={14} />
            {t("inbox.viewAll")}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => onSettings(harvest.id)}
          >
            <Settings size={14} />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
