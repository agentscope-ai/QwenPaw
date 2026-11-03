import type { PushMessage } from "../types";
import { stripScrollHeadlines } from "../../Chat/headlineFilter";

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

const isToolCallBlockType = (blockType: string): boolean =>
  blockType === "tool_use" || blockType === "tool_call";

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
    isToolCallBlockType(blockType) ||
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
      return event.role === "assistant"
        ? stripScrollHeadlines(text)
        : text.trim();
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
  if (isToolCallBlockType(blockType)) {
    const rawInput = block.raw_input;
    if (typeof rawInput === "string" && rawInput.trim()) {
      return rawInput.trim();
    }
    const input = block.input;
    if (typeof input === "string" && input.trim()) {
      return input.trim();
    }
  }
  return "";
};

export const normalizeTraceKind = (event: Record<string, unknown>): string => {
  if (event.type === "response_completed") return "response_completed";
  const block = getPrimaryTraceBlock(event);
  const blockType = String(block?.type || "").toLowerCase();
  if (blockType === "thinking") return "thinking";
  if (isToolCallBlockType(blockType)) return "tool_call";
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
  const block = getPrimaryTraceBlock(eventRecord);
  const type = String(block?.type || "").toLowerCase();
  // Keep the existing attachment behavior; internal hints are not transcript.
  if (["image", "file", "audio", "video", "data", "hint"].includes(type)) {
    return true;
  }
  if (eventType === "event" && block && type && type !== "text") return false;
  if (
    eventType === "event" &&
    !block &&
    Object.keys(eventRecord).some(
      (key) => !["content", "role", "name", "id", "timestamp"].includes(key),
    )
  )
    return false;
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
  if (field === "tool_input" && isToolCallBlockType(blockType)) {
    const rawInput = block.raw_input;
    if (typeof rawInput === "string" && rawInput.trim()) return rawInput;
    const input = block.input;
    if (typeof input === "string") return input;
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

  let turn = 0;
  const normalized = rawEvents
    .flatMap((item) => {
      const eventRecord = (item.event || {}) as Record<string, unknown>;
      if (eventRecord.role === "user") turn += 1;
      const content =
        typeof eventRecord.content === "string"
          ? [{ type: "text", text: eventRecord.content }]
          : eventRecord.content;
      if (Array.isArray(content) && content.length > 1) {
        return content.map((block) => {
          const blockRecord = {
            ...eventRecord,
            content: [block],
          } as Record<string, unknown>;
          return {
            ...item,
            turn,
            eventRecord: blockRecord,
            eventType: normalizeTraceKind(blockRecord),
          };
        });
      }
      const normalizedRecord =
        Array.isArray(content) && content.length === 1
          ? { ...eventRecord, content }
          : ({ ...eventRecord } as Record<string, unknown>);
      return [
        {
          ...item,
          turn,
          eventRecord: normalizedRecord,
          eventType: normalizeTraceKind(normalizedRecord),
        },
      ];
    })
    .filter((item) => !shouldHideTraceEvent(item.eventType, item.eventRecord));

  const grouped: TraceDisplayItem[] = [];
  const pending = new Map<string, number[]>();
  const toolId = (record: Record<string, unknown>): string => {
    const block = getPrimaryTraceBlock(record);
    const id =
      block?.tool_use_id ?? block?.call_id ?? block?.id ?? record.tool_call_id;
    return typeof id === "string" ? id : "";
  };
  const toolName = (record: Record<string, unknown>): string =>
    String(getPrimaryTraceBlock(record)?.name || record.tool_name || "");

  for (let i = 0; i < normalized.length; i += 1) {
    const current = normalized[i];
    const { eventRecord, eventType } = current;
    if (current.turn !== normalized[i - 1]?.turn) pending.clear();
    const traceText = extractTraceText(eventRecord);
    const base = {
      at: current.at,
      eventType,
      eventRecord,
      traceText,
      collapsible:
        isCollapsibleTraceEvent(eventType, eventRecord) ||
        eventType === "event",
      collapseTitle: getTraceFoldTitle(eventType, eventRecord),
    };
    const id = toolId(eventRecord);
    if (eventType === "tool_call") {
      if (id) pending.set(id, [...(pending.get(id) || []), grouped.length]);
      grouped.push({
        ...base,
        collapsible: true,
        toolInput: getToolFieldText(eventRecord, "tool_input"),
        renderKind: "tool_pair",
      });
      continue;
    }
    if (eventType === "tool_output") {
      let callIndex = id ? pending.get(id)?.[0] : undefined;
      // Legacy traces without IDs: only pair an immediately adjacent call
      // and result when neither supplies an ID and their names agree.
      const previous = normalized[i - 1];
      if (
        !id &&
        previous?.eventType === "tool_call" &&
        previous.turn === current.turn &&
        !toolId(previous.eventRecord) &&
        toolName(previous.eventRecord) === toolName(eventRecord)
      ) {
        callIndex = grouped.length - 1;
      }
      const toolOutput =
        getToolFieldText(eventRecord, "tool_output") || traceText;
      if (callIndex !== undefined) {
        grouped[callIndex].toolOutput = toolOutput;
        if (id) pending.get(id)?.shift();
      } else {
        grouped.push({
          ...base,
          collapsible: true,
          toolOutput,
          renderKind: "tool_pair",
        });
      }
      continue;
    }
    grouped.push({ ...base, renderKind: "normal" });
  }
  return grouped;
};
