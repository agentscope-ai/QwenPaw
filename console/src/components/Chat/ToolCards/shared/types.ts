/**
 * Tool card types — self-contained within the plugin system.
 * These mirror the ChatV2 types but live here so the plugin package
 * has zero imports from outside ToolCards/.
 */

export type ToolCallStatus = "calling" | "done" | "error";

export interface ToolCallContent {
  type: "tool_call";
  id: string;
  name: string;
  serverLabel?: string;
  params: Record<string, unknown>;
  result?: unknown;
  status: ToolCallStatus;
}

export interface ToolCardProps<T = Record<string, unknown>> {
  data: T;
  status: ToolCallStatus;
  toolName: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ToolCardComponent = React.FC<ToolCardProps<any>>;

export type ToolCardRegistry = Record<string, ToolCardComponent>;
