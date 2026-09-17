import type {
  CreatorContentPart,
  CreatorEvent,
  CreatorMessage,
} from "@/contracts/creator";
import i18n from "@/i18n";

const USER_AUTHORITY_SOURCES = new Set([
  "user",
  "initial_goal",
  "agent_dock",
  "review_revise",
  "user_direct",
  "user_intervention",
  "user_continuation",
  "authorization_denied",
  "review_rejection_feedback",
]);

const RESERVED_RUNTIME_MARKER =
  /\[\s*(?:RUNTIME_EVENT\s*:[^\]\r\n]*|RUNTIME_[A-Z0-9_]+|CREATOR_[A-Z0-9_]*(?:REJECTED|EXHAUSTED))\s*\]/iu;
const BARE_CONTROL_CODE = /^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$/u;
const BARE_CONTROL_CODE_LINE =
  /(?:^|[\r\n])\s*[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\s*(?=$|[\r\n])/u;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/** Runtime feedback persists in the transcript for replay; not user UI. */
export function isRuntimeControlSource(source: string | undefined): boolean {
  if (!source) return false;
  return (
    source.startsWith("runtime_") ||
    source === "specialist_result" ||
    source === "creator_waiting" ||
    source.startsWith("completion_")
  );
}

/** Machine-owned enum/reason values are state, never user-facing prose. */
export function isTechnicalControlText(raw: string): boolean {
  const value = raw.trim();
  return (
    Boolean(value) &&
    (BARE_CONTROL_CODE.test(value) || RESERVED_RUNTIME_MARKER.test(value))
  );
}

function containsReservedRuntimeMarker(message: CreatorMessage): boolean {
  return message.content.some(
    (part) =>
      part.type === "text" &&
      (RESERVED_RUNTIME_MARKER.test(part.text) ||
        BARE_CONTROL_CODE_LINE.test(part.text)),
  );
}

export function isUserAuthorityMessage(message: CreatorMessage): boolean {
  if (message.role !== "user") return false;
  const source = message.source;
  return Boolean(
    source &&
      (USER_AUTHORITY_SOURCES.has(source) || source.startsWith("frontend_")),
  );
}

export function shouldRenderConversationMessage(
  message: CreatorMessage,
): boolean {
  if (isRuntimeControlSource(message.source)) return false;
  // File Runtime used to persist tool results as ordinary transcript rows.
  // They remain useful for rebuilding the tool card, but must not appear as a
  // second machine-authored conversation bubble.
  if (message.role === "tool" && message.source === "file_agent_runtime")
    return false;
  if (message.role === "user") {
    // Reserved control markers are never user-authored presentation even if a
    // malformed/legacy row accidentally carries source=user.
    if (containsReservedRuntimeMarker(message)) return false;
    return isUserAuthorityMessage(message);
  }
  return true;
}

export function isReviewFeedbackMessage(message: CreatorMessage): boolean {
  return (
    message.source === "review_rejection_feedback" &&
    typeof message.metadata?.decisionId === "string" &&
    isRecord(message.metadata?.rejectionFeedback)
  );
}

/**
 * Recovery and request replay may expose the same durable Review decision
 * more than once. The decision id is the user-visible semantic identity, so
 * render only its earliest transcript row.
 */
export function deduplicateReviewFeedbackMessages(
  messages: CreatorMessage[],
): CreatorMessage[] {
  const firstByDecision = new Map<string, CreatorMessage>();
  messages.forEach((message) => {
    if (!isReviewFeedbackMessage(message)) return;
    const decisionId = String(message.metadata.decisionId);
    const current = firstByDecision.get(decisionId);
    if (!current || message.messageSeq < current.messageSeq) {
      firstByDecision.set(decisionId, message);
    }
  });
  return messages.filter((message) => {
    if (!isReviewFeedbackMessage(message)) return true;
    return firstByDecision.get(String(message.metadata.decisionId)) === message;
  });
}

function legacyFileRuntimeToolCalls(
  message: CreatorMessage,
): Record<string, unknown>[] {
  if (message.role !== "assistant" || message.source !== "file_agent_runtime")
    return [];
  return Array.isArray(message.metadata?.toolCalls)
    ? message.metadata.toolCalls.filter(isRecord)
    : [];
}

function toolCallName(toolCall: Record<string, unknown>): string | undefined {
  if (typeof toolCall.name === "string" && toolCall.name) return toolCall.name;
  if (typeof toolCall.tool === "string" && toolCall.tool) return toolCall.tool;
  if (typeof toolCall.toolName === "string" && toolCall.toolName)
    return toolCall.toolName;
  const function_ = isRecord(toolCall.function) ? toolCall.function : undefined;
  return typeof function_?.name === "string" && function_.name
    ? function_.name
    : undefined;
}

function withoutLegacyFileRuntimePlaceholder(
  message: CreatorMessage,
): CreatorContentPart[] {
  const toolCalls = legacyFileRuntimeToolCalls(message);
  if (toolCalls.length === 0) return message.content;
  const names = toolCalls.map(toolCallName);
  if (names.some((name) => !name)) return message.content;
  const placeholder = i18n.t("lib.prepareCallTool", {
    names: names.join("、"),
  });
  return message.content.filter(
    (part) => part.type !== "text" || part.text !== placeholder,
  );
}

export function conversationContent(
  message: CreatorMessage,
): CreatorContentPart[] {
  return withoutLegacyFileRuntimePlaceholder(message);
}

export interface CreatorActionEnvelope {
  partIndex: number;
  narration: string;
  rawPayload: string;
  payload?: Record<string, unknown>;
  action: string;
  tool?: string;
  complete: boolean;
  syntax: "json" | "function" | "native";
}

function parsedActionMetadata(
  message: CreatorMessage,
): Record<string, unknown> | undefined {
  return isRecord(message.metadata?.parsedAction)
    ? message.metadata.parsedAction
    : undefined;
}

function nativeToolCallMetadata(
  message: CreatorMessage,
): Record<string, unknown> | undefined {
  return isRecord(message.metadata?.toolCall)
    ? message.metadata.toolCall
    : undefined;
}

function nativeActionEnvelope(
  toolCall: Record<string, unknown>,
  narration: string,
): CreatorActionEnvelope | null {
  const name = typeof toolCall.name === "string" ? toolCall.name : "";
  if (!name) return null;
  const arguments_ = isRecord(toolCall.arguments)
    ? toolCall.arguments
    : undefined;
  const control = [
    "plan",
    "final",
    "yield_until_runtime_event",
    "complete_current_change",
  ].includes(name);
  const action = control ? name : "tool_call";
  const payload = arguments_
    ? control
      ? name === "yield_until_runtime_event" ||
        name === "complete_current_change"
        ? { action, arguments: arguments_ }
        : { action, ...arguments_ }
      : { action, tool: name, arguments: arguments_ }
    : undefined;
  const rawPayload = arguments_ ? JSON.stringify(arguments_) : "";
  return {
    partIndex: -1,
    narration,
    rawPayload,
    payload,
    action,
    tool: control ? undefined : name,
    complete: Boolean(arguments_),
    syntax: "native",
  };
}

function partialJsonString(raw: string, key: string): string | undefined {
  const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  const match = new RegExp(
    `"${escapedKey}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`,
    "u",
  ).exec(raw);
  if (!match) return undefined;
  try {
    return JSON.parse(`"${match[1]}"`) as string;
  } catch {
    return match[1];
  }
}

function parsedFunctionArguments(raw: string): Record<string, unknown> {
  const arguments_: Record<string, unknown> = {};
  const parameterPattern =
    /<parameter=([A-Za-z_][A-Za-z0-9_.-]*)>\s*([\s\S]*?)\s*<\/parameter>/gu;
  for (const match of raw.matchAll(parameterPattern)) {
    let value: unknown = match[2];
    try {
      value = JSON.parse(match[2]) as unknown;
    } catch {
      // A plain string parameter is still a valid, useful live preview.
    }
    if (match[1] === "arguments" && isRecord(value))
      Object.assign(arguments_, value);
    else arguments_[match[1]] = value;
  }
  return arguments_;
}

function actionEnvelopeFromText(
  raw: string,
  partIndex: number,
  metadataPayload?: Record<string, unknown>,
): CreatorActionEnvelope | null {
  const fencePattern = /```json\s*/giu;
  const fences = [...raw.matchAll(fencePattern)];
  const fence = fences.at(-1);
  if (fence?.index !== undefined) {
    const payloadStart = fence.index + fence[0].length;
    const suffix = raw.slice(payloadStart);
    const closingIndex = suffix.indexOf("```");
    const rawPayload = (
      closingIndex >= 0 ? suffix.slice(0, closingIndex) : suffix
    ).trim();
    let parsedPayload: Record<string, unknown> | undefined;
    try {
      const candidate = JSON.parse(rawPayload) as unknown;
      if (isRecord(candidate)) parsedPayload = candidate;
    } catch {
      // Partial JSON remains visible and keeps growing until it becomes valid.
    }
    const payload = metadataPayload ?? parsedPayload;
    const action =
      typeof payload?.action === "string"
        ? payload.action
        : partialJsonString(rawPayload, "action");
    if (!action) return null;
    const tool =
      typeof payload?.tool === "string"
        ? payload.tool
        : partialJsonString(rawPayload, "tool");
    return {
      partIndex,
      narration: raw.slice(0, fence.index).trimEnd(),
      rawPayload,
      payload,
      action,
      tool,
      complete:
        Boolean(payload) && (Boolean(metadataPayload) || closingIndex >= 0),
      syntax: "json",
    };
  }

  const functionMatch = /<function=([A-Za-z_][A-Za-z0-9_.-]*)>/u.exec(raw);
  if (functionMatch?.index !== undefined) {
    const rawPayload = raw.slice(functionMatch.index).trim();
    const complete = /<\/function>\s*(?:<\/tool_call>)?/u.test(rawPayload);
    const tool = functionMatch[1];
    return {
      partIndex,
      narration: raw.slice(0, functionMatch.index).trimEnd(),
      rawPayload,
      payload: complete
        ? {
            action: "tool_call",
            tool,
            arguments: parsedFunctionArguments(rawPayload),
          }
        : undefined,
      action: "tool_call",
      tool,
      complete,
      syntax: "function",
    };
  }

  if (metadataPayload && typeof metadataPayload.action === "string") {
    return {
      partIndex,
      narration: raw,
      rawPayload: JSON.stringify(metadataPayload),
      payload: metadataPayload,
      action: metadataPayload.action,
      tool:
        typeof metadataPayload.tool === "string"
          ? metadataPayload.tool
          : undefined,
      complete: true,
      syntax: "json",
    };
  }
  return null;
}

