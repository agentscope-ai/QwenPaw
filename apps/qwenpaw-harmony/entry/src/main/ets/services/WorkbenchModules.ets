/*
 * 工作台模块表 —— 逐条对齐 PR #7378 apps/qwenpaw-mobile/src/features/workbench/modules.ts。
 * 21 个模块 + 4 个任务分类；每模块声明标题 / 说明 / 图标 / 接口端点 / 关键词 / 能力范围。
 * icon 用 QwenPaw 同款 lucide（工程 media 资源，Image 渲染），与 7378 图标逐一对应。
 */

export interface WorkbenchModule {
  key: string;
  // title / subtitle 为显示文案，走资源（keywords / scope 是搜索索引，保留原串不翻译）
  title: ResourceStr;
  subtitle: ResourceStr;
  icon: Resource;
  endpoint: string;
  keywords: string[];
  scope: string[];
}

export interface WorkbenchCategory {
  key: string;
  title: ResourceStr;
  subtitle: ResourceStr;
  modules: WorkbenchModule[];
}

const MODULES: WorkbenchModule[] = [
  { key: 'files', title: $r('app.string.wb_mod_files_title'), subtitle: $r('app.string.wb_mod_files_subtitle'), icon: $r('app.media.folder'),
    endpoint: '/workspace/tree?path=&limit=100&root=workspace',
    keywords: ['文件', '产物', 'memory', 'workspace'],
    scope: ['浏览工作区文件', '查看 Agent 生成的产物', '会话附件管理'] },
  { key: 'projects-git', title: $r('app.string.wb_mod_projects_git_title'), subtitle: $r('app.string.wb_mod_projects_git_subtitle'), icon: $r('app.media.refresh_cw'),
    endpoint: '/workspace/project-directory',
    keywords: ['coding', '项目', 'git', '分支', '提交'],
    scope: ['Coding Mode', '项目目录', 'Git 工作区与提交历史'] },
  { key: 'agent-config', title: $r('app.string.wb_mod_agent_config_title'), subtitle: $r('app.string.wb_mod_agent_config_subtitle'), icon: $r('app.media.user'),
    endpoint: '/agents/{agentId}',
    keywords: ['身份', '提示词', '记忆', '模型'],
    scope: ['模型与推理配置', '系统提示与身份', '记忆和工作区设置'] },
  { key: 'skills', title: $r('app.string.wb_mod_skills_title'), subtitle: $r('app.string.wb_mod_skills_subtitle'), icon: $r('app.media.wand_sparkles'),
    endpoint: '/skills', keywords: ['技能', '启用', '安装'],
    scope: ['已安装技能', '技能启用状态', 'Skill Pool'] },
  { key: 'skill-pool', title: $r('app.string.wb_mod_skill_pool_title'), subtitle: $r('app.string.wb_mod_skill_pool_subtitle'), icon: $r('app.media.book_open'),
    endpoint: '/skills/pool', keywords: ['技能池', '同步', '复用'],
    scope: ['Skill Pool', '安装到 Agent', '同步状态'] },
  { key: 'tools', title: $r('app.string.wb_mod_tools_title'), subtitle: $r('app.string.wb_mod_tools_subtitle'), icon: $r('app.media.wrench'),
    endpoint: '/tools', keywords: ['工具', '审批', '异步'],
    scope: ['工具可用状态', '工具参数', '执行权限'] },
  { key: 'mcp-acp', title: $r('app.string.wb_mod_mcp_acp_title'), subtitle: $r('app.string.wb_mod_mcp_acp_subtitle'), icon: $r('app.media.puzzle'),
    endpoint: '/mcp', keywords: ['服务', 'oauth', '访问规则', '协议'],
    scope: ['MCP 服务', '访问主体', 'ACP 节点配置'] },
  { key: 'acp', title: $r('app.string.wb_mod_acp_title'), subtitle: $r('app.string.wb_mod_acp_subtitle'), icon: $r('app.media.link'),
    endpoint: '/config/acp', keywords: ['agent protocol', 'node', '外部智能体'],
    scope: ['ACP Agents', 'Node Runtime', '信任与工具解析'] },
  { key: 'checkpoints', title: $r('app.string.wb_mod_checkpoints_title'), subtitle: $r('app.string.wb_mod_checkpoints_subtitle'), icon: $r('app.media.clock'),
    endpoint: '/workspace/checkpoints/status', keywords: ['快照', '恢复', '版本'],
    scope: ['快照状态', '版本图', '恢复和清理策略'] },
  { key: 'extensions', title: $r('app.string.wb_mod_extensions_title'), subtitle: $r('app.string.wb_mod_extensions_subtitle'), icon: $r('app.media.layout_grid'),
    endpoint: '/plugins', keywords: ['市场', '插件', 'pawapp', 'app', '扩展'],
    scope: ['Skill Marketplace', '插件安装', 'PawApp 启动'] },
  { key: 'channels', title: $r('app.string.wb_mod_channels_title'), subtitle: $r('app.string.wb_mod_channels_subtitle'), icon: $r('app.media.radio'),
    endpoint: '/config/channels', keywords: ['渠道', '钉钉', '飞书', '微信', 'telegram', 'slack'],
    scope: ['渠道账号', '群聊和私聊策略', '待审批访问'] },
  { key: 'sessions', title: $r('app.string.wb_mod_sessions_title'), subtitle: $r('app.string.wb_mod_sessions_subtitle'), icon: $r('app.media.list'),
    endpoint: '/chats?archived=false', keywords: ['会话', '归档', '运行'],
    scope: ['会话列表', '运行状态', '归档与删除'] },
  { key: 'automation', title: $r('app.string.wb_mod_automation_title'), subtitle: $r('app.string.wb_mod_automation_subtitle'), icon: $r('app.media.timer_reset'),
    endpoint: '/cron/jobs', keywords: ['定时任务', '心跳', '唤醒'],
    scope: ['Cron Jobs', 'Heartbeat 配置', '运行记录'] },
  { key: 'hub', title: $r('app.string.wb_mod_hub_title'), subtitle: $r('app.string.wb_mod_hub_subtitle'), icon: $r('app.media.network'),
    endpoint: '/hub/healthz', keywords: ['hub', '多用户', 'runtime', '控制面', '管理员'],
    scope: ['Hub 身份', '个人 Runtime', '多用户运行管理'] },
  { key: 'models', title: $r('app.string.wb_mod_models_title'), subtitle: $r('app.string.wb_mod_models_subtitle'), icon: $r('app.media.zap'),
    endpoint: '/models', keywords: ['provider', 'llm', '默认模型', '免费模型'],
    scope: ['Provider 状态', '模型列表', '默认模型'] },
  { key: 'environments', title: $r('app.string.wb_mod_environments_title'), subtitle: $r('app.string.wb_mod_environments_subtitle'), icon: $r('app.media.key'),
    endpoint: '/envs', keywords: ['环境变量', '密钥', '凭据'],
    scope: ['环境变量', '密钥遮罩', '凭据更新'] },
  { key: 'security', title: $r('app.string.wb_mod_security_title'), subtitle: $r('app.string.wb_mod_security_subtitle'), icon: $r('app.media.shield_check'),
    endpoint: '/config/security/sandbox', keywords: ['沙箱', 'tool guard', 'file guard', '扫描'],
    scope: ['Sandbox', 'Tool Guard', 'File Guard', 'Skill Scanner'] },
  { key: 'offload', title: $r('app.string.wb_mod_offload_title'), subtitle: $r('app.string.wb_mod_offload_subtitle'), icon: $r('app.media.timer_off'),
    endpoint: '/settings/offload-policy', keywords: ['后台', '前台', '长任务'],
    scope: ['默认 Offload 策略'] },
  { key: 'voice', title: $r('app.string.wb_mod_voice_title'), subtitle: $r('app.string.wb_mod_voice_subtitle'), icon: $r('app.media.mic'),
    endpoint: '/workspace/audio-mode', keywords: ['voice', 'audio', 'whisper', '转写'],
    scope: ['音频模式', '转写引擎', 'Whisper Provider'] },
  { key: 'debug', title: $r('app.string.wb_mod_debug_title'), subtitle: $r('app.string.wb_mod_debug_subtitle'), icon: $r('app.media.file_text'),
    endpoint: '/console/debug/backend-logs?lines=200', keywords: ['日志', '诊断', 'backend'],
    scope: ['Backend Logs', '运行诊断'] },
  { key: 'operations', title: $r('app.string.wb_mod_operations_title'), subtitle: $r('app.string.wb_mod_operations_subtitle'), icon: $r('app.media.archive'),
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
  { key: 'agent_workspace', title: $r('app.string.wb_cat_agent_workspace_title'), subtitle: $r('app.string.wb_cat_agent_workspace_subtitle'),
    modules: pick(['files', 'projects-git', 'agent-config', 'sessions']) },
  { key: 'conn_automation', title: $r('app.string.wb_cat_conn_automation_title'), subtitle: $r('app.string.wb_cat_conn_automation_subtitle'),
    modules: pick(['models', 'channels', 'automation', 'mcp-acp', 'acp', 'tools', 'voice']) },
  { key: 'run_security', title: $r('app.string.wb_cat_run_security_title'), subtitle: $r('app.string.wb_cat_run_security_subtitle'),
    modules: pick(['hub', 'skills', 'skill-pool', 'security', 'offload', 'environments']) },
  { key: 'data_diagnostics', title: $r('app.string.wb_cat_data_diagnostics_title'), subtitle: $r('app.string.wb_cat_data_diagnostics_subtitle'),
    modules: pick(['operations', 'checkpoints', 'debug']) },
];

export const WORKBENCH_MODULES: WorkbenchModule[] = MODULES;
