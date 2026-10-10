/*
 * 智能体列表服务 —— GET {base}/api/agents（对齐 PR #7378 routers/agents.py AgentSummary）。
 * 字段防御式解析：服务端版本差异时缺字段不崩溃。
 */

import { http } from '@kit.NetworkKit';
import { emitter } from '@kit.BasicServicesKit';
import { Context } from '@kit.AbilityKit';
import { doRequest, jsonOf, ConnectError } from './ConnectionService';
import { QpConnection, saveConnection } from './ConnectionStore';

// 智能体切换事件：selectAgent 持久化后广播，
// ConnectPanel（会话列表）/ WorkbenchTab（审批）/ AgentsTab 各自重载跟随
export const AGENT_CHANGE_EVENT: string = 'qp_agent_change';

// 打开「创建 Agent」表单的请求事件（标题栏 ＋ 按钮 → 智能体页表单，解耦）
export const AGENT_CREATE_EVENT: string = 'qp_agent_create';

// 切换当前智能体 —— 对齐 PR #7378 store/app.ts selectAgent：
// 持久化 {...connection, agentId}，随后各数据源按新 agent 重载（经 X-Agent-Id 头）。
export async function selectAgent(ctx: Context, conn: QpConnection, agentId: string): Promise<QpConnection> {
  const next: QpConnection = {
    baseUrl: conn.baseUrl,
    token: conn.token,
    username: conn.username,
    agentId: agentId,
    source: conn.source,
    serverMode: conn.serverMode
  };
  await saveConnection(ctx, next);
  emitter.emit(AGENT_CHANGE_EVENT);
  return next;
}

export interface AgentInfo {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  pinned: boolean;
  startupStatus: string;   // running / pending / disabled / ...
  activeModel: string;
  backend: string;
}

function strOf(rec: Record<string, Object>, key: string): string {
  const v: Object = rec[key];
  return typeof v === 'string' ? v as string : '';
}

function boolOf(rec: Record<string, Object>, key: string, fallback: boolean): boolean {
  const v: Object = rec[key];
  return typeof v === 'boolean' ? v as boolean : fallback;
}

export async function fetchAgents(baseUrl: string, token: string, agentId: string): Promise<AgentInfo[]> {
  const resp: http.HttpResponse = await doRequest(
    `${baseUrl}/api/agents`, http.RequestMethod.GET, null,
    token.length > 0 ? token : null, agentId);
  if (resp.responseCode === 401 || resp.responseCode === 403) {
    throw new ConnectError(`票据已失效（HTTP ${resp.responseCode}），请回到「会话」页重新连接。`);
  }
  if (resp.responseCode !== 200) {
    throw new ConnectError(`读取智能体列表失败（HTTP ${resp.responseCode}）。`);
  }
  const data: Record<string, Object> = jsonOf(resp);
  const arr: Object = data['agents'];
  if (!Array.isArray(arr)) {
    return [];
  }
  const items: Object[] = arr as Object[];
  const out: AgentInfo[] = [];
  for (const item of items) {
    const a: Record<string, Object> = item as Record<string, Object>;
    const id: string = strOf(a, 'id');
    const name: string = strOf(a, 'name').length > 0 ? strOf(a, 'name') : id;
    const info: AgentInfo = {
      id: id,
      name: name,
      description: strOf(a, 'description'),
      enabled: boolOf(a, 'enabled', true),
      pinned: boolOf(a, 'pinned', false),
      startupStatus: strOf(a, 'startup_status'),
      activeModel: strOf(a, 'active_model'),
      backend: strOf(a, 'backend')
    };
    out.push(info);
  }
  return out;
}

// —— 智能体管理（对齐 PR #7378 agents.tsx mutateAgent / 创建 / 复制）——
//   pin|toggle → PATCH {base}/api/agents/{id}/{pin|toggle}（body 为目标值）
//   delete     → DELETE {base}/api/agents/{id}
//   create     → POST   {base}/api/agents
//   copy       → POST   {base}/api/agents/{id}/copy
export type AgentAction = 'pin' | 'toggle' | 'delete';

interface PinBody {
  pinned: boolean;
}

interface ToggleBody {
  enabled: boolean;
}

function assertOk(resp: http.HttpResponse, what: string): void {
  if (resp.responseCode === 401 || resp.responseCode === 403) {
    throw new ConnectError(`票据已失效（HTTP ${resp.responseCode}），请重新连接。`);
  }
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new ConnectError(`${what}失败（HTTP ${resp.responseCode}）。`);
  }
}

function authOf(token: string): string | null {
  return token.length > 0 ? token : null;
}

export async function mutateAgent(baseUrl: string, token: string, agentId: string,
  action: AgentAction, target: AgentInfo): Promise<void> {
  const path: string = `${baseUrl}/api/agents/${encodeURIComponent(target.id)}`;
  if (action === 'delete') {
    assertOk(await doRequest(path, http.RequestMethod.DELETE, null, authOf(token), agentId),
      '删除智能体');
    return;
  }
  if (action === 'pin') {
    const pin: PinBody = { pinned: !target.pinned };
    const body: string = JSON.stringify(pin);
    assertOk(await doRequest(`${path}/pin`, http.RequestMethod.PATCH, body, authOf(token), agentId),
      '置顶智能体');
    return;
  }
  const toggle: ToggleBody = { enabled: !target.enabled };
  const body: string = JSON.stringify(toggle);
  assertOk(await doRequest(`${path}/toggle`, http.RequestMethod.PATCH, body, authOf(token), agentId),
    '启停智能体');
}

// 创建智能体（空字段不下发，对齐 PR create 分支）
export async function createAgent(baseUrl: string, token: string, agentId: string,
  name: string, newId: string, description: string, workspaceDir: string): Promise<void> {
  const payload: Record<string, Object> = {
    'name': name,
    'language': 'zh-CN',
    'backend': 'qwenpaw'
  };
  if (newId.length > 0) {
    payload['id'] = newId;
  }
  if (description.length > 0) {
    payload['description'] = description;
  }
  if (workspaceDir.length > 0) {
    payload['workspace_dir'] = workspaceDir;
  }
  assertOk(await doRequest(`${baseUrl}/api/agents`, http.RequestMethod.POST,
    JSON.stringify(payload), authOf(token), agentId), '创建智能体');
}

// 复制智能体（对齐 PR copy 分支：agent.json 恒复制，其余按开关）
export async function copyAgent(baseUrl: string, token: string, agentId: string,
  sourceId: string, name: string, copyMd: boolean, copySkills: boolean,
  copyJobs: boolean): Promise<void> {
  const payload: Record<string, Object> = {
    'name': name,
    'copy_agent_json': true,
    'copy_md_files': copyMd,
    'copy_skills': copySkills,
    'copy_jobs': copyJobs
  };
  assertOk(await doRequest(`${baseUrl}/api/agents/${encodeURIComponent(sourceId)}/copy`,
    http.RequestMethod.POST, JSON.stringify(payload), authOf(token), agentId), '复制智能体');
}
