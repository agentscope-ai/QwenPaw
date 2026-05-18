import type { PushMessage } from "../types";

export type TraceDisplayItem = {
  at: number;
  eventType: string;
  eventRecord: Record<string, unknown>;
  traceText: string;
  collapsible: boolean;
  collapseTitle: string;
  toolInput?: string;
  toolOutput?: string;
  renderKind: "tool_pair" | "normal";
};

export const buildContentFallbackTrace = (messageItem: PushMessage) => ({
  events: messageItem.content
    ? [
        {
          at: messageItem.createdAt.getTime() / 1000,
          event: {
            role: "assistant",
            name: "assistant",
            content: [
              {
                type: "text",
                text: messageItem.content,
              },
            ],
          },
        },
      ]
    : [],
});

export const getPrimaryTraceBlock = (
  event: Record<string, unknown>,
): Record<string, unknown> | null => {
  const content = event.content;
  if (!Array.isArray(content) || !content.length) return null;
  const first = content[0];
  if (!first || typeof first !== "object") return null;
  return first as Record<string, unknown>;
};

export const isCollapsibleTraceEvent = (
  kind: string,
  event: Record<string, unknown>,
): boolean => {
  const lowerKind = kind.toLowerCase();
  if (lowerKind.includes("thinking") || lowerKind.includes("tool")) {
    return true;
  }
  const block = getPrimaryTraceBlock(event);
  const blockType = String(block?.type || "").toLowerCase();
  if (
    blockType === "thinking" ||
    blockType === "tool_use" ||
    blockType === "tool_result"
  ) {
    return true;
  }
  return false;
};

export const extractTraceText = (event: Record<string, unknown>): string => {
  const block = getPrimaryTraceBlock(event);
  if (!block) return "";
  const blockType = String(block.type || "").toLowerCase();
  if (blockType === "thinking") {
    const thinking = block.thinking;
    if (typeof thinking === "string" && thinking.trim()) {
      return thinking.trim();
    }
  }
  if (blockType === "text") {
    const text = block.text;
    if (typeof text === "string" && text.trim()) {
      return text.trim();
    }
  }
  if (blockType === "tool_result") {
    const output = block.output;
    if (Array.isArray(output)) {
      const textChunks = output
        .map((item) => {
          if (!item || typeof item !== "object") return "";
          const text = (item as Record<string, unknown>).text;
          return typeof text === "string" ? text : "";
        })
        .filter(Boolean);
      if (textChunks.length) return textChunks.join("\n");
    }
  }
  if (blockType === "tool_use") {
    const rawInput = block.raw_input;
    if (typeof rawInput === "string" && rawInput.trim()) {
      return rawInput.trim();
    }
  }
  return "";
};

export const normalizeTraceKind = (event: Record<string, unknown>): string => {
  if (event.type === "response_completed") return "response_completed";
  const block = getPrimaryTraceBlock(event);
  const blockType = String(block?.type || "").toLowerCase();
  if (blockType === "thinking") return "thinking";
  if (blockType === "tool_use") return "tool_call";
  if (blockType === "tool_result") return "tool_output";
  if (blockType === "text") return "push_preview";
  return "event";
};

export const shouldHideTraceEvent = (
  eventType: string,
  eventRecord: Record<string, unknown>,
): boolean => {
  const lowerType = eventType.toLowerCase();
  if (lowerType === "response_completed") return true;
  if (
    !extractTraceText(eventRecord) &&
    !isCollapsibleTraceEvent(eventType, eventRecord)
  ) {
    return true;
  }
  return false;
};

export const getTraceFoldTitle = (
  eventType: string,
  eventRecord: Record<string, unknown>,
): string => {
  const lowerType = eventType.toLowerCase();
  if (lowerType.includes("thinking")) return "Thinking";
  if (lowerType.includes("tool")) {
    const block = getPrimaryTraceBlock(eventRecord);
    const toolName = block?.name;
    if (typeof toolName === "string" && toolName.trim()) {
      return toolName;
    }
    return "Tool";
  }
  return "Details";
};

export const getToolFieldText = (
  eventRecord: Record<string, unknown>,
  field: "tool_input" | "tool_output",
): string => {
  const block = getPrimaryTraceBlock(eventRecord);
  if (!block) return "";
  const blockType = String(block.type || "").toLowerCase();
  if (field === "tool_input" && blockType === "tool_use") {
    const rawInput = block.raw_input;
    if (typeof rawInput === "string" && rawInput.trim()) return rawInput;
    const input = block.input;
    if (input !== undefined) {
      try {
        return JSON.stringify(input, null, 2);
      } catch {
        return String(input);
      }
    }
  }
  if (field === "tool_output" && blockType === "tool_result") {
    const output = block.output;
    if (output !== undefined) {
      try {
        return JSON.stringify(output, null, 2);
      } catch {
        return String(output);
      }
    }
  }
  return "";
};

