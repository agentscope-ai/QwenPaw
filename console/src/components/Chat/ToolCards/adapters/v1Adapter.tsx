/**
 * v1Adapter — bridges ChatV2 tool cards to ChatV1's @agentscope-ai/chat format.
 *
 * ChatV1 uses `customToolRenderConfig: Record<string, React.FC<any>>` where
 * the component receives @agentscope-ai/chat's internal props shape:
 *
 *   { data: { content: [{ data: { arguments, name, ... } }] }, ... }
 *
 * ChatV2 cards expect:
 *
 *   { content: ToolCallContent, isStreaming?: boolean }
 *
 * This adapter wraps each ChatV2 card so it can be used in ChatV1.
 */

import React from "react";
import type { ToolCallContent, ToolCallStatus } from "../shared/types";
import { useToolCallTurnEnded } from "../shared/ToolCallTurnContext";
import type { BuiltinCardComponent } from "../cards";
import GenericToolCard from "../cards/GenericToolCard";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STREAM_INPUT_PREVIEW_CHARS = 4 * 1024;
const ERROR_STATUSES = new Set(["failed", "rejected", "canceled"]);
const TOOL_ERROR_STATES = new Set(["error", "interrupted", "denied"]);

interface DerivedToolStatus {
  status: ToolCallStatus;
  /** Error status caused by an interruption rather than a tool failure. */
  interrupted: boolean;
}

/**
 * Derive the tool execution status from V1 message data.
 *
 * Checks the tool-execution-layer `state` (nested inside resultItem.data)
 * first — it reflects the real outcome of the tool call. Falls back to
 * message-level `status` for delivery state.
 *
 * *turnEnded* closes dangling calls: a call with no terminal marker (no
 * result block, or output that stopped mid-stream) is only running while its
 * turn streams. Once the turn ends nothing more can arrive, so the call is
 * reported as interrupted instead of spinning forever.
 */
function deriveToolStatus(
  resultItem: Record<string, unknown> | undefined,
  data: Record<string, unknown>,
  turnEnded: boolean,
): DerivedToolStatus {
  const unfinished: DerivedToolStatus = turnEnded
    ? { status: "error", interrupted: true }
    : { status: "calling", interrupted: false };
  if (!resultItem) return unfinished;

  const resultData = (resultItem?.data ?? {}) as Record<string, unknown>;
  const toolState = resultData.state as string;
  if (toolState && TOOL_ERROR_STATES.has(toolState)) {
    return { status: "error", interrupted: toolState === "interrupted" };
  }

  const rawStatus =
    (data.status as string) || (resultItem.status as string) || "";
  if (rawStatus === "completed") return { status: "done", interrupted: false };
  if (ERROR_STATUSES.has(rawStatus)) {
    return { status: "error", interrupted: rawStatus === "canceled" };
  }
  return unfinished;
}

// ---------------------------------------------------------------------------
// V1 props parsing
// ---------------------------------------------------------------------------

/**
 * Parse the props that @agentscope-ai/chat passes to custom tool renderers.
 *
 * From the @agentscope-ai/chat source (Tool.js):
 *
 *   var C = customToolRenderConfig[toolName];
 *   node = _jsx(C, { data: data });
 *
 * Where `data` has this shape:
 *   {
 *     content: [
 *       { data: { name, arguments, server_label, ... } },  // [0] = call
 *       { data: { output, ... } },                         // [1] = result
 *     ],
 *     status: "in_progress" | "completed" | "failed" | ...
 *   }
 */
