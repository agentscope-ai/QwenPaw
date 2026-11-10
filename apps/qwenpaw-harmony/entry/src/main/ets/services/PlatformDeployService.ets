/*
 * 平台部署（云端 QwenPaw）—— 移植 PR #7378 features/platform/deployment.ts
 * + features/platform/deploymentModel.ts（解析、状态呈现、错误文案映射）。
 *   数据源：{Platform}/api/v1/app/{list,get,create,start,restart,pre,stable,reset-qwenpaw-auth,deploy-logs}
 *
 * 状态/错误文案沿用 7378 deploymentModel.ts 的中文口径（源文件同样未走 i18n）。
 */

import { http } from '@kit.NetworkKit';
import { Context } from '@kit.AbilityKit';
import { platformRequest, PlatformRequestError } from './PlatformSession';
import { objOf, strOf, numOf } from './JsonUtil';
import { t } from './I18n';

export const DEFAULT_APP_TYPE: string = 'qwenpaw';
export const DEFAULT_VERSION_TYPE: string = 'stable';

export interface PlatformDeployment {
  appId: string;
  status: string;
  accessUrl: string;
  errorMessage: string;
  message: string;
  progress: number;
  versionType: string;
}

export interface DeploymentStatusPresentation {
  label: string;
  detail: string;
  active: boolean;
  failed: boolean;
}

export interface DeploymentCompatibility {
  compatible: boolean;
  label: string;
}

// 保留 7378 的取数链：list → 取第一个 appId
export async function listPlatformDeployments(ctx: Context): Promise<string[]> {
  const data: Object = await platformRequest(ctx, '/api/v1/app/list', http.RequestMethod.GET, null);
  const out: string[] = [];
  let entries: Object | null = Array.isArray(data) ? data : null;
  if (entries === null) {
    const o: Record<string, Object> | null = objOf(data);
    if (o !== null) {
      const apps: Object = o['apps'] !== undefined ? o['apps'] : o['list'];
      if (Array.isArray(apps)) {
        entries = apps as Object[];
      }
    }
  }
  if (entries === null) {
    return out;
  }
  for (const entry of entries as Object[]) {
    const o: Record<string, Object> | null = objOf(entry);
    if (o === null) {
      continue;
    }
    let id: string = strOf(o, 'appId', '');
    if (id.length === 0) {
      id = strOf(o, 'id', '');
    }
    if (id.length > 0 && out.indexOf(id) < 0) {
      out.push(id);
    }
  }
  return out;
}

export async function createPlatformDeployment(ctx: Context): Promise<string> {
  const body: Record<string, Object> = {};
  body['appType'] = DEFAULT_APP_TYPE;
  body['versionType'] = DEFAULT_VERSION_TYPE;
  const data: Object = await platformRequest(ctx, '/api/v1/app/create',
    http.RequestMethod.POST, JSON.stringify(body));
  const o: Record<string, Object> | null = objOf(data);
  if (o === null) {
    throw new Error(t($r('app.string.deploy_err_no_appid')));
  }
  let id: string = strOf(o, 'appId', '');
  if (id.length === 0) {
    id = strOf(o, 'id', '');
  }
  if (id.length === 0) {
    throw new Error(t($r('app.string.deploy_err_no_appid')));
  }
  return id;
}

export async function getPlatformDeployment(ctx: Context, appId: string): Promise<PlatformDeployment> {
  const data: Object = await platformRequest(ctx,
    `/api/v1/app/get?appId=${encodeURIComponent(appId)}`, http.RequestMethod.GET, null);
  const o: Record<string, Object> = objOf(data) !== null
    ? objOf(data) as Record<string, Object> : {};
  let id: string = strOf(o, 'appId', '');
  if (id.length === 0) {
    id = strOf(o, 'id', appId);
  }
  let status: string = strOf(o, 'status', 'pending').toLowerCase();
  if (status.length === 0) {
    status = 'pending';
  }
  let accessUrl: string = strOf(o, 'accessUrl', '');
  if (accessUrl.length === 0) {
    accessUrl = strOf(o, 'access_url', '');
  }
  while (accessUrl.endsWith('/')) {
    accessUrl = accessUrl.substring(0, accessUrl.length - 1);
  }
  let errorMessage: string = strOf(o, 'errorMessage', '');
  if (errorMessage.length === 0) {
    errorMessage = strOf(o, 'error_message', '');
  }
  let versionType: string = strOf(o, 'versionType', '');
  if (versionType.length === 0) {
    versionType = strOf(o, 'version_type', '');
  }
  const deployment: PlatformDeployment = {
    appId: id,
    status: status,
    accessUrl: accessUrl,
    errorMessage: errorMessage,
    message: strOf(o, 'message', ''),
    progress: numOf(o, 'progress', 0),
    versionType: versionType
  };
  return deployment;
}

