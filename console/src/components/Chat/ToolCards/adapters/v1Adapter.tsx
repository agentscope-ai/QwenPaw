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
import type { BuiltinCardComponent } from "../cards";
import GenericToolCard from "../cards/GenericToolCard";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ERROR_STATUSES = new Set(["failed", "rejected", "canceled"]);

/**
 * Derive the tool execution status from V1 message data.
 *
 * No result item (content[1]) → tool hasn't produced output yet → "calling".
 * Message-level status on tool_call messages reflects *delivery*, not execution,
 * so we only consult it when a result item exists.
 */
function deriveToolStatus(
  resultItem: Record<string, unknown> | undefined,
  data: Record<string, unknown>,
): ToolCallStatus {
  if (!resultItem) return "calling";

  const rawStatus =
    (data.status as string) || (resultItem.status as string) || "";
  if (rawStatus === "completed") return "done";
  if (ERROR_STATUSES.has(rawStatus)) return "error";
  return "calling";
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
function parseV1Props(v1Props: Record<string, unknown>): {
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
  if (typeof rawArgs === "string") {
    try {
      params = JSON.parse(rawArgs);
    } catch {
      params = {};
    }
  } else if (rawArgs && typeof rawArgs === "object") {
    params = rawArgs as Record<string, unknown>;
  }

  // Extract result from content[1].data.output
  const result = resultData.output;

  // No output content → tool hasn't executed yet → always "calling".
  // Message-level status on *_call messages reflects delivery, not execution.
  const status = deriveToolStatus(resultItem, data);

  // Extract id
  const toolId =
    (callData.id as string) ||
    (data.id as string) ||
    `v1-${toolName}-${Date.now()}`;

  const toolCallContent: ToolCallContent = {
    type: "tool_call",
    id: toolId,
    name: toolName,
    serverLabel: (callData.server_label as string) || undefined,
    params,
    result: result ?? undefined,
    status,
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
    const { content, isStreaming } = parseV1Props(v1Props);
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
