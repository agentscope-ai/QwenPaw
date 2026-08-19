import { chatApi } from "../../api/modules/chat";
import { parseInternalFileLink } from "./internalFileLinks";
import type { FileTarget, SessionArtifact, SessionArtifactKind } from "./types";

const FILE_IO_TOOL_NAMES = new Set(["appendfile", "editfile", "writefile"]);
const TOOL_CALL_MESSAGE_TYPES = new Set([
  "tool_call",
  "plugin_call",
  "function_call",
  "mcp_call",
  "component_call",
]);
const TOOL_OUTPUT_MESSAGE_TYPES = new Set([
  "tool_call_output",
  "plugin_call_output",
  "function_call_output",
  "mcp_call_output",
  "component_call_output",
]);
const FAILED_TOOL_STATES = new Set([
  "cancelled",
  "canceled",
  "denied",
  "error",
  "failed",
  "interrupted",
  "rejected",
]);

interface ToolCallArtifactEvent {
  kind: "tool_call";
  callId: string;
  toolName: string;
  params: Record<string, unknown>;
  hasInlineResult: boolean;
}

type ArtifactEvent = ToolCallArtifactEvent;

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function parsedRecord(value: unknown): Record<string, unknown> | null {
  const direct = record(value);
  if (direct) return direct;
  if (typeof value !== "string") return null;
  try {
    return record(JSON.parse(value));
  } catch {
    return null;
  }
}

function firstString(
  value: Record<string, unknown>,
  keys: readonly string[],
): string {
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return "";
}

