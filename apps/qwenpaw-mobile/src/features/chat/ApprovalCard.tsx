import { MobileAlert } from "@/components/MobileAlert";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Clock3,
  ShieldCheck,
  X,
} from "lucide-react-native";
import { memo, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { PendingApproval } from "../../api/types";
import { colors, radius, spacing } from "../../theme/tokens";

export const ApprovalCard = memo(function ApprovalCard({
  approval,
  compact = false,
  contextLabel,
  onApprove,
  onDeny,
}: {
  approval: PendingApproval;
  compact?: boolean;
  contextLabel?: string;
  onApprove: (scope: "exact" | "similar") => Promise<void>;
  onDeny: () => Promise<void>;
}) {
  const [now, setNow] = useState(() => Date.now());
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [busy, setBusy] = useState<"exact" | "similar" | "deny" | null>(null);
  const allowSimilar = Boolean(
    approval.is_generalized && approval.similar_target &&
    approval.tool_source !== "STRICT mode",
  );
  const title = approval.tool_display_name || approval.tool_name;
  const severity = approval.severity?.toLocaleLowerCase() || "unknown";
  const params = useMemo(
    () => JSON.stringify(approval.tool_params ?? {}, null, 2),
    [approval.tool_params],
  );
  const remaining = remainingSeconds(approval, now);

  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const perform = async (
    kind: "exact" | "similar" | "deny",
    action: () => Promise<void>,
  ) => {
    setBusy(kind);
    try {
      await action();
    } catch (error) {
      MobileAlert.alert(
        kind === "deny" ? "拒绝失败" : "审批失败",
        error instanceof Error ? error.message : "请稍后重试。",
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={[styles.card, compact && styles.cardCompact]}>
      <View style={styles.header}>
        <View style={styles.securityIcon}>
          <ShieldCheck color={colors.accentDark} size={18} />
        </View>
        <View style={styles.headerText}>
          <Text style={styles.eyebrow}>需要你的审批</Text>
          <Text numberOfLines={1} style={styles.title}>{title}</Text>
        </View>
        <View style={styles.timer}>
          <Clock3 color={remaining <= 30 ? colors.danger : colors.muted} size={13} />
          <Text style={[
            styles.timerText,
            remaining <= 30 && styles.timerUrgent,
          ]}>
            {formatRemaining(remaining)}
          </Text>
        </View>
      </View>

      {contextLabel ? <Text style={styles.context}>{contextLabel}</Text> : null}
      {approval.reasoning ? (
        <Text numberOfLines={compact ? 2 : 4} style={styles.reasoning}>
          {approval.reasoning}
        </Text>
      ) : null}

      <View style={styles.metaRow}>
        <View style={[
          styles.severity,
          (severity === "high" || severity === "critical") &&
            styles.severityHigh,
        ]}>
          <AlertTriangle color={
            severity === "high" || severity === "critical"
              ? colors.danger
              : colors.accentDark
          } size={12} />
          <Text style={styles.severityText}>{severity.toUpperCase()}</Text>
        </View>
        <Text style={styles.metaText}>
          {approval.findings_count || 0} 项安全检查
        </Text>
        <View style={styles.metaSpacer} />
        <Pressable
          accessibilityLabel={detailsOpen ? "收起审批详情" : "展开审批详情"}
          onPress={() => setDetailsOpen((value) => !value)}
          style={styles.detailsButton}
        >
          <Text style={styles.detailsButtonText}>详情</Text>
          {detailsOpen
            ? <ChevronUp color={colors.muted} size={14} />
            : <ChevronDown color={colors.muted} size={14} />}
        </Pressable>
      </View>

      {detailsOpen ? (
        <View style={styles.details}>
          {approval.exact_target ? (
            <Detail label="本次目标" value={approval.exact_target} />
          ) : null}
          {allowSimilar && approval.similar_target ? (
            <Detail label="始终允许范围" value={approval.similar_target} />
          ) : null}
          {params !== "{}" ? <Detail label="工具参数" value={params} code /> : null}
          {approval.findings_summary ? (
            <Detail label="检查结果" value={approval.findings_summary} />
          ) : null}
        </View>
      ) : null}

      <View style={styles.actions}>
        <ActionButton
          danger
          disabled={busy !== null || remaining <= 0}
          icon={X}
          label="拒绝"
          loading={busy === "deny"}
          onPress={() => void perform("deny", onDeny)}
        />
        <ActionButton
          disabled={busy !== null || remaining <= 0}
          icon={Check}
          label={allowSimilar ? "仅本次" : "允许"}
          loading={busy === "exact"}
          onPress={() => void perform("exact", () => onApprove("exact"))}
          primary
        />
        {allowSimilar ? (
          <ActionButton
            disabled={busy !== null || remaining <= 0}
            icon={ShieldCheck}
            label="始终允许"
            loading={busy === "similar"}
            onPress={() => void perform("similar", () => onApprove("similar"))}
          />
        ) : null}
      </View>
      {remaining <= 0 ? <Text style={styles.timeout}>审批已超时，正在同步状态</Text> : null}
    </View>
  );
});

function Detail({
  code = false,
  label,
  value,
}: {
  code?: boolean;
  label: string;
  value: string;
}) {
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text selectable style={[styles.detailValue, code && styles.code]}>
        {value}
      </Text>
    </View>
  );
}

function ActionButton({
  danger = false,
  disabled,
  icon: Icon,
  label,
  loading,
  onPress,
  primary = false,
}: {
  danger?: boolean;
  disabled: boolean;
  icon: typeof Check;
  label: string;
  loading: boolean;
  onPress: () => void;
  primary?: boolean;
}) {
  const color = primary ? colors.white : danger ? colors.danger : colors.ink;
  return (
    <Pressable
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.action,
        primary && styles.actionPrimary,
        danger && styles.actionDanger,
        disabled && styles.actionDisabled,
        pressed && styles.actionPressed,
      ]}
    >
      {loading
        ? <ActivityIndicator color={color} size="small" />
        : <Icon color={color} size={15} />}
      <Text style={[
        styles.actionText,
        primary && styles.actionTextPrimary,
        danger && styles.actionTextDanger,
      ]}>
        {label}
      </Text>
    </Pressable>
  );
}

