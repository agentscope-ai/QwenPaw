/*
 * 远端 PawApp 注册表（QwenPaw 提供的前端扩展应用已知清单）—— 供工作台「扩展与 App Center」页使用：
 * 本地形态（未连接远端）列出浏览（详情页看描述/边界/源码）；连接形态的「App Center」组展示
 * 服务端 /api/pawapps 的真实应用，本注册表不再重复列。
 *
 * 条目手工维护：新增一个前端扩展应用时在这里加一条即可
 * （文案走 string.json 资源，与工程其余部分同一 i18n 口径）。
 *
 * 「前端扩展」的边界：插件 UI 是纯前端页面，但其运行时宿主（QwenPaw 控制台的路由/主题/鉴权
 * 环境）与数据面（插件自带的后端）都在远端 QwenPaw 上；设备侧没有 QwenPaw 后端，无法独立
 * 运行插件前端。因此本注册表条目不提供安装动作——安装与启用须连接 QwenPaw 后经「App
 * Center」打开，或由工作台「扩展与 App Center」页的「本地插件」组安装（设备 ZIP 上传
 * POST /api/plugins/upload / 按 URL 安装 POST /api/plugins/install）。
 */

export interface RemotePawAppEntry {
  id: string;
  version: string;
  nameResource: Resource;
  descriptionResource: Resource;
  notesResource: Resource;
  repoUrl: string;
}

function makeAgentTeamsWorkbench(): RemotePawAppEntry {
  const entry: RemotePawAppEntry = {
    id: 'agentteams-qwenpaw-workbench',
    version: '0.5.0-beta.15.6',
    nameResource: $r('app.string.local_plugin_agentteams_name'),
    descriptionResource: $r('app.string.local_plugin_agentteams_desc'),
    notesResource: $r('app.string.local_plugin_agentteams_notes'),
    repoUrl: 'https://github.com/LUOSENGWA/agentteams-qwenpaw-workbench'
  };
  return entry;
}

// 首条为 AgentTeams 团队工作台应用（纯前端扩展，边界见本文件头注释）
export const REMOTE_PAWAPPS: RemotePawAppEntry[] = [makeAgentTeamsWorkbench()];
