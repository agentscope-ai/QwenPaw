import type { ToolInfo } from "../../../api/modules/tools";
import {
  Blocks,
  Bot,
  CheckCheck,
  Clock,
  Code2,
  FilePenLine,
  FilePlus2,
  FileText,
  FolderSearch,
  Gauge,
  Globe,
  Image,
  Layers,
  ListChecks,
  MailCheck,
  MessagesSquare,
  Monitor,
  PanelsTopLeft,
  RefreshCw,
  ScanSearch,
  Search,
  Send,
  Sparkles,
  Terminal,
  Users,
  Video,
  Workflow,
  type LucideIcon,
} from "lucide-react";

export const TOOL_GROUPS = [
  "files",
  "web",
  "media",
  "agents",
  "runtime",
  "migration",
  "other",
] as const;

export const TOOL_PRESENTATION: Record<
  string,
  { group: (typeof TOOL_GROUPS)[number]; Icon: LucideIcon }
> = {
  execute_shell_command: { group: "runtime", Icon: Terminal },
  read_file: { group: "files", Icon: FileText },
  write_file: { group: "files", Icon: FilePlus2 },
  edit_file: { group: "files", Icon: FilePenLine },
  append_file: { group: "files", Icon: FilePlus2 },
  grep_search: { group: "files", Icon: Search },
  glob_search: { group: "files", Icon: FolderSearch },
  ast_search: { group: "files", Icon: Code2 },
  desktop_screenshot: { group: "media", Icon: Monitor },
  view_image: { group: "media", Icon: Image },
  view_video: { group: "media", Icon: Video },
  enhance_and_generate_image: { group: "media", Icon: Sparkles },
  web_search: { group: "web", Icon: Search },
  web_fetch: { group: "web", Icon: Globe },
  browser: { group: "web", Icon: PanelsTopLeft },
  list_agents: { group: "agents", Icon: Users },
  chat_with_agent: { group: "agents", Icon: MessagesSquare },
  submit_to_agent: { group: "agents", Icon: Send },
  check_agent_task: { group: "agents", Icon: ListChecks },
  spawn_subagent: { group: "agents", Icon: Workflow },
  delegate_external_agent: { group: "agents", Icon: Bot },
  send_file_to_user: { group: "files", Icon: Send },
  get_current_time: { group: "runtime", Icon: Clock },
  set_user_timezone: { group: "runtime", Icon: Globe },
  get_token_usage: { group: "runtime", Icon: Gauge },
  materialize_skill: { group: "runtime", Icon: Blocks },
  run_tool_batch: { group: "runtime", Icon: Layers },
  activate_f1_exploration_mode: { group: "runtime", Icon: MailCheck },
  migration_compat_inspect: { group: "migration", Icon: ScanSearch },
  migration_compat_read_file: { group: "migration", Icon: FileText },
  migration_compat_write_file: { group: "migration", Icon: FilePenLine },
  migration_compat_update: { group: "migration", Icon: RefreshCw },
  migration_compat_finalize: { group: "migration", Icon: CheckCheck },
};

export function toolGroup(tool: ToolInfo): (typeof TOOL_GROUPS)[number] {
  if (tool.source_plugin_id) {
    return TOOL_GROUPS.find((group) => group === tool.category) ?? "other";
  }
  return TOOL_PRESENTATION[tool.name]?.group ?? "other";
}