export async function getPlatformDeploymentLogs(ctx: Context, appId: string): Promise<string[]> {
  const data: Object = await platformRequest(ctx,
    `/api/v1/app/deploy-logs?appId=${encodeURIComponent(appId)}`, http.RequestMethod.GET, null);
  const out: string[] = [];
  let entries: Object | null = Array.isArray(data) ? data : null;
  if (entries === null) {
    const o: Record<string, Object> | null = objOf(data);
    if (o !== null && Array.isArray(o['logs'])) {
      entries = o['logs'] as Object[];
    }
  }
  if (entries === null) {
    return out;
  }
  for (const entry of entries as Object[]) {
    if (typeof entry === 'string') {
      const line: string = (entry as string).trim();
      if (line.length > 0) {
        out.push(line);
      }
      continue;
    }
    const o: Record<string, Object> | null = objOf(entry);
    if (o === null) {
      continue;
    }
    let message: string = strOf(o, 'message', '');
    if (message.length === 0) {
      message = strOf(o, 'log', '');
    }
    if (message.length === 0) {
      message = strOf(o, 'content', '');
    }
    if (message.length === 0) {
      continue;
    }
    let level: string = strOf(o, 'level', '');
    if (level.length === 0) {
      level = strOf(o, 'source', '');
    }
    out.push(level.length > 0 ? `[${level.toUpperCase()}] ${message}` : message);
  }
  return out;
}

async function appAction(ctx: Context, path: string, appId: string): Promise<void> {
  const body: Record<string, Object> = {};
  body['appId'] = appId;
  await platformRequest(ctx, path, http.RequestMethod.POST, JSON.stringify(body));
}

export async function restartPlatformDeployment(ctx: Context, appId: string): Promise<void> {
  await appAction(ctx, '/api/v1/app/restart', appId);
}

export async function resetPlatformQwenPawAuth(ctx: Context, appId: string): Promise<void> {
  await appAction(ctx, '/api/v1/app/reset-qwenpaw-auth', appId);
}

export async function switchPlatformDeploymentVersion(ctx: Context, appId: string,
  version: string): Promise<void> {
  await appAction(ctx, version === 'stable' ? '/api/v1/app/stable' : '/api/v1/app/pre', appId);
}

// 状态呈现（对齐 7378 deploymentStatusPresentation）
export function deploymentStatusPresentation(status: string): DeploymentStatusPresentation {
  switch (status.toLowerCase()) {
    case 'idle':
      return statusValue(t($r('app.string.deploy_status_idle')), t($r('app.string.deploy_status_idle_desc')), false, false);
    case 'creating':
      return statusValue(t($r('app.string.deploy_status_creating')), t($r('app.string.deploy_status_creating_desc')), true, false);
    case 'pending':
    case 'deploying':
      return statusValue(t($r('app.string.deploy_status_deploying')), t($r('app.string.deploy_status_deploying_desc')), true, false);
    case 'rate_limited':
      return statusValue(t($r('app.string.deploy_status_in_progress')), t($r('app.string.deploy_status_in_progress_desc')), true, false);
    case 'starting':
      return statusValue(t($r('app.string.deploy_status_starting')), t($r('app.string.deploy_status_starting_desc')), true, false);
    case 'restarting':
      return statusValue(t($r('app.string.deploy_status_restarting')), t($r('app.string.deploy_status_restarting_desc')), true, false);
    case 'updating':
      return statusValue(t($r('app.string.deploy_status_switching')), t($r('app.string.deploy_status_switching_desc')), true, false);
    case 'waking_up':
    case 'sleeping':
      return statusValue(t($r('app.string.deploy_status_waking')), t($r('app.string.deploy_status_waking_desc')), true, false);
    case 'stopped':
      return statusValue(t($r('app.string.deploy_status_recovering')), t($r('app.string.deploy_status_recovering_desc')), true, false);
    case 'running':
      return statusValue(t($r('app.string.deploy_status_ready')), t($r('app.string.deploy_status_ready_desc')), false, false);
    case 'failed':
      return statusValue(t($r('app.string.deploy_status_not_ready')), t($r('app.string.deploy_status_not_ready_desc')), false, true);
    case 'deleted':
      return statusValue(t($r('app.string.deploy_status_removed')), t($r('app.string.deploy_status_removed_desc')), false, true);
    default:
      return statusValue(t($r('app.string.deploy_status_preparing')), t($r('app.string.deploy_status_preparing_desc')), true, false);
  }
}

