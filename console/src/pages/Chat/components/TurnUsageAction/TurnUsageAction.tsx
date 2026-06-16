import React from "react";
import { Popover, Progress } from "antd";
import { useTranslation } from "react-i18next";
import { formatCompact } from "../../../../utils/formatNumber";
import {
  readTurnUsageFromResponseCardData,
  type ContextUsage,
  type TurnUsage,
} from "../../turnUsage";

const RING_SIZE = 18;
const RING_STROKE = 3;
const RING_R = (RING_SIZE - RING_STROKE) / 2;
const RING_CIRC = 2 * Math.PI * RING_R;

function ringColor(ratio: number): string {
  if (ratio >= 95) return "#cf1322";
  if (ratio >= 85) return "#f5222d";
  if (ratio >= 75) return "#fa8c16";
  if (ratio >= 50) return "#faad14";
  return "#52c41a";
}

function UsageRing({ ratio }: { ratio: number }) {
  const pct = Math.max(0, Math.min(ratio, 100));
  const cx = RING_SIZE / 2;
  return (
    <svg width={RING_SIZE} height={RING_SIZE} aria-hidden>
      <circle
        cx={cx}
        cy={cx}
        r={RING_R}
        fill="none"
        stroke="currentColor"
        strokeOpacity={0.2}
        strokeWidth={RING_STROKE}
      />
      <circle
        cx={cx}
        cy={cx}
        r={RING_R}
        fill="none"
        stroke={ringColor(pct)}
        strokeWidth={RING_STROKE}
        strokeDasharray={`${RING_CIRC} ${RING_CIRC}`}
        strokeDashoffset={RING_CIRC * (1 - pct / 100)}
        strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cx})`}
      />
    </svg>
  );
}

function PopoverBody({
  usage,
  context,
}: {
  usage: TurnUsage | null;
  context: ContextUsage | null;
}) {
  const { t } = useTranslation();
  const ratio = context
    ? Math.max(0, Math.min(Number(context.context_usage_ratio) || 0, 100))
    : 0;
  const pctLabel =
    ratio > 0 && ratio < 1 ? `${ratio.toFixed(1)}%` : `${Math.round(ratio)}%`;

  return (
    <div style={{ width: 280, fontSize: 13, lineHeight: 1.5 }}>
      {usage && (
        <div style={{ marginBottom: context ? 12 : 0 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            {t(
              usage.estimated
                ? "chat.turnUsagePopover.turnEstimated"
                : "chat.turnUsagePopover.turn",
            )}{" "}
            {formatCompact(usage.total_tokens || 0)}{" "}
            {t("chat.turnUsagePopover.tok")}
          </div>
          <div style={{ opacity: 0.75 }}>
            {t("chat.turnUsagePopover.inOut", {
              inTok: formatCompact(usage.prompt_tokens || 0),
              outTok: formatCompact(usage.completion_tokens || 0),
            })}
          </div>
        </div>
      )}
      {context && (
        <>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              marginBottom: 6,
            }}
          >
            <span style={{ fontWeight: 600 }}>
              {t("chat.turnUsagePopover.contextLabel")} {pctLabel}
            </span>
            <span style={{ opacity: 0.75, fontSize: 12 }}>
              {formatCompact(context.estimated_tokens)}/
              {formatCompact(context.max_input_length)}
            </span>
          </div>
          <Progress
            percent={ratio}
            showInfo={false}
            strokeColor={ringColor(ratio)}
            size="small"
          />
        </>
      )}
    </div>
  );
}

const TurnUsageAction: React.FC<{
  data: { data?: Record<string, unknown> };
}> = ({ data }) => {
  const { t } = useTranslation();
  const snapshot = readTurnUsageFromResponseCardData(data?.data ?? null);
  if (!snapshot || (!snapshot.usage && !snapshot.context_usage)) {
    return null;
  }

  const ratio = snapshot.context_usage
    ? Math.max(
        0,
        Math.min(Number(snapshot.context_usage.context_usage_ratio) || 0, 100),
      )
    : 0;

  return (
    <Popover
      trigger={["hover", "click"]}
      mouseEnterDelay={0.15}
      content={
        <PopoverBody usage={snapshot.usage} context={snapshot.context_usage} />
      }
    >
      <span
        role="button"
        tabIndex={0}
        aria-label={t("chat.turnUsagePopover.ariaLabel")}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "default",
          color: "inherit",
          opacity: 0.65,
          padding: "0 2px",
        }}
      >
        {snapshot.context_usage ? (
          <UsageRing ratio={ratio} />
        ) : (
          <span style={{ fontSize: 12, fontWeight: 600 }}>tok</span>
        )}
      </span>
    </Popover>
  );
};

export default TurnUsageAction;
