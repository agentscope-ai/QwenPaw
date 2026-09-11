import React from "react";
import { Button, Popover, Space } from "antd";
import { useTranslation } from "react-i18next";
import { formatCompact } from "../../../../utils/formatNumber";
import { cacheHitRate, formatPercent } from "../../../../utils/cacheUsage";
import { useTurnUsageStore } from "../../turnUsageStore";
import type { ContextUsage, TurnUsage } from "../../turnUsage";

const DIAL_SIZE = 24;
const DIAL_CENTER = DIAL_SIZE / 2;
const CONTEXT_RADIUS = 10.5;
const CONTEXT_CIRCUMFERENCE = 2 * Math.PI * CONTEXT_RADIUS;

function contextRingColor(ratio: number): string {
  if (ratio >= 90) return "#cf1322";
  if (ratio >= 75) return "#d48806";
  return "#66756d";
}

function cacheDialColors(rate: number | null): {
  fill: string;
  text: string;
} {
  if (rate === null || rate <= 0) {
    return { fill: "rgba(102, 117, 109, 0.10)", text: "#7f8983" };
  }
  return { fill: "rgba(39, 139, 89, 0.12)", text: "#278b59" };
}

function cacheDialText(rate: number | null): string {
  if (rate === null) return "–";
  if (rate >= 100) return "100";
  return `${Math.floor(Math.max(rate, 0))}`;
}

function cacheRateFromUsage(usage: TurnUsage | null): number | null {
  if (!usage?.session_cache_observed) return null;
  return (
    usage.session_cache_hit_rate ??
    cacheHitRate(
      usage.session_cache_read_tokens || 0,
      usage.session_cache_eligible_input_tokens || 0,
    )
  );
}

function FusionUsageDial({
  contextRate,
  cacheRate,
}: {
  contextRate: number;
  cacheRate: number | null;
}) {
  const context = Math.max(0, Math.min(contextRate, 100));
  const cacheColors = cacheDialColors(cacheRate);
  const cacheText = cacheDialText(cacheRate);
  return (
    <svg
      width={DIAL_SIZE}
      height={DIAL_SIZE}
      viewBox={`0 0 ${DIAL_SIZE} ${DIAL_SIZE}`}
      aria-hidden
    >
      <circle
        cx={DIAL_CENTER}
        cy={DIAL_CENTER}
        r={CONTEXT_RADIUS}
        fill="none"
        stroke="currentColor"
        strokeOpacity={0.14}
        strokeWidth={2}
      />
      <circle
        cx={DIAL_CENTER}
        cy={DIAL_CENTER}
        r={CONTEXT_RADIUS}
        fill="none"
        stroke={contextRingColor(context)}
        strokeWidth={2}
        strokeDasharray={`${CONTEXT_CIRCUMFERENCE} ${CONTEXT_CIRCUMFERENCE}`}
        strokeDashoffset={CONTEXT_CIRCUMFERENCE * (1 - context / 100)}
        strokeLinecap="round"
        transform={`rotate(-90 ${DIAL_CENTER} ${DIAL_CENTER})`}
      />
      <circle
        cx={DIAL_CENTER}
        cy={DIAL_CENTER}
        r={6.5}
        fill={cacheColors.fill}
      />
      <text
        x={DIAL_CENTER}
        y={DIAL_CENTER}
        dy="0.32em"
        fill={cacheColors.text}
        fontSize={cacheText.length > 2 ? 6.2 : 7.4}
        fontWeight={700}
        textAnchor="middle"
      >
        {cacheText}
      </text>
    </svg>
  );
}

function MetricRow({
  name,
  position,
  detail,
  value,
  valueColor,
}: {
  name: string;
  position: string;
  detail: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 12,
        alignItems: "baseline",
      }}
    >
      <div>
        <div style={{ fontWeight: 600 }}>{name}</div>
        <div style={{ opacity: 0.68, fontSize: 12, marginTop: 2 }}>
          {position} · {detail}
        </div>
      </div>
      <div
        style={{
          color: valueColor,
          fontSize: 15,
          fontWeight: 700,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function PopoverBody({
  usage,
  context,
  onCompact,
  onNew,
}: {
  usage: TurnUsage | null;
  context: ContextUsage;
  onCompact: () => void;
  onNew: () => void;
}) {
  const { t } = useTranslation();
  const contextRate = Math.max(
    0,
    Math.min(Number(context.context_usage_ratio) || 0, 100),
  );
  const cacheRate = cacheRateFromUsage(usage);
  return (
    <div style={{ width: 260, fontSize: 13, lineHeight: 1.5 }}>
      <MetricRow
        name={t("chat.turnUsagePopover.contextLabel")}
        position={t("chat.turnUsagePopover.outerRing")}
        detail={`${formatCompact(context.estimated_tokens)} / ${formatCompact(
          context.max_input_length,
        )}`}
        value={formatPercent(contextRate)}
      />
      <div
        style={{
          marginTop: 12,
          paddingTop: 12,
          borderTop: "1px solid rgba(0,0,0,0.06)",
        }}
      >
        <MetricRow
          name={t("chat.turnUsagePopover.cacheLabel")}
          position={t("chat.turnUsagePopover.centerValue")}
          detail={t("chat.turnUsagePopover.cacheTokens", {
            readTok: formatCompact(usage?.session_cache_read_tokens || 0),
            inputTok: formatCompact(
              usage?.session_cache_eligible_input_tokens || 0,
            ),
          })}
          value={formatPercent(cacheRate)}
          valueColor={
            cacheRate !== null && cacheRate > 0 ? "#278b59" : undefined
          }
        />
      </div>
      <div
        style={{
          marginTop: 12,
          paddingTop: 12,
          borderTop: "1px solid rgba(0,0,0,0.06)",
        }}
      >
        <div style={{ fontSize: 12, opacity: 0.65, marginBottom: 8 }}>
          {t("chat.turnUsagePopover.manageContext")}
        </div>
        <Space size={8}>
          <Button size="small" onClick={onCompact}>
            {t("chat.turnUsagePopover.compact")}
          </Button>
          <Button size="small" onClick={onNew}>
            {t("chat.turnUsagePopover.new")}
          </Button>
        </Space>
      </div>
    </div>
  );
}

const ContextUsageIndicator: React.FC<{
  onCompact: () => void;
  onNew: () => void;
}> = ({ onCompact, onNew }) => {
  const { t } = useTranslation();
  const snapshot = useTurnUsageStore((state) => state.snapshot);

  if (!snapshot?.context_usage) return null;

  const contextRate = Math.max(
    0,
    Math.min(Number(snapshot.context_usage.context_usage_ratio) || 0, 100),
  );
  const cacheRate = cacheRateFromUsage(snapshot.usage);

  return (
    <Popover
      trigger={["hover", "click"]}
      mouseEnterDelay={0.15}
      content={
        <PopoverBody
          usage={snapshot.usage}
          context={snapshot.context_usage}
          onCompact={onCompact}
          onNew={onNew}
        />
      }
    >
      <button
        type="button"
        aria-label={t("chat.turnUsagePopover.ariaLabel", {
          contextRate: formatPercent(contextRate),
          cacheRate: formatPercent(cacheRate),
        })}
        style={{
          display: "grid",
          width: 32,
          height: 32,
          padding: 4,
          placeItems: "center",
          flex: "none",
          cursor: "pointer",
          color: "inherit",
          background: "transparent",
          border: 0,
          borderRadius: 9,
        }}
      >
        <FusionUsageDial contextRate={contextRate} cacheRate={cacheRate} />
      </button>
    </Popover>
  );
};

export default ContextUsageIndicator;
