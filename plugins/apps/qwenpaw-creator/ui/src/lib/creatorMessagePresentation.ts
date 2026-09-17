import type {
  CreatorContentPart,
  CreatorEvent,
  CreatorMessage,
  ProjectDocument,
} from "@/contracts/creator";
import i18n from "@/i18n";
import {
  creatorTargetLabel,
  humanizeCreatorRefs,
} from "@/lib/creatorPresentation";

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
const RUNTIME_ACTIONS = new Set([
  "plan",
  "tool_call",
  "final",
  "yield_until_runtime_event",
  "complete_current_change",
]);

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
  project?: ProjectDocument | null,
): CreatorContentPart[] {
  const content = withoutLegacyFileRuntimePlaceholder(message);
  if (message.role !== "assistant") return content;
  return content.flatMap<CreatorContentPart>((part) => {
    if (part.type !== "text") return [part];
    const text = publicAssistantText(part.text, {
      streaming: message.metadata?.streaming === true,
      project,
    });
    return text ? [{ ...part, text }] : [];
  });
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

/** Parse the first complete object; following public prose is not JSON. */
function jsonObjectPrefix(raw: string): Record<string, unknown> | undefined {
  let depth = 0;
  let quoted = false;
  let escaped = false;
  for (let index = 0; index < raw.length; index += 1) {
    const character = raw[index];
    if (quoted) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') quoted = false;
      continue;
    }
    if (character === '"') quoted = true;
    else if (character === "{" || character === "[") depth += 1;
    else if (character === "}" || character === "]") {
      depth -= 1;
      if (depth === 0) {
        try {
          const value = JSON.parse(raw.slice(0, index + 1)) as unknown;
          return isRecord(value) ? value : undefined;
        } catch {
          return undefined;
        }
      }
    }
  }
  return undefined;
}