function statusValue(label: string, detail: string, active: boolean,
  failed: boolean): DeploymentStatusPresentation {
  const p: DeploymentStatusPresentation = {
    label: label, detail: detail, active: active, failed: failed
  };
  return p;
}

// 镜像与 Mobile 的兼容性（对齐 7378 platformMobileCompatibility）
export function deploymentCompatibility(versionType: string): DeploymentCompatibility {
  const v: string = versionType.trim().toLowerCase();
  if (v.length === 0) {
    return { compatible: true, label: 'QwenPaw' };
  }
  if (v === 'stable') {
    return { compatible: true, label: t($r('app.string.deploy_version_stable')) };
  }
  if (v === 'beta' || v === 'pre' || v === 'preview') {
    return { compatible: true, label: 'QwenPaw Beta' };
  }
  if (v === 'data' || v === 'qwenpaw-data' || v === 'qwenpaw_data') {
    return { compatible: false, label: 'QwenPaw Data' };
  }
  return { compatible: false, label: versionType.trim().length > 0 ? versionType.trim() : t($r('app.string.deploy_version_unknown')) };
}

// 错误文案映射（对齐 7378 platformDeploymentErrorMessage）
export function deploymentErrorMessage(e: Error): string {
  const raw: string = e.message.length > 0 ? e.message : String(e);
  const msg: string = raw.toLowerCase();
  if (e instanceof PlatformRequestError) {
    const err: PlatformRequestError = e as PlatformRequestError;
    if (err.status === 429) {
      return t($r('app.string.deploy_msg_rate_limited'));
    }
  }
  if (msg.indexOf('asp.auth.github_bind_required') >= 0 ||
    (msg.indexOf('github') >= 0 && msg.indexOf('bind') >= 0)) {
    return t($r('app.string.deploy_msg_github_required'));
  }
  if (msg.indexOf('qualification') >= 0) {
    return t($r('app.string.deploy_msg_not_eligible'));
  }
  if (msg.indexOf('violation') >= 0) {
    return t($r('app.string.deploy_msg_forbidden'));
  }
  if (msg.indexOf('application_pending') >= 0 || msg.indexOf('appeal_pending') >= 0) {
    return t($r('app.string.deploy_msg_pending_review'));
  }
  if (msg.indexOf('extracting response') >= 0 || msg.indexOf('application/octet-stream') >= 0) {
    return t($r('app.string.deploy_msg_unavailable'));
  }
  return raw.length > 0 ? raw : t($r('app.string.deploy_msg_failed'));
}

// 是否为终态（不再轮询；对齐 7378 isTerminalDeployment）
export function isTerminalDeployment(status: string): boolean {
  const s: string = status.toLowerCase();
  return s === 'running' || s === 'failed' || s === 'deleted';
}

// 三步进度（对齐 7378 deploymentProgress + ProgressStep）
export function deploymentProgress(status: string, hasDeployment: boolean): number {
  if (!hasDeployment) {
    return 0;
  }
  switch (status.toLowerCase()) {
    case 'creating':
      return 1;
    case 'running':
      return 3;
    case 'pending':
    case 'deploying':
    case 'starting':
    case 'restarting':
    case 'updating':
    case 'waking_up':
    case 'sleeping':
    case 'stopped':
      return 2;
    default:
      return 1;
  }
}
