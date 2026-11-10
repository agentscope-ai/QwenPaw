/*
 * Agent 级审批等级（对齐 console / 后端契约：approval_level 是 **Agent 级**设置，存在 agent.json 的
 * profile 上）。这里只负责**读**：它是会话没有本地覆盖时的默认值。
 *
 * 读：GET /api/workspace/running-config → 该字段由后端 `getattr(agent_config, "approval_level")`
 *     回填（src/qwenpaw/app/routers/workspace.py 的 get_agents_running_config）。
 *
 * 为什么不在这里写：chat 页面的运行条改的是"这一个会话"的等级，服务的落点是**请求上下文 +
 * 本机会话偏好**（见 services/ChatApprovalPrefs.ets）；写 Agent 级字段会把整台 Agent 的默认值
 * 一起改掉（那是 console「Agent 配置」页 / 本工程工作台 Agent 配置模块的职责）。
 */

import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf, ConnectError } from './ConnectionService';
import { tf } from './I18n';

function authOf(token: string): string | null {
  return token.length > 0 ? token : null;
}

/** 读 Agent 当前审批等级（'' = 服务端未给值，调用方按"不带 request_context"处理）。 */
export async function fetchAgentApproval(baseUrl: string, token: string,
  agentId: string): Promise<string> {
  const resp: http.HttpResponse = await doRequest(`${baseUrl}/api/workspace/running-config`,
    http.RequestMethod.GET, null, authOf(token), agentId);
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new ConnectError(tf($r('app.string.err_load_agent_approval'), resp.responseCode));
  }
  const v: Object = jsonOf(resp)['approval_level'];
  return typeof v === 'string' ? v as string : '';
}