function actionEnvelopeFromText(
  raw: string,
  partIndex: number,
  metadataPayload?: Record<string, unknown>,
): CreatorActionEnvelope | null {
  const fencePattern = /```(?:json)?[ \t]*(?:\r?\n|(?=\{))/giu;
  const fences = [...raw.matchAll(fencePattern)];
  for (const fence of fences) {
    if (fence.index === undefined) continue;
    // A closing fence followed by prose is not another pending action block.
    if ((raw.slice(0, fence.index).match(/```/gu)?.length ?? 0) % 2 === 1)
      continue;
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
      // An incomplete action must never flash into the public conversation.
    }
    const payload = metadataPayload ?? parsedPayload;
    const action =
      typeof payload?.action === "string"
        ? payload.action
        : partialJsonString(rawPayload, "action");
    if (
      parsedPayload &&
      action &&
      !RUNTIME_ACTIONS.has(action) &&
      !parsedPayload.tool &&
      !parsedPayload.arguments
    )
      continue;
    if (!action && closingIndex >= 0) continue;
    // Hold an unclosed JSON block until it can be distinguished from the
    // runtime envelope. Completed ordinary JSON remains public model output.
    if (!action && parsedPayload) continue;
    const tool =
      typeof payload?.tool === "string"
        ? payload.tool
        : partialJsonString(rawPayload, "tool");
    return {
      partIndex,
      narration: raw.slice(0, fence.index).trimEnd(),
      rawPayload,
      payload,
      action: action ?? "",
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
      narration: raw
        .slice(0, functionMatch.index)
        .replace(/<tool_call>\s*$/u, "")
        .trimEnd(),
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

  // Function/JSON markers can be split at any byte boundary by SSE.
  const angleIndex = raw.lastIndexOf("<");
  const angleSuffix = raw.slice(angleIndex);
  const pendingFunction =
    angleIndex >= 0 &&
    ["<function=", "<tool_call>"].some(
      (marker) =>
        marker.startsWith(angleSuffix) || angleSuffix.startsWith(marker),
    );
  const lastLineIndex = raw.lastIndexOf("\n") + 1;
  const lastLine = raw.slice(lastLineIndex).trimStart();
  const precedingFences =
    raw.slice(0, lastLineIndex).match(/```/gu)?.length ?? 0;
  const pendingFence =
    precedingFences % 2 === 0 &&
    Boolean(lastLine) &&
    "```json".startsWith(lastLine.toLowerCase());
  const bareJson = /(?:^|\n)[ \t]*(\{[\s\S]*)$/u.exec(raw);
  let barePayload: Record<string, unknown> | undefined;
  let bareAction: string | undefined;
  let pendingBare = false;
  if (
    bareJson &&
    (raw.slice(0, bareJson.index).match(/```/gu)?.length ?? 0) % 2 === 0
  ) {
    barePayload = jsonObjectPrefix(bareJson[1]);
    bareAction =
      typeof barePayload?.action === "string"
        ? barePayload.action
        : partialJsonString(bareJson[1], "action");
    // Field order is not guaranteed. Buffer an incomplete object rather than
    // leaking arguments when the action key arrives later in the stream.
    pendingBare = !barePayload || Boolean(bareAction);
    if (
      barePayload &&
      bareAction &&
      !RUNTIME_ACTIONS.has(bareAction) &&
      !barePayload.tool &&
      !barePayload.arguments
    )
      pendingBare = false;
  }
  const toolContainerIndex = raw.lastIndexOf("<tool_call>", angleIndex);
  let pendingIndex = -1;
  if (pendingFunction)
    pendingIndex = toolContainerIndex >= 0 ? toolContainerIndex : angleIndex;
  else if (pendingFence) pendingIndex = lastLineIndex;
  else if (pendingBare) pendingIndex = bareJson!.index;
  if (pendingIndex >= 0) {
    return {
      partIndex,
      narration: raw.slice(0, pendingIndex).trimEnd(),
      rawPayload: raw.slice(pendingIndex).trim(),
      payload: pendingBare ? barePayload : undefined,
      action: bareAction ?? "",
      complete: Boolean(barePayload),
      syntax: pendingFunction ? "function" : "json",
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

export interface PublicAssistantTextOptions {
  streaming?: boolean;
  project?: ProjectDocument | null;
}

/** Raw version ids sometimes appear as a final answer's entire code span.
 * Resolve only known project versions; URLs, fenced/indented code and larger
 * code expressions keep their original meaning. This is assistant-only. */
function publicVersionCodeNames(
  text: string,
  project?: ProjectDocument | null,
): string {
  if (!project) return text;
  const names = new Map<string, string>();
  for (const id of Object.keys(project.assets?.artifact_versions_by_id ?? {}))
    names.set(id, creatorTargetLabel(`artifact-version:${id}`, project));
  for (const id of Object.keys(project.assets?.source_versions_by_id ?? {}))
    if (!names.has(id))
      names.set(id, creatorTargetLabel(`asset-version:${id}`, project));
  if (names.size === 0) return text;

  let fence: { character: string; length: number } | null = null;
  return text
    .split("\n")
    .map((line) => {
      const marker =
        /^(?:[ \t]*(?:>[ \t]*)+)?[ \t]*(?:(?:[-+*]|\d+[.)])[ \t]+)?(`{3,}|~{3,})(.*)$/u.exec(
          line,
        );
      if (fence) {
        if (
          marker &&
          marker[1][0] === fence.character &&
          marker[1].length >= fence.length &&
          !marker[2].trim()
        )
          fence = null;
        return line;
      }
      if (marker && (marker[1][0] !== "`" || !marker[2].includes("`"))) {
        fence = { character: marker[1][0], length: marker[1].length };
        return line;
      }
      if (/^(?: {4}|\t)/u.test(line)) return line;
      return line.replace(
        /[A-Za-z][A-Za-z0-9+.-]*:\/\/[^\s<>]+|(?<![`\\])(`+)([^`\n]+)\1(?!`)/gu,
        (token, _delimiter: string | undefined, id: string | undefined) =>
          id === undefined ? token : names.get(id) ?? token,
      );
    })
    .join("\n");
}

function publicDomainTerms(text: string): string {
  const labels: Record<string, string> = {
    "Edit Element": "editElement",
    "Timeline Element": "timelineElement",
    Timeline: "timeline",
    WorkGraph: "workGraph",
    SourceAssetVersion: "sourceAssetVersion",
    ArtifactVersion: "artifactVersion",
    "Runtime 通知": "runtimeNotification",
  };
  const translate = (term: string) =>
    i18n.t(`presentation.publicTerms.${labels[term]}`);
  let fenced = false;
  return text
    .split("\n")
    .map((line) => {
      if (/^\s*```/u.test(line)) {
        fenced = !fenced;
        return line;
      }
      // Authored copy is content, not runtime narration: keep exact titles,
      // dialogue, subtitles and examples even when their words match a type.
      if (
        fenced ||
        /^\s*(?:>\s*)?(?:\*\*)?(?:台词|对白|字幕|旁白|片名|标题|Dialogue|Caption|Narration|Title)(?:\*\*)?\s*[：:]/u.test(
          line,
        )
      )
        return line;
      let publicLine = line.replace(
        /《[^》]*》|“[^”]*”|https?:\/\/[^\s)]+|【系统自动消息\s*·\s*Runtime 通知】|`?(?:\b(?:Timeline Element|Edit Element|SourceAssetVersion|ArtifactVersion|WorkGraph|Timeline)\b|Runtime 通知)`?/gu,
        (token) => {
          if (
            token.startsWith("《") ||
            token.startsWith("“") ||
            token.startsWith("http")
          )
            return token;
          if (token.startsWith("【")) return translate("Runtime 通知");
          return translate(token.replace(/^`|`$/gu, ""));
        },
      );
      // English type names often have surrounding spaces in Chinese narration.
      // Remove only those next to the translated phrase, preserving authored copy.
      for (const term of Object.keys(labels).map(translate)) {
        if (!/^[\p{Script=Han}]+$/u.test(term)) continue;
        publicLine = publicLine
          .replace(
            new RegExp(`([\\p{Script=Han}])[ \\t]+(?=${term})`, "gu"),
            "$1",
          )
          .replace(
            new RegExp(`(${term})[ \\t]+(?=[\\p{Script=Han}])`, "gu"),
            "$1",
          );
      }
      return publicLine;
    })
    .join("\n");
}

const PROMPT_SYNC_CONTROL_FIELD =
  /\b(?:prompt_sync|plan_fingerprint|storyboard_prompt_fingerprint|video_prompt_fingerprint)\b/u;
const PROMPT_SYNC_CLEAR_ADVICE =
  /(?:清除|删除|重置)[^。\n]*(?:同步记录|同步元数据|指纹)|(?:clear|delete|reset)[^.!?\n]*(?:sync (?:record|metadata)|fingerprint)/iu;

/** Derived synchronization state is not an editing instruction. Keep authored
 * copy/code intact, but omit ordinary paragraphs that expose it or advise
 * deleting it. Never turn that implementation detail into a claimed status. */
function withoutPromptSyncControlNarration(text: string): string {
  let fence: { character: string; length: number } | null = null;
  const chunks = text.split(/(\n\s*\n)/u).map((raw, index) => {
    if (index % 2) return { raw, separator: true, lines: [], prose: "" };
    const lines = raw.split("\n").map((line) => {
      const marker =
        /^(?:[ \t]*(?:>[ \t]*)+)?[ \t]*(?:(?:[-+*]|\d+[.)])[ \t]+)?(`{3,}|~{3,})(.*)$/u.exec(
          line,
        );
      let protectedLine = Boolean(fence);
      if (fence) {
        if (
          marker &&
          marker[1][0] === fence.character &&
          marker[1].length >= fence.length &&
          !marker[2].trim()
        )
          fence = null;
      } else if (marker && (marker[1][0] !== "`" || !marker[2].includes("`"))) {
        fence = { character: marker[1][0], length: marker[1].length };
        protectedLine = true;
      }
      protectedLine ||=
        /^(?: {4}|\t)/u.test(line) ||
        /^\s*(?:>\s*)?(?:\*\*)?(?:台词|对白|字幕|旁白|片名|标题|Dialogue|Caption|Narration|Title)(?:\*\*)?\s*[：:]/u.test(
          line,
        );
      const prose = protectedLine
        ? ""
        : line.replace(
            /《[^》]*》|“[^”]*”|「[^」]*」|『[^』]*』|[A-Za-z][A-Za-z0-9+.-]*:\/\/[^\s<>]+/gu,
            "",
          );
      return { line, protectedLine, prose };
    });
    return {
      raw,
      separator: false,
      lines,
      prose: lines.map((line) => line.prose).join("\n"),
    };
  });
  if (!chunks.some((chunk) => PROMPT_SYNC_CONTROL_FIELD.test(chunk.prose)))
    return text;
  return chunks
    .map((chunk) => {
      if (
        chunk.separator ||
        (!PROMPT_SYNC_CONTROL_FIELD.test(chunk.prose) &&
          !PROMPT_SYNC_CLEAR_ADVICE.test(chunk.prose))
      )
        return chunk.raw;
      return chunk.lines
        .filter((line) => line.protectedLine)
        .map((line) => line.line)
        .join("\n");
    })
    .join("");
}

/**
 * Only public prose belongs in assistant bubbles. This deliberately does not
 * summarize thinking, argument JSON, results, or runtime feedback into prose.
 */
export function publicAssistantText(
  raw: string,
  { streaming = true, project }: PublicAssistantTextOptions = {},
): string {
  let text = raw
    .replace(/^\s*\[(?:SUCCESS|BLOCKED|FAILED)\]\s*/u, "")
    .replace(/<(think|thinking|analysis)>[\s\S]*?(?:<\/\1>|$)/giu, "");
  if (streaming) {
    const index = text.lastIndexOf("<");
    if (
      index >= 0 &&
      ["<think>", "<thinking>", "<analysis>"].some((tag) =>
        tag.startsWith(text.slice(index)),
      )
    )
      text = text.slice(0, index);
  }
  // This exact backend review continuation template describes orchestration.
  // Preserve the review decision while omitting internal delegation mechanics.
  text = text.replace(
    /[^。\n]*的产物已生成，后续步骤尚未开始。请先完成审阅；审阅通过后，?主线需重新委派同一目标以继续(?:后续步骤)?。|当前产物已生成，后续步骤尚未开始。请先完成审阅；审阅通过后主线需重新委派同一目标以继续。/gu,
    i18n.t("agentActivity.reviewHint"),
  );
  const envelope = actionEnvelopeFromText(text, 0);
  if (envelope) {
    const finalMessage =
      envelope.action === "final" &&
      typeof envelope.payload?.message === "string"
        ? envelope.payload.message
        : "";
    text = [
      ...new Set([envelope.narration, finalMessage].filter(Boolean)),
    ].join("\n\n");
  }
  const runtimeMarker = RESERVED_RUNTIME_MARKER.exec(text);
  if (runtimeMarker?.index !== undefined) {
    const paragraphStart = text.lastIndexOf("\n\n", runtimeMarker.index);
    text = paragraphStart < 0 ? "" : text.slice(0, paragraphStart);
  }
  text = withoutPromptSyncControlNarration(text);
  // Runtime feedback can accidentally be copied into assistant narration.
  // Reject that paragraph, including its payload, rather than printing a
  // marker-free machine result or inventing a user-facing summary.
  text = text
    .split(/\n\s*\n/u)
    .filter(
      (paragraph) =>
        // These are model self-instructions observed during real creation.
        // The actual tool activity already supplies the public progress row.
        !/^\s*(?:Now (?:let me\b|I need to\b)|Let me (?:write|set up|add|update|fix)\b)/iu.test(
          paragraph,
        ) &&
        !RESERVED_RUNTIME_MARKER.test(paragraph) &&
        !BARE_CONTROL_CODE_LINE.test(paragraph) &&
        !/(?:"(?:tool_call|toolCallId|actionId|runId|targetRefs|elements_by_id|artifact_versions_by_id)"\s*:|\b(?:elements_by_id|source_versions_by_id|artifact_versions_by_id|schema_version|min_dialogue_ratio|storyboard_prompt|video_prompt)\b)/u.test(
          paragraph,
        ),
    )
    .join("\n\n");
  return publicVersionCodeNames(
    publicDomainTerms(humanizeCreatorRefs(text, project)),
    project,
  ).trim();
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
  project?: ProjectDocument | null,
): CreatorContentPart[] {
  const visibleContent = conversationContent(message, project);
  const finalMessage =
    envelope?.action === "final" &&
    typeof envelope.payload?.message === "string"
      ? publicAssistantText(envelope.payload.message, {
          streaming: false,
          project,
        })
      : "";
  const existingText = visibleContent
    .filter(
      (part): part is Extract<CreatorContentPart, { type: "text" }> =>
        part.type === "text",
    )
    .map((part) => part.text.trim());
  return finalMessage &&
    !existingText.some(
      (part) => part === finalMessage || part.endsWith(`\n\n${finalMessage}`),
    )
    ? [...visibleContent, { type: "text", text: finalMessage }]
    : visibleContent;
}

export interface ToolCallPresentation {
  actionId: string;
  anchorMessageId?: string;
  order: number;
  status: "started" | "succeeded" | "failed" | "cancelled";
  /** The owning run was explicitly replaced by a later request. */
  superseded?: boolean;
  /** A finished request may have started no media work. */
  productionOutcome?:
    | "waiting_review"
    | "not_started"
    | "unconfirmed"
    | "incomplete";
  /** True only after execution started, never inferred from argument bytes. */
  executing?: boolean;
  /** Outstanding persisted authorization events for this exact tool call. */
  waitingAuthorization?: boolean;
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
  runId?: string;
  anchorMessageId?: string;
  order: number;
  tool?: string;
  arguments?: Record<string, unknown>;
  completed: boolean;
  executing: boolean;
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

const BEFORE_PRODUCTION_REASONS = new Set([
  "TARGET_NOT_FOUND",
  "WAITING_REVIEW",
  "EDIT_IN_PROGRESS",
  "GATED",
  "READY",
  "STALE",
  "FAILED",
  "UNSUPPORTED_EXECUTION_MODE",
  "SCENE_REVIEW_REQUIRED",
  "MOTION_DESIGN_REQUIRED",
  "MODEL_RENDER_REVIEW_ENABLED",
  "INPUTS_NOT_READY",
  "APPROVED_INPUTS_CHANGED",
]);

function productionOutcome(
  call: MutableToolCall,
): ToolCallPresentation["productionOutcome"] {
  if (
    call.tool !== "request_workgraph_execution" ||
    !call.completed ||
    call.failed ||
    !isRecord(call.result)
  )
    return undefined;
  const { status, items } = call.result;
  if (status === "PARTIAL") return "incomplete";
  if (status !== "BLOCKED") return undefined;
  if (!Array.isArray(items) || items.length === 0) return "unconfirmed";
  if (
    items.every(
      (item) =>
        isRecord(item) &&
        item.status === "BLOCKED" &&
        item.reason === "WAITING_REVIEW" &&
        !item.taskId,
    )
  )
    return "waiting_review";
  return items.every(
    (item) =>
      isRecord(item) &&
      item.status === "BLOCKED" &&
      !item.taskId &&
      typeof item.reason === "string" &&
      BEFORE_PRODUCTION_REASONS.has(item.reason),
  )
    ? "not_started"
    : "unconfirmed";
}

/** Merge durable envelopes, Runtime result rows, and SSE by actionId. */
export function toolCallPresentations(
  messages: CreatorMessage[],
  events: CreatorEvent[],
): ToolCallPresentation[] {
  const calls = new Map<string, MutableToolCall>();
  const pendingAuthorizations = new Map<string, Set<string>>();
  const decidedAuthorizations = new Set<string>();
  const terminalRuns = new Map<
    string,
    { failed: boolean; superseded: boolean }
  >();
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
      executing: false,
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
        if (typeof message.metadata?.runId === "string")
          call.runId = message.metadata.runId;
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
      if (typeof message.metadata?.runId === "string")
        call.runId = message.metadata.runId;
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
        event.type === "agent.run.cancelled" ||
        event.type === "agent.run.failed"
      ) {
        if (typeof event.data.runId === "string") {
          terminalRuns.set(event.data.runId, {
            failed: event.type === "agent.run.failed",
            superseded: event.data.superseded === true,
          });
        }
        return;
      }
      if (
        event.type === "execution.authorization_required" ||
        event.type === "execution.authorization_decided" ||
        event.type === "creation.checkpoint_required" ||
        event.type === "creation.checkpoint_decided"
      ) {
        const callId = event.data.toolCallId;
        const authorizationId = event.data.authorizationId;
        if (
          typeof authorizationId === "string" &&
          event.type.endsWith("_decided")
        ) {
          // A replacement main run may reuse the same durable request with a
          // new call id. Its decision settles every older reference too.
          decidedAuthorizations.add(authorizationId);
          pendingAuthorizations.forEach((pending) =>
            pending.delete(authorizationId),
          );
        } else if (
          typeof callId === "string" &&
          typeof authorizationId === "string" &&
          !decidedAuthorizations.has(authorizationId)
        ) {
          const pending =
            pendingAuthorizations.get(callId) ?? new Set<string>();
          pending.add(authorizationId);
          pendingAuthorizations.set(callId, pending);
        }
        return;
      }
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
      if (typeof event.data.runId === "string") call.runId = event.data.runId;
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
      if (
        (event.type === "agent.tool_started" ||
          event.type === "agent.tool.started") &&
        !call.completed
      ) {
        call.executing = true;
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
    .map((call) => {
      const terminalRun =
        !call.completed && call.runId
          ? terminalRuns.get(call.runId)
          : undefined;
      return {
        actionId: call.actionId,
        anchorMessageId: call.anchorMessageId,
        order: call.order,
        status:
          call.failed || terminalRun?.failed
            ? "failed"
            : call.completed
            ? "succeeded"
            : terminalRun
            ? "cancelled"
            : "started",
        ...(terminalRun?.superseded ? { superseded: true } : {}),
        ...(productionOutcome(call)
          ? { productionOutcome: productionOutcome(call) }
          : {}),
        executing: call.executing && !call.completed && !terminalRun,
        ...(!call.completed &&
        !terminalRun &&
        pendingAuthorizations.get(call.actionId)?.size
          ? { waitingAuthorization: true }
          : {}),
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
      };
    });
}
