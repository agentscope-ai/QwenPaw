/*
 * 工作台模块表 —— 逐条对齐 PR #7378 apps/qwenpaw-mobile/src/features/workbench/modules.ts。
 * 21 个模块 + 4 个任务分类；每模块声明标题 / 说明 / 图标 / 接口端点 / 关键词 / 能力范围。
 * icon 用 HarmonyOS 系统符号（sys.symbol.*），语义对齐 7378 的 lucide 图标。
 */

export interface WorkbenchModule {
  key: string;
  title: string;
  subtitle: string;
  icon: Resource;
  endpoint: string;
  keywords: string[];
  scope: string[];
}

export interface WorkbenchCategory {
  title: string;
  subtitle: string;
  modules: WorkbenchModule[];
}

const MODULES: WorkbenchModule[] = [
  { key: 'files', title: 'Files', subtitle: '工作区文件与产物', icon: $r('sys.symbol.folder'),
    endpoint: '/workspace/tree?path=&limit=100&root=workspace',
    keywords: ['文件', '产物', 'memory', 'workspace'],
    scope: ['浏览工作区文件', '查看 Agent 生成的产物', '会话附件管理'] },
  { key: 'projects-git', title: 'Coding 项目与 Git', subtitle: '项目目录、分支与版本提交', icon: $r('sys.symbol.arrow_2_circlepath'),
    endpoint: '/workspace/project-directory',
    keywords: ['coding', '项目', 'git', '分支', '提交'],
    scope: ['Coding Mode', '项目目录', 'Git 工作区与提交历史'] },
  { key: 'agent-config', title: 'Agent 配置', subtitle: '当前 Agent 的模型与行为', icon: $r('sys.symbol.person'),
    endpoint: '/agents/{agentId}',
    keywords: ['身份', '提示词', '记忆', '模型'],
    scope: ['模型与推理配置', '系统提示与身份', '记忆和工作区设置'] },
  { key: 'skills', title: 'Skills', subtitle: '安装、启用与配置技能', icon: $r('sys.symbol.wand_and_stars'),
    endpoint: '/skills', keywords: ['技能', '启用', '安装'],
    scope: ['已安装技能', '技能启用状态', 'Skill Pool'] },
  { key: 'skill-pool', title: 'Skill Pool', subtitle: '跨 Agent 复用技能', icon: $r('sys.symbol.list_book'),
    endpoint: '/skills/pool', keywords: ['技能池', '同步', '复用'],
    scope: ['Skill Pool', '安装到 Agent', '同步状态'] },
  { key: 'tools', title: 'Tools', subtitle: '内置工具与权限', icon: $r('sys.symbol.wrench_and_screwdriver'),
    endpoint: '/tools', keywords: ['工具', '审批', '异步'],
    scope: ['工具可用状态', '工具参数', '执行权限'] },
  { key: 'mcp-acp', title: 'MCP', subtitle: '外部工具与服务', icon: $r('sys.symbol.puzzle'),
    endpoint: '/mcp', keywords: ['服务', 'oauth', '访问规则', '协议'],
    scope: ['MCP 服务', '访问主体', 'ACP 节点配置'] },
  { key: 'acp', title: 'ACP', subtitle: '外部 Agent 运行协议', icon: $r('sys.symbol.link'),
    endpoint: '/config/acp', keywords: ['agent protocol', 'node', '外部智能体'],
    scope: ['ACP Agents', 'Node Runtime', '信任与工具解析'] },
  { key: 'checkpoints', title: 'Checkpoints', subtitle: 'Agent 工作区版本', icon: $r('sys.symbol.clock'),
    endpoint: '/workspace/checkpoints/status', keywords: ['快照', '恢复', '版本'],
    scope: ['快照状态', '版本图', '恢复和清理策略'] },
  { key: 'extensions', title: '扩展与 App Center', subtitle: 'Marketplace、Plugins 与 PawApps', icon: $r('sys.symbol.square_grid_2x2'),
    endpoint: '/plugins', keywords: ['市场', '插件', 'pawapp', 'app', '扩展'],
    scope: ['Skill Marketplace', '插件安装', 'PawApp 启动'] },
  { key: 'channels', title: 'Channels', subtitle: '消息渠道与访问控制', icon: $r('sys.symbol.radio'),
    endpoint: '/config/channels', keywords: ['渠道', '钉钉', '飞书', '微信', 'telegram', 'slack'],
    scope: ['渠道账号', '群聊和私聊策略', '待审批访问'] },
  { key: 'sessions', title: 'Sessions', subtitle: '全部会话与运行状态', icon: $r('sys.symbol.list_bullet'),
    endpoint: '/chats?archived=false', keywords: ['会话', '归档', '运行'],
    scope: ['会话列表', '运行状态', '归档与删除'] },
  { key: 'automation', title: 'Cron 与 Heartbeat', subtitle: '定时任务和主动唤醒', icon: $r('sys.symbol.clock_arrow_2_circlepath'),
    endpoint: '/cron/jobs', keywords: ['定时任务', '心跳', '唤醒'],
    scope: ['Cron Jobs', 'Heartbeat 配置', '运行记录'] },
  { key: 'hub', title: 'QwenPaw Hub', subtitle: '身份、Runtime 与多用户运行', icon: $r('sys.symbol.network_acceleration'),
    endpoint: '/hub/healthz', keywords: ['hub', '多用户', 'runtime', '控制面', '管理员'],
    scope: ['Hub 身份', '个人 Runtime', '多用户运行管理'] },
  { key: 'models', title: 'Models 与 Providers', subtitle: '模型服务与默认模型', icon: $r('sys.symbol.bolt'),
    endpoint: '/models', keywords: ['provider', 'llm', '默认模型', '免费模型'],
    scope: ['Provider 状态', '模型列表', '默认模型'] },
  { key: 'environments', title: 'Environment 与凭据', subtitle: '环境变量和密钥', icon: $r('sys.symbol.key'),
    endpoint: '/envs', keywords: ['环境变量', '密钥', '凭据'],
    scope: ['环境变量', '密钥遮罩', '凭据更新'] },
  { key: 'security', title: 'Security', subtitle: '沙箱、守卫与扫描', icon: $r('sys.symbol.checkmark_shield'),
    endpoint: '/config/security/sandbox', keywords: ['沙箱', 'tool guard', 'file guard', '扫描'],
    scope: ['Sandbox', 'Tool Guard', 'File Guard', 'Skill Scanner'] },
  { key: 'offload', title: 'Tool Offload', subtitle: '长任务前后台策略', icon: $r('sys.symbol.clock_badge_gearshape_fill'),
    endpoint: '/settings/offload-policy', keywords: ['后台', '前台', '长任务'],
    scope: ['默认 Offload 策略'] },
  { key: 'voice', title: '语音与转写', subtitle: '音频处理和 Whisper', icon: $r('sys.symbol.mic'),
    endpoint: '/workspace/audio-mode', keywords: ['voice', 'audio', 'whisper', '转写'],
    scope: ['音频模式', '转写引擎', 'Whisper Provider'] },
  { key: 'debug', title: 'Debug', subtitle: '后端日志与诊断', icon: $r('sys.symbol.doc_plaintext'),
    endpoint: '/console/debug/backend-logs?lines=200', keywords: ['日志', '诊断', 'backend'],
    scope: ['Backend Logs', '运行诊断'] },
  { key: 'operations', title: '备份与运行统计', subtitle: 'Backups、Token Usage 与状态', icon: $r('sys.symbol.archivebox'),
    endpoint: '/backups', keywords: ['备份', '恢复', 'token', '统计', '诊断'],
    scope: ['备份和恢复', 'Token Usage', 'Agent Stats', '运行诊断'] },
];

