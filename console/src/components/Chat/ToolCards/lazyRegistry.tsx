import { lazy, Suspense } from "react";
import { Spin } from "antd";
import { ChunkErrorBoundary } from "../../ChunkErrorBoundary";
import type { BuiltinCardComponent, BuiltinCardProps } from "./cards";

function lazyCard(
  load: () => Promise<{ default: BuiltinCardComponent }>,
): BuiltinCardComponent {
  const Card = lazy(load);
  return function LazyToolCard(props: BuiltinCardProps) {
    return (
      <ChunkErrorBoundary>
        <Suspense fallback={<Spin size="small" />}>
          <Card {...props} />
        </Suspense>
      </ChunkErrorBoundary>
    );
  };
}

const ReadFileCard = lazyCard(() => import("./cards/ReadFileCard"));
const WriteFileCard = lazyCard(() => import("./cards/WriteFileCard"));
const EditFileCard = lazyCard(() => import("./cards/EditFileCard"));
const AppendFileCard = lazyCard(() => import("./cards/AppendFileCard"));
const GrepSearchCard = lazyCard(() => import("./cards/GrepSearchCard"));
const GlobSearchCard = lazyCard(() => import("./cards/GlobSearchCard"));
const ViewImageCard = lazyCard(() => import("./cards/ViewImageCard"));
const ViewVideoCard = lazyCard(() => import("./cards/ViewVideoCard"));
const DesktopScreenshotCard = lazyCard(
  () => import("./cards/DesktopScreenshotCard"),
);
const SendFileCard = lazyCard(() => import("./cards/SendFileCard"));
const BrowserCard = lazyCard(() => import("./cards/BrowserCard"));
const BrowserUseCard = lazyCard(
  () => import("./cards/deprecated/BrowserUseCard"),
);
const GetCurrentTimeCard = lazyCard(() => import("./cards/GetCurrentTimeCard"));
const SetTimezoneCard = lazyCard(() => import("./cards/SetTimezoneCard"));
const TokenUsageCard = lazyCard(() => import("./cards/TokenUsageCard"));
const MemorySearchCard = lazyCard(() => import("./cards/MemorySearchCard"));
const ListAgentsCard = lazyCard(() => import("./cards/ListAgentsCard"));
const ChatWithAgentCard = lazyCard(() => import("./cards/ChatWithAgentCard"));
const SubmitToAgentCard = lazyCard(() => import("./cards/SubmitToAgentCard"));
const CheckAgentTaskCard = lazyCard(() => import("./cards/CheckAgentTaskCard"));
const DelegateExternalAgentCard = lazyCard(
  () => import("./cards/DelegateExternalAgentCard"),
);
const ShellCard = lazyCard(() => import("./cards/ShellCard"));
const CodeModeCard = lazyCard(() => import("./cards/CodeModeCard"));
const RunToolBatchCard = lazyCard(() => import("./cards/RunToolBatchCard"));

export const GenericToolCard = lazyCard(
  () => import("./cards/GenericToolCard"),
);

export const BUILTIN_CARD_REGISTRY: Record<string, BuiltinCardComponent> = {
  // File I/O
  read_file: ReadFileCard,
  write_file: WriteFileCard,
  edit_file: EditFileCard,
  append_file: AppendFileCard,

  // Search
  grep_search: GrepSearchCard,
  glob_search: GlobSearchCard,

  // Media
  view_image: ViewImageCard,
  view_video: ViewVideoCard,
  desktop_screenshot: DesktopScreenshotCard,
  send_file_to_user: SendFileCard,

  // Unified Browser SDK
  browser: BrowserCard,

  // ── DEPRECATED BROWSER (remove together with backend deprecated_browser/) ──
  browser_use: BrowserUseCard,
  // ── END DEPRECATED BROWSER ──

  // Time
  get_current_time: GetCurrentTimeCard,
  set_user_timezone: SetTimezoneCard,

  // Token usage
  get_token_usage: TokenUsageCard,

  // Memory
  memory_search: MemorySearchCard,

  // Agent management
  list_agents: ListAgentsCard,
  chat_with_agent: ChatWithAgentCard,
  submit_to_agent: SubmitToAgentCard,
  check_agent_task: CheckAgentTaskCard,
  delegate_external_agent: DelegateExternalAgentCard,

  // Shell
  execute_shell_command: ShellCard,
  shell: ShellCard,
  bash: ShellCard,
  terminal: ShellCard,
  run_command: ShellCard,

  // Workflow
  run_tool_batch: RunToolBatchCard,
  run_code: CodeModeCard,
};