function parseV1Props(
  v1Props: Record<string, unknown>,
  turnEnded: boolean,
): {
  content: ToolCallContent;
  isStreaming: boolean;
} {
  // v1Props = { data: { content: [...], status: ... } }
  const data = (v1Props?.data ?? v1Props) as Record<string, unknown>;
  const contentArray = data?.content as
    | Array<Record<string, unknown>>
    | undefined;

  // content[0].data = tool call info (name, arguments)
  const callItem = contentArray?.[0];
  const callData = (callItem?.data ?? {}) as Record<string, unknown>;

  // content[1].data = tool result (output)
  const resultItem = contentArray?.[1];
  const resultData = (resultItem?.data ?? {}) as Record<string, unknown>;

  // Extract tool name
  const toolName = (callData.name as string) || "unknown";

  // Extract arguments (may be a JSON string or an object)
  let params: Record<string, unknown> = {};
  const rawArgs = callData.arguments;
  const isInputStreaming = callItem?.delta === true;
  const inputProgress =
    isInputStreaming && typeof rawArgs === "string"
      ? {
          preview: rawArgs.slice(-STREAM_INPUT_PREVIEW_CHARS),
          truncated: rawArgs.length > STREAM_INPUT_PREVIEW_CHARS,
        }
      : undefined;
  if (!isInputStreaming && typeof rawArgs === "string") {
    try {
      params = JSON.parse(rawArgs);
    } catch {
      params = {};
    }
  } else if (!isInputStreaming && rawArgs && typeof rawArgs === "object") {
    params = rawArgs as Record<string, unknown>;
  }

  // Extract result from content[1].data.output
  const result = resultData.output;

  // Message-level status on *_call messages reflects delivery, not execution,
  // so the presence of an output block decides between running and finished.
  const { status, interrupted } = deriveToolStatus(resultItem, data, turnEnded);

  // Extract id — prefer call_id which carries the ToolCallBlock.id
  // (e.g. "toolu_…" / "call_…") from the AgentScope SSE stream.
  // It is set in the backend at FunctionCall.call_id
  // (see agentscope/message.py → FunctionCall dataclass).
  const toolId =
    (callData.call_id as string) ||
    (callData.id as string) ||
    (data.id as string) ||
    `v1-${toolName}-${Date.now()}`;

  const toolCallContent: ToolCallContent = {
    type: "tool_call",
    id: toolId,
    name: toolName,
    serverLabel: (callData.server_label as string) || undefined,
    params,
    inputProgress,
    result: result ?? undefined,
    status,
    interrupted,
  };

  return {
    content: toolCallContent,
    isStreaming: status === "calling",
  };
}

// ---------------------------------------------------------------------------
// Adapter factory
// ---------------------------------------------------------------------------

/**
 * Wrap a ChatV2 BuiltinCardComponent so it can be used as a ChatV1
 * `customToolRenderConfig` renderer.
 *
 * Includes an error boundary so that rendering failures don't break
 * the entire ChatV1 UI.
 */
export function adaptCardForV1(
  CardComponent: BuiltinCardComponent,
): React.FC<any> {
  const V1WrappedCard: React.FC<any> = (v1Props) => {
    const turnEnded = useToolCallTurnEnded();
    const { content, isStreaming } = parseV1Props(v1Props, turnEnded);
    return <CardComponent content={content} isStreaming={isStreaming} />;
  };

  V1WrappedCard.displayName = `V1(${
    CardComponent.displayName || CardComponent.name || "Card"
  })`;
  return V1WrappedCard;
}

/**
 * Convert the entire builtin card registry to ChatV1 format.
 *
 * Returns `Record<string, React.FC<any>>` suitable for passing to
 * `pluginSystem.addToolRenderers()`.
 */
export function adaptRegistryForV1(
  registry: Record<string, BuiltinCardComponent>,
): Record<string, React.FC<any>> {
  const adapted: Record<string, React.FC<any>> = {};
  for (const [toolName, CardComponent] of Object.entries(registry)) {
    adapted[toolName] = adaptCardForV1(CardComponent);
  }
  return adapted;
}

/** Lazy-cached V1-wrapped GenericToolCard for the fallback proxy. */
let _genericFallback: React.FC<any> | null = null;
function getGenericFallback(): React.FC<any> {
  if (!_genericFallback) {
    _genericFallback = adaptCardForV1(GenericToolCard);
  }
  return _genericFallback;
}

/**
 * Wrap a plain tool-render config object with a Proxy so that any tool
 * name not explicitly registered still returns a wrapped GenericToolCard.
 *
 * This must be applied **after** all registrations are merged (i.e. on the
 * final config passed to V1 Chat), because `Object.assign` / spread only
 * copy own-enumerable properties and would lose the Proxy behaviour.
 */
export function withGenericFallback(
  config: Record<string, React.FC<any>>,
): Record<string, React.FC<any>> {
  const fallback = getGenericFallback();
  return new Proxy(config, {
    get(target, prop, receiver) {
      if (typeof prop === "string" && !(prop in target)) {
        return fallback;
      }
      return Reflect.get(target, prop, receiver);
    },
  });
}