/** Detect the final machine action while its SSE text is still incomplete. */
export function actionEnvelopeFromStreamText(
  raw: string,
): CreatorActionEnvelope | null {
  return actionEnvelopeFromText(raw, 0);
}

export function creatorActionEnvelope(
  message: CreatorMessage,
): CreatorActionEnvelope | null {
  const native = nativeToolCallMetadata(message);
  if (native) {
    const narration = message.content
      .filter(
        (part): part is Extract<CreatorContentPart, { type: "text" }> =>
          part.type === "text",
      )
      .map((part) => part.text)
      .join("\n")
      .trim();
    return nativeActionEnvelope(native, narration);
  }
  const metadataPayload = parsedActionMetadata(message);
  for (let index = message.content.length - 1; index >= 0; index -= 1) {
    const part = message.content[index];
    if (part.type !== "text") continue;
    const envelope = actionEnvelopeFromText(part.text, index, metadataPayload);
    if (envelope) return envelope;
  }
  return null;
}

/** Keep prose/media in conversation; move machine syntax to its card. */
export function actionAwareConversationContent(
  message: CreatorMessage,
  envelope: CreatorActionEnvelope | null = creatorActionEnvelope(message),
): CreatorContentPart[] {
  const visibleContent = conversationContent(message);
  if (!envelope) return visibleContent;
  if (envelope.syntax === "native") {
    const finalMessage =
      envelope.action === "final" &&
      typeof envelope.payload?.message === "string"
        ? envelope.payload.message
        : "";
    const existingText = visibleContent
      .filter(
        (part): part is Extract<CreatorContentPart, { type: "text" }> =>
          part.type === "text",
      )
      .map((part) => part.text.trim())
      .filter(Boolean);
    return finalMessage && !existingText.includes(finalMessage)
      ? [...visibleContent, { type: "text", text: finalMessage }]
      : visibleContent;
  }
  return visibleContent.flatMap((part, index) => {
    if (index !== envelope.partIndex || part.type !== "text") return [part];
    const finalMessage =
      envelope.action === "final" &&
      typeof envelope.payload?.message === "string"
        ? envelope.payload.message
        : "";
    const text = [envelope.narration, finalMessage]
      .filter(
        (value, valueIndex, values) =>
          Boolean(value) && values.indexOf(value) === valueIndex,
      )
      .join("\n\n");
    return text ? [{ ...part, text }] : [];
  });
}