function remainingSeconds(approval: PendingApproval, now: number): number {
  const elapsed = Math.floor(now / 1000 - approval.created_at);
  return Math.max(0, Math.floor(approval.timeout_seconds - elapsed));
}

function formatRemaining(value: number): string {
  const minutes = Math.floor(value / 60);
  const seconds = String(value % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

const styles = StyleSheet.create({
  card: {
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: "#F0CFB5",
    borderRadius: radius.md,
    backgroundColor: "#FFFCF9",
    padding: spacing.md,
    shadowColor: colors.black,
    shadowOffset: { width: 0, height: 5 },
    shadowOpacity: 0.06,
    shadowRadius: 18,
  },
  cardCompact: { padding: 13 },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  securityIcon: {
    width: 36,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    backgroundColor: colors.accentSoft,
  },
  headerText: { flex: 1, minWidth: 0 },
  eyebrow: { color: colors.accentDark, fontSize: 10, fontWeight: "700" },
  title: { marginTop: 2, color: colors.ink, fontSize: 15, fontWeight: "700" },
  timer: { flexDirection: "row", alignItems: "center", gap: 4 },
  timerText: { color: colors.muted, fontSize: 11, fontVariant: ["tabular-nums"] },
  timerUrgent: { color: colors.danger },
  context: { color: colors.muted, fontSize: 11 },
  reasoning: { color: colors.ink, fontSize: 13, lineHeight: 19 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 7 },
  severity: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.accentSoft,
    paddingHorizontal: 7,
    paddingVertical: 4,
  },
  severityHigh: { backgroundColor: "#FBEAE8" },
  severityText: { color: colors.muted, fontSize: 9, fontWeight: "800" },
  metaText: { color: colors.faint, fontSize: 10 },
  metaSpacer: { flex: 1 },
  detailsButton: { flexDirection: "row", alignItems: "center", gap: 2 },
  detailsButtonText: { color: colors.muted, fontSize: 11, fontWeight: "600" },
  details: {
    gap: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
    paddingTop: spacing.sm,
  },
  detailRow: { gap: 4 },
  detailLabel: { color: colors.muted, fontSize: 10, fontWeight: "700" },
  detailValue: { color: colors.ink, fontSize: 11, lineHeight: 16 },
  code: {
    borderRadius: radius.sm,
    backgroundColor: colors.groupedBackground,
    padding: spacing.sm,
    fontFamily: "Menlo",
  },
  actions: { flexDirection: "row", gap: spacing.xs },
  action: {
    flex: 1,
    minHeight: 38,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
    paddingHorizontal: 7,
  },
  actionPrimary: { borderColor: colors.accent, backgroundColor: colors.accent },
  actionDanger: { borderColor: "#E8C8C4", backgroundColor: "#FFF8F7" },
  actionText: { color: colors.ink, fontSize: 11, fontWeight: "700" },
  actionTextPrimary: { color: colors.white },
  actionTextDanger: { color: colors.danger },
  actionDisabled: { opacity: 0.45 },
  actionPressed: { opacity: 0.72 },
  timeout: { color: colors.danger, fontSize: 10, textAlign: "center" },
});