export const formatToolInput = (text: string): string => {
  if (!text.trim()) return "{}";
  return text;
};

export const formatToolBlockContent = (text: string): string => {
  const normalized = text.trim();
  if (!normalized) return "";
  try {
    const parsed = JSON.parse(normalized);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return text;
  }
};

export const normalizeDetailTaskName = (title: string): string => {
  if (!title) return "-";
  return title
    .replace(/^(cron result|heartbeat result)\s*[:：]\s*/i, "")
    .replace(/^(定时任务结果|心跳结果)\s*[:：]\s*/i, "")
    .trim();
};

export const getDetailModalTitle = (
  messageItem: PushMessage | null,
  t: (key: string, options?: Record<string, unknown>) => string,
): string => {
  if (!messageItem) return t("inbox.messageDetailTitle");
  const sourceType = (messageItem.metadata?.sourceType || "").toLowerCase();
  if (sourceType === "cron") {
    return t("inbox.detailCronTitle", {
      name: normalizeDetailTaskName(messageItem.title),
    });
  }
  if (sourceType === "heartbeat") {
    return t("inbox.detailHeartbeatTitle");
  }
  return messageItem.title || t("inbox.messageDetailTitle");
};

/**
 * Parse raw trace events into grouped display items with tool-call pairing.
 */
export const buildTraceDisplayItems = (
  rawEvents: Array<{ at: number; event: Record<string, unknown> }>,
): TraceDisplayItem[] => {
  if (!rawEvents.length) return [];

  const normalized = rawEvents
    .flatMap((item) => {
      const eventRecord = (item.event || {}) as Record<string, unknown>;
      const content = eventRecord.content;
      if (Array.isArray(content) && content.length > 1) {
        return content.map((block) => {
          const blockRecord = {
            ...eventRecord,
            content: [block],
          } as Record<string, unknown>;
          return {
            ...item,
            eventRecord: blockRecord,
            eventType: normalizeTraceKind(blockRecord),
          };
        });
      }
      const normalizedRecord =
        Array.isArray(content) && content.length === 1
          ? eventRecord
          : ({ ...eventRecord } as Record<string, unknown>);
      return [
        {
          ...item,
          eventRecord: normalizedRecord,
          eventType: normalizeTraceKind(normalizedRecord),
        },
      ];
    })
    .filter((item) => !shouldHideTraceEvent(item.eventType, item.eventRecord));

  const grouped: TraceDisplayItem[] = [];
  for (let i = 0; i < normalized.length; i += 1) {
    const current = normalized[i];
    const traceText = extractTraceText(current.eventRecord);
    const collapsible = isCollapsibleTraceEvent(
      current.eventType,
      current.eventRecord,
    );
    const collapseTitle = getTraceFoldTitle(
      current.eventType,
      current.eventRecord,
    );

    if (current.eventType === "tool_call") {
      const next = normalized[i + 1];
      const currentToolName = String(current.eventRecord.tool_name || "");
      const nextToolName = String(next?.eventRecord?.tool_name || "");
      const canPair =
        !!next &&
        next.eventType === "tool_output" &&
        (!!currentToolName || !!nextToolName)
          ? currentToolName === nextToolName
          : true;
      const toolInput = getToolFieldText(current.eventRecord, "tool_input");
      if (canPair && next) {
        const nextTraceText = extractTraceText(next.eventRecord);
        const toolOutput =
          getToolFieldText(next.eventRecord, "tool_output") || nextTraceText;
        grouped.push({
          at: current.at,
          eventType: "tool_call",
          eventRecord: current.eventRecord,
          traceText,
          collapsible: true,
          collapseTitle:
            collapseTitle ||
            getTraceFoldTitle(next.eventType, next.eventRecord),
          toolInput,
          toolOutput,
          renderKind: "tool_pair",
        });
        i += 1;
        continue;
      }
      grouped.push({
        at: current.at,
        eventType: current.eventType,
        eventRecord: current.eventRecord,
        traceText,
        collapsible: true,
        collapseTitle,
        toolInput,
        renderKind: "tool_pair",
      });
      continue;
    }

    if (current.eventType === "tool_output") {
      const toolOutput =
        getToolFieldText(current.eventRecord, "tool_output") || traceText;
      grouped.push({
        at: current.at,
        eventType: current.eventType,
        eventRecord: current.eventRecord,
        traceText,
        collapsible: true,
        collapseTitle,
        toolOutput,
        renderKind: "tool_pair",
      });
      continue;
    }

    grouped.push({
      at: current.at,
      eventType: current.eventType,
      eventRecord: current.eventRecord,
      traceText,
      collapsible,
      collapseTitle,
      renderKind: "normal",
    });
  }
  return grouped;
};