export interface ToolCallPresentation {
  actionId: string;
  anchorMessageId?: string;
  order: number;
  status: "started" | "succeeded" | "failed";
  tool: string;
  arguments?: Record<string, unknown>;
  argumentsText?: string;
  receivedBytes?: number;
  providerChunkCount?: number;
  argumentStreamComplete?: boolean;
  result?: unknown;
  error?: string;
}

interface MutableToolCall {
  actionId: string;
  anchorMessageId?: string;
  order: number;
  tool?: string;
  arguments?: Record<string, unknown>;
  completed: boolean;
  failed: boolean;
  result?: unknown;
  error?: string;
  argumentsText?: string;
  receivedBytes?: number;
  providerChunkCount?: number;
  argumentStreamComplete?: boolean;
}

function textContent(message: CreatorMessage): string {
  return message.content
    .filter(
      (part): part is Extract<CreatorContentPart, { type: "text" }> =>
        part.type === "text",
    )
    .map((part) => part.text)
    .join("\n")
    .trim();
}

function runtimeResultText(message: CreatorMessage): string {
  return textContent(message)
    .replace(/^\[[A-Z0-9_]+\]\s*/u, "")
    .trim();
}

function safeResult(message: CreatorMessage): unknown {
  const text = runtimeResultText(message);
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/** Merge durable envelopes, Runtime result rows, and SSE by actionId. */
export function toolCallPresentations(
  messages: CreatorMessage[],
  events: CreatorEvent[],
): ToolCallPresentation[] {
  const calls = new Map<string, MutableToolCall>();
  const ensure = (actionId: string, order: number) => {
    const existing = calls.get(actionId);
    if (existing) {
      existing.order = Math.min(existing.order, order);
      return existing;
    }
    const created: MutableToolCall = {
      actionId,
      order,
      completed: false,
      failed: false,
    };
    calls.set(actionId, created);
    return created;
  };

  [...messages]
    .sort((left, right) => left.messageSeq - right.messageSeq)
    .forEach((message) => {
      legacyFileRuntimeToolCalls(message).forEach((toolCall, index) => {
        const actionId =
          typeof toolCall.id === "string"
            ? toolCall.id
            : typeof toolCall.toolCallId === "string"
            ? toolCall.toolCallId
            : undefined;
        if (!actionId) return;
        const call = ensure(actionId, message.messageSeq + index / 1_000);
        call.anchorMessageId = message.messageId;
        call.tool = toolCallName(toolCall) ?? call.tool;
        const function_ = isRecord(toolCall.function)
          ? toolCall.function
          : undefined;
        const arguments_ = toolCall.arguments ?? function_?.arguments;
        if (isRecord(arguments_)) call.arguments = arguments_;
        else if (typeof arguments_ === "string") {
          call.argumentsText = arguments_;
          try {
            const parsed = JSON.parse(arguments_) as unknown;
            if (isRecord(parsed)) call.arguments = parsed;
          } catch {
            // Historical rows may only contain a partial argument string.
          }
        }
      });
      const actionId =
        typeof message.metadata?.actionId === "string"
          ? message.metadata.actionId
          : typeof message.metadata?.toolCallId === "string"
          ? message.metadata.toolCallId
          : undefined;
      if (!actionId) return;
      const call = ensure(actionId, message.messageSeq);
      const parsedAction = isRecord(message.metadata?.parsedAction)
        ? message.metadata.parsedAction
        : undefined;
      const nativeToolCall = isRecord(message.metadata?.toolCall)
        ? message.metadata.toolCall
        : undefined;
      if (message.role === "assistant" && nativeToolCall) {
        call.anchorMessageId = message.messageId;
        if (typeof nativeToolCall.name === "string")
          call.tool = nativeToolCall.name;
        if (isRecord(nativeToolCall.arguments))
          call.arguments = nativeToolCall.arguments;
      } else if (message.role === "assistant" && parsedAction) {
        call.anchorMessageId = message.messageId;
        if (typeof parsedAction.tool === "string")
          call.tool = parsedAction.tool;
        if (isRecord(parsedAction.arguments))
          call.arguments = parsedAction.arguments;
      }
      if (
        message.role === "tool" ||
        message.source === "runtime_action_result"
      ) {
        if (typeof message.metadata?.tool === "string")
          call.tool = message.metadata.tool;
        else if (typeof message.metadata?.toolName === "string")
          call.tool = message.metadata.toolName;
        call.completed = true;
        call.failed =
          message.metadata?.failed === true ||
          message.metadata?.cancelledByHardStop === true;
        if (call.failed) call.error = runtimeResultText(message);
        else call.result = safeResult(message);
      }
    });

  [...events]
    .sort((left, right) => left.seq - right.seq)
    .forEach((event) => {
      if (
        event.type === "assistant.output_rejected" ||
        event.type === "session.error"
      ) {
        const rejectedMessageId =
          typeof event.data.rejectedAssistantMessageId === "string"
            ? event.data.rejectedAssistantMessageId
            : typeof event.data.assistantMessageId === "string"
            ? event.data.assistantMessageId
            : undefined;
        if (rejectedMessageId) {
          for (const [actionId, call] of calls) {
            if (call.anchorMessageId === rejectedMessageId)
              calls.delete(actionId);
          }
        }
        return;
      }
      if (
        ![
          "agent.tool_progress",
          "agent.tool_started",
          "agent.tool_completed",
          "agent.tool.started",
          "agent.tool.completed",
          "agent.tool.failed",
        ].includes(event.type)
      )
        return;
      const actionId =
        typeof event.data.toolCallId === "string"
          ? event.data.toolCallId
          : typeof event.data.actionId === "string"
          ? event.data.actionId
          : undefined;
      if (!actionId) return;
      const call = ensure(
        actionId,
        Number.MAX_SAFE_INTEGER - 1_000_000 + event.seq,
      );
      if (typeof event.data.tool === "string") call.tool = event.data.tool;
      else if (typeof event.data.toolName === "string")
        call.tool = event.data.toolName;
      const dottedCompletion =
        event.type === "agent.tool.completed" ||
        event.type === "agent.tool.failed";
      if (
        typeof event.data.messageId === "string" &&
        (!dottedCompletion || !call.anchorMessageId)
      ) {
        call.anchorMessageId = event.data.messageId;
      }
      if (event.type === "agent.tool_progress") {
        if (typeof event.data.receivedBytes === "number")
          call.receivedBytes = event.data.receivedBytes;
        if (typeof event.data.providerChunkCount === "number")
          call.providerChunkCount = event.data.providerChunkCount;
        if (typeof event.data.complete === "boolean")
          call.argumentStreamComplete = event.data.complete;
      }
      if (isRecord(event.data.arguments)) {
        call.arguments = event.data.arguments;
      }
      if (
        event.type === "agent.tool_completed" ||
        event.type === "agent.tool.completed" ||
        event.type === "agent.tool.failed"
      ) {
        call.completed = true;
        if (
          event.type === "agent.tool.failed" ||
          event.data.failed === true ||
          event.data.cancelledByHardStop === true
        ) {
          call.failed = true;
          call.error =
            typeof event.data.error === "string"
              ? event.data.error
              : typeof event.data.errorType === "string"
              ? event.data.errorType
              : call.error;
        }
      }
    });

  return [...calls.values()]
    .filter(
      (call): call is MutableToolCall & { tool: string } =>
        Boolean(call.tool) &&
        ![
          "plan",
          "final",
          "yield_until_runtime_event",
          "complete_current_change",
        ].includes(call.tool ?? ""),
    )
    .sort((left, right) => left.order - right.order)
    .map((call) => ({
      actionId: call.actionId,
      anchorMessageId: call.anchorMessageId,
      order: call.order,
      status: call.failed ? "failed" : call.completed ? "succeeded" : "started",
      tool: call.tool,
      arguments: call.arguments,
      ...(call.argumentsText ? { argumentsText: call.argumentsText } : {}),
      result: call.result,
      error: call.error,
      ...(call.receivedBytes !== undefined
        ? { receivedBytes: call.receivedBytes }
        : {}),
      ...(call.providerChunkCount !== undefined
        ? { providerChunkCount: call.providerChunkCount }
        : {}),
      ...(call.argumentStreamComplete !== undefined
        ? { argumentStreamComplete: call.argumentStreamComplete }
        : {}),
    }));
}
