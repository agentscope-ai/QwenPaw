/**
 * Builtin tool card registry.
 *
 * Each tool name maps to a React component that receives
 * { content: ToolCallContent, isStreaming?: boolean }.
 *
 * The mapping is consumed by:
 *  - ToolCallBlock (ChatV2) via CardRegistry
 *  - ChatV1 via v1Adapter + PluginSystem
 */

import type React from "react";
import type { ToolCallContent } from "../shared/types";

// ── Card imports ──────────────────────────────────────────────────────
export { default as ReadFileCard } from "./ReadFileCard";
export { default as WriteFileCard } from "./WriteFileCard";
export { default as EditFileCard } from "./EditFileCard";
export { default as AppendFileCard } from "./AppendFileCard";
export { default as GrepSearchCard } from "./GrepSearchCard";
export { default as GlobSearchCard } from "./GlobSearchCard";
export { default as ViewImageCard } from "./ViewImageCard";
export { default as ViewVideoCard } from "./ViewVideoCard";
export { default as DesktopScreenshotCard } from "./DesktopScreenshotCard";
export { default as SendFileCard } from "./SendFileCard";
export { default as BrowserCard } from "./BrowserCard";
// ── DEPRECATED BROWSER (remove together with backend deprecated_browser/) ──
export { default as BrowserUseCard } from "./deprecated/BrowserUseCard";
// ── END DEPRECATED BROWSER ──
export { default as GetCurrentTimeCard } from "./GetCurrentTimeCard";
export { default as SetTimezoneCard } from "./SetTimezoneCard";
export { default as TokenUsageCard } from "./TokenUsageCard";
export { default as MemorySearchCard } from "./MemorySearchCard";
export { default as ListAgentsCard } from "./ListAgentsCard";
export { default as ChatWithAgentCard } from "./ChatWithAgentCard";
export { default as SubmitToAgentCard } from "./SubmitToAgentCard";
export { default as CheckAgentTaskCard } from "./CheckAgentTaskCard";
export { default as DelegateExternalAgentCard } from "./DelegateExternalAgentCard";
export { default as ShellCard } from "./ShellCard";
export { default as CodeModeCard } from "./CodeModeCard";
export { default as RunToolBatchCard } from "./RunToolBatchCard";
export { default as GenericToolCard } from "./GenericToolCard";

// ── Common props type ─────────────────────────────────────────────────

export interface BuiltinCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

export type BuiltinCardComponent = React.FC<BuiltinCardProps>;

export { BUILTIN_CARD_REGISTRY } from "../lazyRegistry";
