/*
 * 待审批服务 —— 对齐 PR #7378：
 *   取数：GET {base}/api/console/push-messages → { pending_approvals: PendingApproval[] }（client.ts listApprovals）
 *   批准：POST {base}/api/approval/approve {request_id, session_id: root_session_id, user_id:'mobile', scope}
 *   拒绝：POST {base}/api/approval/deny    {request_id, session_id: root_session_id, user_id:'mobile', reason}
 * 字段防御式解析。
 */

import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf, ConnectError } from './ConnectionService';

export interface ApprovalInfo {
  requestId: string;
  rootSessionId: string;     // 审批回传用的 session_id（对齐 RN：session_id = root_session_id）
  agentId: string;
  toolName: string;          // 展示名（tool_display_name 优先）
  toolSource: string;
  severity: string;          // high / critical 等
  findingsCount: number;
  findingsSummary: string;
  timeoutSeconds: number;    // 倒计时总时长（秒）；0 = 服务端未给
  createdAt: number;
  reasoning: string;
  toolParams: string;        // 工具参数（JSON 文本，原样展示）
  isGeneralized: boolean;
  exactTarget: string;       // 本次目标（「仅本次」范围）
  similarTarget: string;     // 始终允许范围（「始终允许」范围）
}

function strOf(rec: Record<string, Object>, key: string): string {
  const v: Object = rec[key];
  return typeof v === 'string' ? v as string : '';
}

function numOf(rec: Record<string, Object>, key: string): number {
  const v: Object = rec[key];
  return typeof v === 'number' ? v as number : 0;
}

// 工具参数可能是对象，统一转成可展示的 JSON 文本
function paramsText(rec: Record<string, Object>): string {
  const v: Object = rec['tool_params'];
  if (v === undefined || v === null) {
    return '';
  }
  if (typeof v === 'string') {
    return v as string;
  }
  try {
    return JSON.stringify(v);
  } catch (e) {
    return '';
  }
}

export async function fetchApprovals(baseUrl: string, token: string, agentId: string): Promise<ApprovalInfo[]> {
  const resp: http.HttpResponse = await doRequest(
    `${baseUrl}/api/console/push-messages`, http.RequestMethod.GET, null,
    token.length > 0 ? token : null, agentId);
  if (resp.responseCode === 401 || resp.responseCode === 403) {
    throw new ConnectError(`票据已失效（HTTP ${resp.responseCode}），请回到「会话」页重新连接。`);
  }
  if (resp.responseCode !== 200) {
    throw new ConnectError(`读取审批列表失败（HTTP ${resp.responseCode}）。`);
  }
  const data: Record<string, Object> = jsonOf(resp);
  const arr: Object = data['pending_approvals'];
  if (!Array.isArray(arr)) {
    return [];
  }
  const items: Object[] = arr as Object[];
  const out: ApprovalInfo[] = [];
  for (const item of items) {
    const a: Record<string, Object> = item as Record<string, Object>;
    const display: string = strOf(a, 'tool_display_name');
    const name: string = display.length > 0 ? display : strOf(a, 'tool_name');
    const findings: Object = a['findings_summary'];
    const info: ApprovalInfo = {
      requestId: strOf(a, 'request_id'),
      rootSessionId: strOf(a, 'root_session_id'),
      agentId: strOf(a, 'agent_id'),
      toolName: name.length > 0 ? name : '工具调用',
      toolSource: strOf(a, 'tool_source'),
      severity: strOf(a, 'severity'),
      findingsCount: numOf(a, 'findings_count'),
      findingsSummary: typeof findings === 'string' ? findings as string : '',
      timeoutSeconds: numOf(a, 'timeout_seconds'),
      createdAt: numOf(a, 'created_at'),
      reasoning: strOf(a, 'reasoning'),
      toolParams: paramsText(a),
      isGeneralized: a['is_generalized'] === true,
      exactTarget: strOf(a, 'exact_target'),
      similarTarget: strOf(a, 'similar_target')
    };
    out.push(info);
  }
  return out;
}

// 审批请求体（对齐 RN approve/deny 的 JSON 结构）
interface ApproveBody {
  request_id: string;
  session_id: string;
  user_id: string;
  scope: string;
}

interface DenyBody {
  request_id: string;
  session_id: string;
  user_id: string;
  reason: string;
}

// 批准：scope = 'exact'（仅本次）/ 'similar'（始终允许），对齐 RN approve()
export async function approveRequest(baseUrl: string, token: string, agentId: string,
  requestId: string, rootSessionId: string, scope: string): Promise<void> {
  const body: ApproveBody = {
    request_id: requestId,
    session_id: rootSessionId,
    user_id: 'mobile',
    scope: scope
  };
  const resp: http.HttpResponse = await doRequest(`${baseUrl}/api/approval/approve`,
    http.RequestMethod.POST, JSON.stringify(body), token.length > 0 ? token : null, agentId);
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new ConnectError(`批准失败（HTTP ${resp.responseCode}）。`);
  }
}

// 拒绝：对齐 RN deny()
export async function denyRequest(baseUrl: string, token: string, agentId: string,
  requestId: string, rootSessionId: string, reason: string): Promise<void> {
  const body: DenyBody = {
    request_id: requestId,
    session_id: rootSessionId,
    user_id: 'mobile',
    reason: reason
  };
  const resp: http.HttpResponse = await doRequest(`${baseUrl}/api/approval/deny`,
    http.RequestMethod.POST, JSON.stringify(body), token.length > 0 ? token : null, agentId);
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new ConnectError(`拒绝失败（HTTP ${resp.responseCode}）。`);
  }
}