export function findWorkbenchModule(key: string): WorkbenchModule | null {
  for (const m of MODULES) {
    if (m.key === key) {
      return m;
    }
  }
  return null;
}

function pick(keys: string[]): WorkbenchModule[] {
  const out: WorkbenchModule[] = [];
  for (const k of keys) {
    const m: WorkbenchModule | null = findWorkbenchModule(k);
    if (m !== null) {
      out.push(m);
    }
  }
  return out;
}

// 4 任务分类（对齐 7378 categoryBlueprints）
export const WORKBENCH_CATEGORIES: WorkbenchCategory[] = [
  { title: 'Agent 与工作空间', subtitle: 'Agent、会话、文件与项目',
    modules: pick(['files', 'projects-git', 'agent-config', 'sessions']) },
  { title: '连接与自动化', subtitle: '模型、渠道、工具与计划任务',
    modules: pick(['models', 'channels', 'automation', 'mcp-acp', 'acp', 'tools', 'voice']) },
  { title: '运行与安全', subtitle: '技能、权限、运行与扩展',
    modules: pick(['hub', 'skills', 'skill-pool', 'security', 'offload', 'environments', 'extensions']) },
  { title: '数据与诊断', subtitle: '版本、日志、用量与恢复',
    modules: pick(['operations', 'checkpoints', 'debug']) },
];

export const WORKBENCH_MODULES: WorkbenchModule[] = MODULES;
