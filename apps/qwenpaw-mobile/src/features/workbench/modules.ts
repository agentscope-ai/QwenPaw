import type { LucideIcon } from "lucide-react-native";
import {
  Archive,
  AudioLines,
  AppWindow,
  Blocks,
  Bot,
  Box,
  Clock3,
  Cpu,
  FileClock,
  Folder,
  FolderGit2,
  GitFork,
  Library,
  KeyRound,
  Radio,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  TimerOff,
  Wrench,
} from "lucide-react-native";

export type WorkbenchModuleKey =
  | "files"
  | "projects-git"
  | "agent-config"
  | "skills"
  | "skill-pool"
  | "tools"
  | "mcp-acp"
  | "acp"
  | "checkpoints"
  | "channels"
  | "sessions"
  | "automation"
  | "models"
  | "environments"
  | "security"
  | "offload"
  | "voice"
  | "debug"
  | "operations"
  | "extensions";

export interface WorkbenchModule {
  key: WorkbenchModuleKey;
  title: string;
  subtitle: string;
  icon: LucideIcon;
  iconTone?: "orange" | "ink";
  endpoint?: string;
  keywords?: string[];
  scope: string[];
}

export interface WorkbenchSection {
  title: string;
  modules: WorkbenchModule[];
}

export const workbenchSections: WorkbenchSection[] = [
  {
    title: "工作空间",
    modules: [
      {
        key: "files",
        title: "Files",
        subtitle: "工作区文件与产物",
        icon: Folder,
        iconTone: "ink",
        endpoint: "/workspace/tree?path=&limit=100&root=workspace",
        keywords: ["文件", "产物", "memory", "workspace"],
        scope: ["浏览工作区文件", "查看 Agent 生成的产物", "会话附件管理"],
      },
      {
        key: "projects-git",
        title: "Coding 项目与 Git",
        subtitle: "项目目录、分支与版本提交",
        icon: FolderGit2,
        iconTone: "ink",
        endpoint: "/workspace/project-directory",
        keywords: ["coding", "项目", "git", "分支", "提交"],
        scope: ["Coding Mode", "项目目录", "Git 工作区与提交历史"],
      },
      {
        key: "agent-config",
        title: "Agent 配置",
        subtitle: "当前 Agent 的模型与行为",
        icon: Bot,
        endpoint: "/agents/{agentId}",
        keywords: ["身份", "提示词", "记忆", "模型"],
        scope: ["模型与推理配置", "系统提示与身份", "记忆和工作区设置"],
      },
    ],
  },
  {
    title: "Agent 能力",
    modules: [
      {
        key: "skills",
        title: "Skills",
        subtitle: "安装、启用与配置技能",
        icon: Sparkles,
        endpoint: "/skills",
        keywords: ["技能", "启用", "安装"],
        scope: ["已安装技能", "技能启用状态", "Skill Pool"],
      },
      {
        key: "skill-pool",
        title: "Skill Pool",
        subtitle: "跨 Agent 复用技能",
        icon: Library,
        iconTone: "ink",
        endpoint: "/skills/pool",
        keywords: ["技能池", "同步", "复用"],
        scope: ["Skill Pool", "安装到 Agent", "同步状态"],
      },
      {
        key: "tools",
        title: "Tools",
        subtitle: "内置工具与权限",
        icon: Wrench,
        iconTone: "ink",
        endpoint: "/tools",
        keywords: ["工具", "审批", "异步"],
        scope: ["工具可用状态", "工具参数", "执行权限"],
      },
      {
        key: "mcp-acp",
        title: "MCP",
        subtitle: "外部工具与服务",
        icon: Blocks,
        endpoint: "/mcp",
        keywords: ["服务", "oauth", "访问规则", "协议"],
        scope: ["MCP 服务", "访问主体", "ACP 节点配置"],
      },
      {
        key: "acp",
        title: "ACP",
        subtitle: "外部 Agent 运行协议",
        icon: GitFork,
        endpoint: "/config/acp",
        keywords: ["agent protocol", "node", "外部智能体"],
        scope: ["ACP Agents", "Node Runtime", "信任与工具解析"],
      },
      {
        key: "checkpoints",
        title: "Checkpoints",
        subtitle: "Agent 工作区版本",
        icon: FileClock,
        iconTone: "ink",
        endpoint: "/workspace/checkpoints/status",
        keywords: ["快照", "恢复", "版本"],
        scope: ["快照状态", "版本图", "恢复和清理策略"],
      },
      {
        key: "extensions",
        title: "扩展与 App Center",
        subtitle: "Marketplace、Plugins 与 PawApps",
        icon: AppWindow,
        endpoint: "/plugins",
        keywords: ["市场", "插件", "pawapp", "app", "扩展"],
        scope: ["Skill Marketplace", "插件安装", "PawApp 启动"],
      },
    ],
  },
  {
    title: "自动化与连接",
    modules: [
      {
        key: "channels",
        title: "Channels",
        subtitle: "消息渠道与访问控制",
        icon: Radio,
        endpoint: "/config/channels",
        keywords: ["渠道", "钉钉", "飞书", "微信", "telegram", "slack"],
        scope: ["渠道账号", "群聊和私聊策略", "待审批访问"],
      },
      {
        key: "sessions",
        title: "Sessions",
        subtitle: "全部会话与运行状态",
        icon: Box,
        iconTone: "ink",
        endpoint: "/chats?archived=false",
        keywords: ["会话", "归档", "运行"],
        scope: ["会话列表", "运行状态", "归档与删除"],
      },
      {
        key: "automation",
        title: "Cron 与 Heartbeat",
        subtitle: "定时任务和主动唤醒",
        icon: Clock3,
        endpoint: "/cron/jobs",
        keywords: ["定时任务", "心跳", "唤醒"],
        scope: ["Cron Jobs", "Heartbeat 配置", "运行记录"],
      },
    ],
  },
  {
    title: "系统",
    modules: [
      {
        key: "models",
        title: "Models 与 Providers",
        subtitle: "模型服务与默认模型",
        icon: Cpu,
        endpoint: "/models",
        keywords: ["provider", "llm", "默认模型", "免费模型"],
        scope: ["Provider 状态", "模型列表", "默认模型"],
      },
      {
        key: "environments",
        title: "Environment 与凭据",
        subtitle: "环境变量和密钥",
        icon: KeyRound,
        iconTone: "ink",
        endpoint: "/envs",
        keywords: ["环境变量", "密钥", "凭据"],
        scope: ["环境变量", "密钥遮罩", "凭据更新"],
      },
      {
        key: "security",
        title: "Security",
        subtitle: "沙箱、守卫与扫描",
        icon: ShieldCheck,
        endpoint: "/config/security/sandbox",
        keywords: ["沙箱", "tool guard", "file guard", "扫描"],
        scope: ["Sandbox", "Tool Guard", "File Guard", "Skill Scanner"],
      },
      {
        key: "offload",
        title: "Tool Offload",
        subtitle: "长任务前后台策略",
        icon: TimerOff,
        iconTone: "ink",
        endpoint: "/settings/offload-policy",
        keywords: ["后台", "前台", "长任务"],
        scope: ["默认 Offload 策略"],
      },
      {
        key: "voice",
        title: "语音与转写",
        subtitle: "音频处理和 Whisper",
        icon: AudioLines,
        endpoint: "/workspace/audio-mode",
        keywords: ["voice", "audio", "whisper", "转写"],
        scope: ["音频模式", "转写引擎", "Whisper Provider"],
      },
      {
        key: "debug",
        title: "Debug",
        subtitle: "后端日志与诊断",
        icon: TerminalSquare,
        iconTone: "ink",
        endpoint: "/console/debug/backend-logs?lines=200",
        keywords: ["日志", "诊断", "backend"],
        scope: ["Backend Logs", "运行诊断"],
      },
      {
        key: "operations",
        title: "备份与运行统计",
        subtitle: "Backups、Token Usage 与状态",
        icon: Archive,
        iconTone: "ink",
        endpoint: "/backups",
        keywords: ["备份", "恢复", "token", "统计", "诊断"],
        scope: ["备份和恢复", "Token Usage", "Agent Stats", "运行诊断"],
      },
    ],
  },
];

export const workbenchModules = workbenchSections.flatMap(
  (section) => section.modules,
);

const categoryBlueprints: {
  title: string;
  keys: WorkbenchModuleKey[];
}[] = [
  {
    title: "Agent 与工作空间",
    keys: ["files", "projects-git", "agent-config", "sessions"],
  },
  {
    title: "连接与自动化",
    keys: [
      "models",
      "channels",
      "automation",
      "mcp-acp",
      "acp",
      "tools",
      "voice",
    ],
  },
  {
    title: "运行与安全",
    keys: [
      "skills",
      "skill-pool",
      "security",
      "offload",
      "environments",
      "extensions",
    ],
  },
  {
    title: "数据与诊断",
    keys: ["checkpoints", "debug", "operations"],
  },
];

export const workbenchCategories: WorkbenchSection[] = categoryBlueprints.map(
  (category) => ({
    title: category.title,
    modules: category.keys.map((key) => {
      const module = workbenchModules.find((item) => item.key === key);
      if (!module) throw new Error(`Unknown workbench module: ${key}`);
      return module;
    }),
  }),
);

export function findWorkbenchModule(
  key: string,
): WorkbenchModule | undefined {
  return workbenchModules.find((module) => module.key === key);
}
