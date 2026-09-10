import {
  Activity,
  CircleAlert,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Sparkles,
} from "lucide-react-native";
import { memo, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { Connection, DisplayMessage, DisplayTurn } from "../../api/types";
import { colors, radius, spacing } from "../../theme/tokens";
import { collapseTextParts } from "./collapse";
import { MessageBubbleActions } from "./MessageBubbleActions";
import { MessageParts } from "./MessageParts";
import { messageText } from "./messageActionsModel";

export const MessageTurnView = memo(function MessageTurnView({
  connection,
  turn,
}: {
  connection: Connection;
  turn: DisplayTurn;
}) {
  const [expanded, setExpanded] = useState(false);
  const [answerExpanded, setAnswerExpanded] = useState(false);
  const processSummary = useMemo(() => summarizeProcess(turn.process), [turn.process]);
  const processMessages = useMemo(
    () => mergeToolMessages(turn.process),
    [turn.process],
  );
  const answerParts = useMemo(() => [
    ...(turn.answer?.parts ?? []),
    ...turn.resultMedia,
  ], [turn.answer?.parts, turn.resultMedia]);
  const answerPreview = useMemo(
    () => collapseTextParts(answerParts),
    [answerParts],
  );
  const visibleAnswerParts = answerExpanded
    ? answerParts
    : answerPreview.parts;

  return (
    <View style={styles.turn}>
      {turn.user ? (
        <View style={styles.userRow}>
          <MessageBubbleActions
            inverted
            style={styles.userBubble}
            text={messageText(turn.user.parts)}
          >
            {(selecting) => (
              <MessageParts
                connection={connection}
                parts={turn.user!.parts}
                selecting={selecting}
                user
              />
            )}
          </MessageBubbleActions>
        </View>
      ) : null}
      {turn.process.length ? (
        <View style={[styles.processCard, expanded && styles.processExpanded]}>
          <Pressable onPress={() => setExpanded((current) => !current)} style={styles.processHeader}>
            <View style={styles.processIcon}><Activity color={colors.accentDark} size={16} /></View>
            <View style={styles.processHeading}>
              <Text style={styles.processTitle}>执行过程</Text>
              <Text numberOfLines={1} style={styles.processMeta}>{processSummary}</Text>
            </View>
            <ChevronDown color={colors.muted} size={18} style={expanded ? styles.chevronUp : undefined} />
          </Pressable>
          {expanded ? (
            <View style={styles.processBody}>
              {processMessages.map((message, index) => (
                <ProcessRow
                  connection={connection}
                  key={message.id}
                  last={index === processMessages.length - 1}
                  message={message}
                />
              ))}
            </View>
          ) : null}
        </View>
      ) : null}
      {answerParts.length || turn.pending || turn.answer?.error ? (
        <MessageBubbleActions
          style={styles.answerBubble}
          text={messageText(answerParts)}
        >
          {(selecting) => (
            <>
              {!selecting ? (
                <View style={styles.answerLabel}>
                  <Sparkles color={colors.accent} size={14} />
                  <Text style={styles.answerLabelText}>最终回复</Text>
                </View>
              ) : null}
              {turn.answer?.error ? (
                <View style={styles.answerError}>
                  <CircleAlert color={colors.danger} size={17} />
                  <View style={styles.answerErrorCopy}>
                    <Text style={styles.answerErrorTitle}>发送失败</Text>
                    <Text style={styles.answerErrorDetail}>{turn.answer.error}</Text>
                  </View>
                </View>
              ) : answerParts.length ? (
                <>
                  <MessageParts
                    connection={connection}
                    parts={selecting ? answerParts : visibleAnswerParts}
                    selecting={selecting}
                  />
                  {!selecting && answerPreview.collapsible ? (
                    <Pressable
                      onPress={() => setAnswerExpanded((current) => !current)}
                      style={styles.answerExpand}
                    >
                      <Text style={styles.answerExpandText}>
                        {answerExpanded ? "收起" : "展开全文"}
                      </Text>
                      {answerExpanded ? (
                        <ChevronUp color={colors.accentDark} size={15} />
                      ) : (
                        <ChevronDown color={colors.accentDark} size={15} />
                      )}
                    </Pressable>
                  ) : null}
                </>
              ) : (
                <View style={styles.pending}>
                  <ActivityIndicator color={colors.accentDark} size="small" />
                  <Text style={styles.pendingText}>正在组织回复…</Text>
                </View>
              )}
            </>
          )}
        </MessageBubbleActions>
      ) : null}
    </View>
  );
});

function ProcessRow({
  connection,
  last,
  message,
}: {
  connection: Connection;
  last: boolean;
  message: DisplayMessage;
}) {
  const [detailExpanded, setDetailExpanded] = useState(false);
  const text = message.parts.find((part) => part.type === "text");
  const media = message.parts.filter((part) => part.type !== "text");
  const title = message.kind === "reasoning"
    ? "思考与规划"
    : message.kind === "tool"
      ? toolLabel(message.toolName)
      : "中间结果";
  return (
    <View style={[styles.processRow, !last && styles.processDivider]}>
      <CheckCircle2 color={colors.accent} size={15} />
      <View style={styles.processRowBody}>
        <View style={styles.processRowHeading}>
          <Text style={styles.processRowTitle}>{title}</Text>
          {message.kind === "tool" ? (
            <Text style={styles.toolState}>{toolStateLabel(message)}</Text>
          ) : null}
        </View>
        {message.kind === "tool" ? (
          <>
            {message.toolInput ? (
              <ToolDetail
                expanded={detailExpanded}
                label="参数"
                text={message.toolInput}
              />
            ) : null}
            {message.toolOutput ? (
              <ToolDetail
                expanded={detailExpanded}
                label="结果"
                text={message.toolOutput}
              />
            ) : null}
            {media.length ? (
              <MessageParts compact connection={connection} parts={media} />
            ) : null}
            {(message.toolInput?.length ?? 0) + (message.toolOutput?.length ?? 0) > 420 ? (
              <Pressable onPress={() => setDetailExpanded((current) => !current)}>
                <Text style={styles.toolExpand}>{detailExpanded ? "收起详情" : "查看完整结果"}</Text>
              </Pressable>
            ) : null}
          </>
        ) : text?.type === "text" ? (
          <Text numberOfLines={6} style={styles.processText}>{text.text}</Text>
        ) : null}
      </View>
    </View>
  );
}

function ToolDetail({
  expanded,
  label,
  text,
}: {
  expanded: boolean;
  label: string;
  text: string;
}) {
  return (
    <View style={styles.toolDetail}>
      <Text style={styles.toolDetailLabel}>{label}</Text>
      <Text numberOfLines={expanded ? undefined : 6} style={styles.toolDetailText}>
        {text}
      </Text>
    </View>
  );
}

function summarizeProcess(messages: DisplayMessage[]): string {
  const toolMessages = messages.filter((message) => message.kind === "tool");
  const toolCalls = toolMessages.filter((message) => !message.toolState).length;
  const tools = toolCalls || toolMessages.length;
  const reasoning = messages.some((message) => message.kind === "reasoning");
  const parts = [];
  if (reasoning) parts.push("已完成思考");
  if (tools) parts.push(`${tools} 个工具步骤`);
  if (!parts.length) parts.push(`${messages.length} 条中间结果`);
  return parts.join(" · ");
}

function mergeToolMessages(messages: DisplayMessage[]): DisplayMessage[] {
  const merged: DisplayMessage[] = [];
  for (const message of messages) {
    if (message.kind !== "tool") {
      merged.push(message);
      continue;
    }
    const previous = merged.at(-1);
    const sameCall = previous?.kind === "tool" && (
      Boolean(message.toolCallId && previous.toolCallId === message.toolCallId) ||
      Boolean(message.toolName && previous.toolName === message.toolName) ||
      (!message.toolName && Boolean(previous.toolInput) && !previous.toolOutput)
    );
    if (!previous || !sameCall) {
      merged.push(message);
      continue;
    }
    merged[merged.length - 1] = {
      ...previous,
      toolName: previous.toolName ?? message.toolName,
      toolState: message.toolState ?? previous.toolState,
      toolCallId: previous.toolCallId ?? message.toolCallId,
      toolInput: previous.toolInput ?? message.toolInput,
      toolOutput: message.toolOutput ?? previous.toolOutput,
      parts: uniqueParts([...previous.parts, ...message.parts]),
    };
  }
  return merged;
}

function uniqueParts(parts: DisplayMessage["parts"]): DisplayMessage["parts"] {
  const seen = new Set<string>();
  return parts.filter((part) => {
    const key = part.type === "text"
      ? `text:${part.text}`
      : `${part.type}:${part.url}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function toolLabel(name?: string): string {
  if (!name) return "工具调用";
  return name.replace(/_/g, " ");
}

function toolStateLabel(message: DisplayMessage): string {
  if (!message.toolOutput && !message.toolState) return "调用";
  if (/error|failed|denied|interrupted/i.test(message.toolState ?? "")) {
    return "失败";
  }
  return "完成";
}

const styles = StyleSheet.create({
  turn: { gap: spacing.sm },
  userRow: { alignItems: "flex-end", marginBottom: 2 },
  userBubble: { maxWidth: "82%", minWidth: 54, paddingHorizontal: spacing.md, paddingVertical: 11, borderRadius: 20, borderBottomRightRadius: 6, backgroundColor: colors.accent },
  processCard: { overflow: "hidden", borderWidth: 1, borderColor: colors.line, borderRadius: radius.md, backgroundColor: colors.surface },
  processExpanded: { borderColor: colors.accentSoft },
  processHeader: { minHeight: 52, flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12 },
  processIcon: { width: 30, height: 30, alignItems: "center", justifyContent: "center", borderRadius: 10, backgroundColor: colors.accentSoft },
  processHeading: { flex: 1, minWidth: 0, gap: 2 },
  processTitle: { color: colors.ink, fontSize: 14, fontWeight: "600" },
  processMeta: { color: colors.muted, fontSize: 11, lineHeight: 16 },
  chevronUp: { transform: [{ rotate: "180deg" }] },
  processBody: { paddingHorizontal: 13, paddingBottom: 10 },
  processRow: { flexDirection: "row", alignItems: "flex-start", gap: 9, paddingVertical: 10 },
  processDivider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.hairline },
  processRowBody: { flex: 1, minWidth: 0, gap: 5 },
  processRowHeading: { flexDirection: "row", alignItems: "center", gap: 8 },
  processRowTitle: { color: colors.ink, fontSize: 13, fontWeight: "600" },
  toolState: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 6, color: colors.muted, backgroundColor: colors.searchBackground, fontSize: 10, fontWeight: "700" },
  processText: { color: colors.muted, fontSize: 13, lineHeight: 20 },
  toolDetail: { gap: 3, padding: 8, borderRadius: radius.sm, backgroundColor: colors.groupedBackground },
  toolDetailLabel: { color: colors.faint, fontSize: 10, fontWeight: "700" },
  toolDetailText: { color: colors.muted, fontSize: 12, lineHeight: 18, fontFamily: "Menlo" },
  toolExpand: { color: colors.accentDark, fontSize: 12, lineHeight: 18, fontWeight: "600" },
  answerBubble: { padding: spacing.md, borderWidth: 1, borderColor: colors.line, borderRadius: 21, borderBottomLeftRadius: 7, backgroundColor: colors.surfaceStrong },
  answerLabel: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 10 },
  answerLabelText: { color: colors.muted, fontSize: 11, fontWeight: "700" },
  answerExpand: { minHeight: 34, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, marginTop: 4, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.hairline },
  answerExpandText: { color: colors.accentDark, fontSize: 12, fontWeight: "600" },
  answerError: { flexDirection: "row", alignItems: "flex-start", gap: 9, padding: 11, borderRadius: radius.sm, backgroundColor: "#FFF1EF" },
  answerErrorCopy: { flex: 1, minWidth: 0, gap: 3 },
  answerErrorTitle: { color: colors.danger, fontSize: 13, fontWeight: "700" },
  answerErrorDetail: { color: colors.danger, fontSize: 13, lineHeight: 19 },
  pending: { minHeight: 34, flexDirection: "row", alignItems: "center", gap: 9 },
  pendingText: { color: colors.muted, fontSize: 14, lineHeight: 20 },
});
