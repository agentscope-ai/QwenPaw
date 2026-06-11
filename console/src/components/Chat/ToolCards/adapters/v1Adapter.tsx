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
  const result = resultData.output ?? null;

  // Map @agentscope-ai/chat status to ChatV2 ToolCallStatus
  // V1 statuses: "created" | "in_progress" | "completed" | "canceled" | "failed" | "rejected" | "unknown"
  let status: ToolCallStatus = "calling";
  const rawStatus = (data.status as string) || "";
  if (rawStatus === "completed") {
    status = "done";
  } else if (
    rawStatus === "failed" ||
    rawStatus === "rejected" ||
    rawStatus === "canceled"
  ) {
    status = "error";
  }
  // "in_progress" and "created" map to "calling"

  const isStreaming = rawStatus === "in_progress" || rawStatus === "created";

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

  return { content: toolCallContent, isStreaming };
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
