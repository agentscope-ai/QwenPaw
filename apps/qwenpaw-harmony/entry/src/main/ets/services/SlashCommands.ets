/*
 * 聊天页魔法命令（'/' slash 命令）—— 对齐 console @agentscope-ai/chat Sender 的 suggestion 行为：
 *   - 触发：输入行以 '/' 开头且斜杠后无空白（SDK getSlashCommandKeyword 口径）；关键词取斜杠后文本
 *   - 过滤：命令名大小写不敏感包含
 *   - 选中：输入行整体替换为 "/command "（不自动执行；命令执行语义全在服务端，客户端只注入文本
 *     原样发送，与 console prepareLoopModeMessage 对斜杠开头的文本"不拦截、原样发出"一致）
 *
 * 命令清单来源（装配顺序与 console Chat/index.tsx options 一致）：
 *   1. 宿主命令 /new /clear（固定）
 *   2. QwenPaw 内置 /compact /skills
 *   3. 循环模式 GET /api/loops（与运行状态条同源；slash_command 为空的 default 模式跳过，
 *      与保留命令重名跳过）
 *   4. 技能 GET /api/skills（X-Agent-Id；仅 enabled 且 console 通道可见，与保留命令/循环
 *      重名跳过，按名排序）
 *   循环/技能取数失败降级为内置命令，不打断聊天。
 */

import { http } from '@kit.NetworkKit';
import { doRequest, jsonArrayOf } from './ConnectionService';
import { t } from './I18n';

export class SlashItem {
  command: string = '';   // "/new"（展示文本）
  value: string = '';     // "new"（过滤与插入的键）
  description: string = '';
}

export function slashItem(command: string, description: string): SlashItem {
  const it: SlashItem = new SlashItem();
  it.command = command;
  it.value = command.replace(/^\//, '').trim();
  it.description = description;
  return it;
}

/** 斜杠弹层应打开时的过滤关键词（小写）；应关闭时返回 null（对齐 SDK 触发口径）。 */
export function slashKeyword(draft: string): string | null {
  if (!draft.startsWith('/')) {
    return null;
  }
  const rest: string = draft.substring(1);
  if (/\s/.test(rest)) {
    return null;
  }
  return rest.toLowerCase();
}

/** 大小写不敏感的包含过滤（SDK 只按 value 匹配，描述不参与）。 */
export function filterSlashItems(items: SlashItem[], keyword: string): SlashItem[] {
  const kw: string = keyword.toLowerCase();
  const out: SlashItem[] = [];
  for (const it of items) {
    if (it.value.toLowerCase().includes(kw)) {
      out.push(it);
    }
  }
  return out;
}

/** 选中命令后输入行整体替换文本（对齐 SDK triggerValueChange("/" + value + " ")）。 */
export function slashInsertText(item: SlashItem): string {
  return `/${item.value} `;
}

/** 循环模式描述：内置模式取客户端 i18n（与运行状态条同一套资源串），其余取服务端
 * description_i18n（zh 优先），再退回原始 description。 */
function loopDescFor(id: string, rec: Record<string, Object>): string {
  if (id === 'goal') {
    return t($r('app.string.chat_loop_desc_goal'));
  }
  if (id === 'mission') {
    return t($r('app.string.chat_loop_desc_mission'));
  }
  const i18n: Object = rec['description_i18n'];
  if (i18n !== undefined && i18n !== null) {
    const map: Record<string, Object> = i18n as Record<string, Object>;
    const zh: Object = map['zh'] !== undefined ? map['zh'] : map['zh-CN'];
    if (typeof zh === 'string' && (zh as string).length > 0) {
      return zh as string;
    }
  }
  const raw: Object = rec['description'];
  return typeof raw === 'string' ? raw as string : '';
}

/** 技能是否对聊天页可见（对齐 console isSkillAvailableInConsole）：enabled 且通道为 all/console。 */
function skillVisibleInConsole(rec: Record<string, Object>): boolean {
  if (rec['enabled'] !== true) {
    return false;
  }
  const ch: Object = rec['channels'];
  if (ch === undefined || ch === null) {
    return true;
  }
  const arr: Object[] = ch as Object[];
  if (arr.length === 0) {
    return true;
  }
  for (const c of arr) {
    if (c === 'all' || c === 'console') {
      return true;
    }
  }
  return false;
}

/** 组装命令目录（内置 + 循环 + 技能）。网络失败只降级对应段，始终返回内置段。 */
export async function loadSlashCatalog(baseUrl: string, token: string, agentId: string): Promise<SlashItem[]> {
  const items: SlashItem[] = [
    slashItem('/new', ''),
    slashItem('/clear', t($r('app.string.chat_slash_clear_desc'))),
    slashItem('/compact', t($r('app.string.chat_slash_compact_desc'))),
    slashItem('/skills', t($r('app.string.chat_slash_skills_desc')))
  ];
  const reserved: Set<string> = new Set<string>();
  for (const it of items) {
    reserved.add(it.value);
  }
  const loopNames: Set<string> = new Set<string>();
  try {
    const resp: http.HttpResponse = await doRequest(`${baseUrl}/api/loops`, http.RequestMethod.GET, null,
      token.length > 0 ? token : null, agentId);
    if (resp.responseCode >= 200 && resp.responseCode < 300) {
      for (const it of jsonArrayOf(resp)) {
        const rec: Record<string, Object> = it as Record<string, Object>;
        const cmd: Object = rec['slash_command'];
        if (typeof cmd !== 'string' || (cmd as string).trim().length === 0) {
          continue; // default 模式没有斜杠命令
        }
        const name: string = (cmd as string).trim();
        if (reserved.has(name) || loopNames.has(name)) {
          continue;
        }
        const id: Object = rec['id'];
        loopNames.add(name);
        items.push(slashItem(`/${name}`, loopDescFor(typeof id === 'string' ? id as string : '', rec)));
      }
    }
  } catch (e) {
    // 循环目录取不到：降级，只保留内置命令
  }
  try {
    const resp: http.HttpResponse = await doRequest(`${baseUrl}/api/skills`, http.RequestMethod.GET, null,
      token.length > 0 ? token : null, agentId);
    if (resp.responseCode >= 200 && resp.responseCode < 300) {
      const skills: SlashItem[] = [];
      for (const it of jsonArrayOf(resp)) {
        const rec: Record<string, Object> = it as Record<string, Object>;
        const nm: Object = rec['name'];
        if (typeof nm !== 'string' || (nm as string).length === 0) {
          continue;
        }
        const name: string = nm as string;
        if (reserved.has(name) || loopNames.has(name)) {
          continue;
        }
        if (!skillVisibleInConsole(rec)) {
          continue;
        }
        skills.push(slashItem(`/${name}`, ''));
      }
      skills.sort((a: SlashItem, b: SlashItem): number => a.value.localeCompare(b.value));
      for (const s of skills) {
        items.push(s);
      }
    }
  } catch (e) {
    // 技能列表取不到：降级，只保留内置命令与循环
  }
  return items;
}