function filename(path: string): string {
  const clean = path.split(/[?#]/, 1)[0].replace(/\\/g, "/");
  return clean.split("/").filter(Boolean).pop() || "file";
}

function kindFromPath(path: string): SessionArtifactKind {
  if (/\.(?:png|jpe?g|gif|webp|svg|ico|bmp)(?:[?#]|$)/i.test(path)) {
    return "image";
  }
  if (/\.(?:mp3|wav|flac|aac|ogg|wma)(?:[?#]|$)/i.test(path)) {
    return "audio";
  }
  if (/\.(?:mp4|avi|mov|mkv|webm)(?:[?#]|$)/i.test(path)) {
    return "video";
  }
  return "file";
}

function isTrackedFileIoTool(toolName: string): boolean {
  return FILE_IO_TOOL_NAMES.has(
    toolName.replace(/[^a-z\d]/gi, "").toLowerCase(),
  );
}

function targetFor(path: string): FileTarget | null {
  const normalizedPath = path.trim().replace(/\\/g, "/");
  const workspaceTarget = parseInternalFileLink(
    normalizedPath.replace(/^(?:\.\/)+/, ""),
  );
  if (workspaceTarget) {
    return { ...workspaceTarget, root: "project" };
  }
  if (
    normalizedPath.startsWith("/") ||
    /^[a-z]:\//i.test(normalizedPath) ||
    normalizedPath.startsWith("~")
  ) {
    return {
      source: "attachment",
      path: normalizedPath,
      artifactUrl: chatApi.filePreviewUrl(normalizedPath),
    };
  }
  return null;
}

function addArtifact(
  artifacts: Map<string, SessionArtifact>,
  path: string,
  toolName?: string,
): void {
  const target = targetFor(path);
  if (!target) return;
  const displayPath = path || target.path;
  const name = filename(displayPath);
  const key = `${target.source}:${target.path}`;
  artifacts.delete(key);
  artifacts.set(key, {
    id: key,
    name,
    path: displayPath,
    kind: kindFromPath(name || displayPath),
    target,
    toolName,
  });
}

function contentData(item: Record<string, unknown>): Record<string, unknown> {
  const content = Array.isArray(item.content) ? item.content : [];
  return record(record(content[0])?.data) ?? {};
}

function toolCallId(
  item: Record<string, unknown>,
  data: Record<string, unknown>,
): string {
  return (
    firstString(data, ["call_id", "tool_call_id", "id"]) ||
    firstString(item, ["call_id", "tool_call_id", "id"])
  );
}

function toolResultSucceeded(
  item: Record<string, unknown>,
  data: Record<string, unknown>,
): boolean {
  const state = (
    firstString(data, ["state"]) || firstString(item, ["state", "status"])
  ).toLowerCase();
  if (FAILED_TOOL_STATES.has(state)) return false;
  return state === "success" || state === "completed";
}

function toolResultFailed(
  item: Record<string, unknown>,
  data: Record<string, unknown>,
): boolean {
  const state = (
    firstString(data, ["state"]) || firstString(item, ["state", "status"])
  ).toLowerCase();
  return FAILED_TOOL_STATES.has(state);
}

function collectArtifactEvents(
  value: unknown,
  events: ArtifactEvent[],
  successfulResults: Set<string>,
  seen: WeakSet<object>,
): void {
  if (!value || typeof value !== "object") return;
  if (seen.has(value as object)) return;
  seen.add(value as object);

  if (Array.isArray(value)) {
    value.forEach((item) =>
      collectArtifactEvents(item, events, successfulResults, seen),
    );
    return;
  }

  const item = value as Record<string, unknown>;
  const type = typeof item.type === "string" ? item.type : "";
  if (TOOL_CALL_MESSAGE_TYPES.has(type)) {
    const callData = contentData(item);
    const toolName =
      firstString(item, ["name"]) || firstString(callData, ["name"]);
    events.push({
      kind: "tool_call",
      callId: toolCallId(item, callData) || `inline-tool-call-${events.length}`,
      toolName,
      params:
        parsedRecord(item.params) ??
        parsedRecord(item.arguments) ??
        parsedRecord(callData.arguments) ??
        {},
      hasInlineResult:
        item.result !== undefined && !toolResultFailed(item, callData),
    });
    return;
  }

  if (TOOL_OUTPUT_MESSAGE_TYPES.has(type)) {
    const outputData = contentData(item);
    const callId = toolCallId(item, outputData);
    if (callId && toolResultSucceeded(item, outputData)) {
      successfulResults.add(callId);
    }
    return;
  }

  Object.values(item).forEach((child) =>
    collectArtifactEvents(child, events, successfulResults, seen),
  );
}

/** Collect files changed by WriteFile, EditFile, or AppendFile in this Session. */
export function extractSessionArtifacts(messages: unknown): SessionArtifact[] {
  const artifacts = new Map<string, SessionArtifact>();
  const events: ArtifactEvent[] = [];
  const successfulResults = new Set<string>();
  if (!Array.isArray(messages)) return [];
  for (const message of messages) {
    const item = record(message);
    if (!item || item.role === "user") continue;
    collectArtifactEvents(item, events, successfulResults, new WeakSet());
  }
  for (const event of events) {
    if (!isTrackedFileIoTool(event.toolName)) continue;
    if (!event.hasInlineResult && !successfulResults.has(event.callId))
      continue;
    const path = firstString(event.params, ["file_path"]);
    if (path) addArtifact(artifacts, path, event.toolName);
  }
  return Array.from(artifacts.values()).reverse();
}

function artifactSignature(artifact: SessionArtifact): string {
  return `${artifact.id}:${artifact.toolName ?? ""}`;
}

export function mergeSessionArtifacts(
  ...groups: SessionArtifact[][]
): SessionArtifact[] {
  const merged = new Map<string, SessionArtifact>();
  for (const group of groups) {
    for (let index = group.length - 1; index >= 0; index -= 1) {
      const artifact = group[index];
      merged.delete(artifact.id);
      merged.set(artifact.id, artifact);
    }
  }
  return Array.from(merged.values()).reverse();
}

export function sessionArtifactsEqual(
  left: SessionArtifact[],
  right: SessionArtifact[],
): boolean {
  return (
    left.length === right.length &&
    left.every(
      (artifact, index) =>
        artifactSignature(artifact) === artifactSignature(right[index]),
    )
  );
}

/**
 * Incrementally rebuild the small subset of the SDK response model needed for
 * artifact extraction. This consumes raw SSE payloads before the chat SDK
 * batches or merges them into its rendering state.
 */
export class SessionArtifactSseCollector {
  private readonly messages = new Map<string, Record<string, unknown>>();
  private currentArtifacts: SessionArtifact[] = [];

  reset(): void {
    this.messages.clear();
    this.currentArtifacts = [];
  }

  ingest(payload: unknown): SessionArtifact[] {
    const event = record(payload);
    if (!event) return this.artifacts();

    let changed = false;
    if (event.object === "response" && Array.isArray(event.output)) {
      event.output.forEach((message) => {
        changed = this.upsertMessage(message) || changed;
      });
    } else if (event.object === "message") {
      changed = this.upsertMessage(event);
    } else if (event.object === "content" && event.type === "data") {
      changed = this.mergeContent(event);
    }

    if (changed) {
      this.currentArtifacts = extractSessionArtifacts([
        {
          role: "assistant",
          content: Array.from(this.messages.values()),
        },
      ]);
    }
    return this.artifacts();
  }

  artifacts(): SessionArtifact[] {
    return this.currentArtifacts;
  }

  private upsertMessage(value: unknown): boolean {
    const message = record(value);
    const id = message ? firstString(message, ["id", "msg_id"]) : "";
    const type = message ? firstString(message, ["type"]) : "";
    if (
      !message ||
      !id ||
      (!TOOL_CALL_MESSAGE_TYPES.has(type) &&
        !TOOL_OUTPUT_MESSAGE_TYPES.has(type))
    ) {
      return false;
    }
    const current = this.messages.get(id);
    const incomingContent = Array.isArray(message.content)
      ? message.content
      : [];
    this.messages.set(id, {
      ...current,
      ...message,
      content:
        incomingContent.length > 0
          ? incomingContent
          : Array.isArray(current?.content)
          ? current.content
          : [],
    });
    return true;
  }

  private mergeContent(event: Record<string, unknown>): boolean {
    const messageId = firstString(event, ["msg_id"]);
    if (!messageId) return false;
    const message = this.messages.get(messageId);
    if (!message) return false;

    const content = Array.isArray(message.content) ? [...message.content] : [];
    const index =
      typeof event.index === "number" && event.index >= 0
        ? event.index
        : Math.max(0, content.length - 1);
    const current = record(content[index]) ?? {};
    const next = { ...current, ...event };

    if (event.delta === true) {
      if (event.type === "data") {
        const currentData = record(current.data) ?? {};
        const incomingData = record(event.data) ?? {};
        const mergedData = { ...currentData };
        for (const [key, value] of Object.entries(incomingData)) {
          mergedData[key] =
            typeof value === "string" && typeof currentData[key] === "string"
              ? `${currentData[key]}${value}`
              : value;
        }
        next.data = mergedData;
      } else if (event.type === "text" && typeof event.text === "string") {
        next.text = `${typeof current.text === "string" ? current.text : ""}${
          event.text
        }`;
      }
    }

    content[index] = next;
    this.messages.set(messageId, { ...message, content });
    return true;
  }
}
