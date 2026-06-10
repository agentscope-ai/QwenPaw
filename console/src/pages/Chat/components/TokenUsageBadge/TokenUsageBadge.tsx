import React from "react";
import { useTranslation } from "react-i18next";
import { formatCompact } from "../../../../utils/formatNumber";

export interface TurnUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  estimated?: boolean;
}

export interface ContextUsage {
  estimated_tokens: number;
  max_input_length: number;
  context_usage_ratio: number;
}

export interface TokenUsageBadgeSnapshot {
  usage: TurnUsage | null;
  context: ContextUsage | null;
  receivedAt: number;
}

interface Props {
  snapshot: TokenUsageBadgeSnapshot | null;
}

function ringColor(ratio: number): string {
  if (ratio >= 95) return "#cf1322";
  if (ratio >= 85) return "#f5222d";
  if (ratio >= 75) return "#fa8c16";
  if (ratio >= 50) return "#faad14";
  return "#52c41a";
}

const SIZE = 36;
const STROKE = 4;
const R = (SIZE - STROKE) / 2;
const CIRC = 2 * Math.PI * R;
const CX = SIZE / 2;

const wrapperStyle: React.CSSProperties = {
  position: "fixed",
  right: 24,
  bottom: 84,
  zIndex: 2000,
  display: "inline-flex",
  alignItems: "center",
  gap: 10,
  padding: "8px 12px",
  borderRadius: 12,
  background: "rgba(20, 20, 20, 0.78)",
  color: "#fff",
  boxShadow: "0 4px 16px rgba(0,0,0,0.25)",
  backdropFilter: "blur(6px)",
  WebkitBackdropFilter: "blur(6px)",
  fontSize: 12,
  lineHeight: 1.35,
  userSelect: "none",
};

const TokenUsageBadge: React.FC<Props> = ({ snapshot }) => {
  const { t } = useTranslation();
  if (!snapshot || (!snapshot.usage && !snapshot.context)) return null;

  const { usage, context } = snapshot;
  const ratio = context
    ? Math.max(0, Math.min(Number(context.context_usage_ratio) || 0, 100))
    : 0;
  const pctLabel =
    ratio > 0 && ratio < 1 ? `${ratio.toFixed(1)}%` : `${Math.round(ratio)}%`;

  return (
    <div style={wrapperStyle} aria-label={t("chat.tokenUsageBadge.ariaLabel")}>
      {context && (
        <svg width={SIZE} height={SIZE} style={{ flexShrink: 0 }}>
          <circle
            cx={CX}
            cy={CX}
            r={R}
            fill="none"
            stroke="rgba(255,255,255,0.18)"
            strokeWidth={STROKE}
          />
          <circle
            cx={CX}
            cy={CX}
            r={R}
            fill="none"
            stroke={ringColor(ratio)}
            strokeWidth={STROKE}
            strokeDasharray={`${CIRC} ${CIRC}`}
            strokeDashoffset={CIRC * (1 - ratio / 100)}
            strokeLinecap="round"
            transform={`rotate(-90 ${CX} ${CX})`}
            style={{
              transition: "stroke-dashoffset 0.4s ease, stroke 0.4s ease",
            }}
          />
          <text
            x={CX}
            y={CX + 1}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={10}
            fontWeight={700}
            fill="#fff"
          >
            {pctLabel}
          </text>
        </svg>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {usage && (
          <div style={{ fontWeight: 600, whiteSpace: "nowrap" }}>
            {t(
              usage.estimated
                ? "chat.tokenUsageBadge.turnEstimated"
                : "chat.tokenUsageBadge.turn",
            )}{" "}
            {formatCompact(usage.total_tokens || 0)}{" "}
            {t("chat.tokenUsageBadge.tok")}
            <span style={{ opacity: 0.7, fontWeight: 400 }}>
              {" "}
              {t("chat.tokenUsageBadge.inOut", {
                inTok: formatCompact(usage.prompt_tokens || 0),
                outTok: formatCompact(usage.completion_tokens || 0),
              })}
            </span>
          </div>
        )}
        {context && (
          <div style={{ opacity: 0.85, whiteSpace: "nowrap" }}>
            {t("chat.tokenUsageBadge.context", {
              used: formatCompact(context.estimated_tokens),
              max: formatCompact(context.max_input_length),
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default TokenUsageBadge;

export const TOKEN_BADGE_STORAGE_PREFIX = "qwenpaw_token_badge_";

export function resolveTokenBadgeStorageKey(chatId: string): string | null {
  return chatId ? `${TOKEN_BADGE_STORAGE_PREFIX}${chatId}` : null;
}

export function saveTokenBadgeSnapshot(
  key: string,
  snapshot: TokenUsageBadgeSnapshot,
): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(snapshot));
  } catch {
    // QuotaExceededError / SecurityError
  }
}

export function loadTokenBadgeSnapshot(
  chatIdOrKey: string,
): TokenUsageBadgeSnapshot | null {
  try {
    const key = chatIdOrKey.startsWith(TOKEN_BADGE_STORAGE_PREFIX)
      ? chatIdOrKey
      : `${TOKEN_BADGE_STORAGE_PREFIX}${chatIdOrKey}`;
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as TokenUsageBadgeSnapshot) : null;
  } catch {
    return null;
  }
}

export function migrateTokenBadgeSnapshot(
  oldChatId: string,
  newChatId: string,
): void {
  if (!oldChatId || !newChatId || oldChatId === newChatId) return;
  try {
    const oldKey = `${TOKEN_BADGE_STORAGE_PREFIX}${oldChatId}`;
    const newKey = `${TOKEN_BADGE_STORAGE_PREFIX}${newChatId}`;
    const raw = sessionStorage.getItem(oldKey);
    if (raw) {
      sessionStorage.setItem(newKey, raw);
      sessionStorage.removeItem(oldKey);
    }
  } catch {
    // ignore
  }
}
