/*
 * 智能体展示档案 —— 昵称 + 头像底色（对齐 PR #7378 storage/agentAppearance.ts 的本地外观覆盖：
 * 只改本机列表/标题的显示，不动服务端数据）。存于应用沙箱 preferences。
 */

import { preferences } from '@kit.ArkData';
import { Context } from '@kit.AbilityKit';

export interface AgentProfile {
  id: string;
  name: string;    // 空 = 用服务端名
  color: string;   // 头像底色（hex），空 = 用主题色
}

const STORE_NAME: string = 'qwenpaw.agentprofile';
const KEY: string = 'qwenpaw.mobile.agentprofile.v1';

// 头像可选底色（一期用预设调色板，避免相册权限与图像处理链路）
export const AVATAR_COLORS: string[] = [
  '#FF7F16', '#3B82F6', '#10B981', '#8B5CF6', '#EC4899', '#F59E0B'
];

export function profileName(profiles: Map<string, AgentProfile>, agentId: string,
  serverName: string): string {
  const p: AgentProfile | undefined = profiles.get(agentId);
  if (p !== undefined && p.name.length > 0) {
    return p.name;
  }
  return serverName;
}

export function profileColor(profiles: Map<string, AgentProfile>, agentId: string): string {
  const p: AgentProfile | undefined = profiles.get(agentId);
  return p !== undefined ? p.color : '';
}

export function firstChar(name: string): string {
  return name.length > 0 ? name.substring(0, 1).toUpperCase() : '?';
}

export async function loadProfiles(context: Context): Promise<Map<string, AgentProfile>> {
  const out: Map<string, AgentProfile> = new Map<string, AgentProfile>();
  try {
    const store: preferences.Preferences = await preferences.getPreferences(context, STORE_NAME);
    const raw: preferences.ValueType = await store.get(KEY, '');
    if (typeof raw !== 'string' || raw.length === 0) {
      return out;
    }
    const arr: Object = JSON.parse(raw) as Object;
    if (!Array.isArray(arr)) {
      return out;
    }
    const items: Object[] = arr as Object[];
    for (const item of items) {
      const rec: Record<string, Object> = item as Record<string, Object>;
      const id: Object = rec['id'];
      if (typeof id !== 'string' || (id as string).length === 0) {
        continue;
      }
      const name: Object = rec['name'];
      const color: Object = rec['color'];
      out.set(id as string, {
        id: id as string,
        name: typeof name === 'string' ? name as string : '',
        color: typeof color === 'string' ? color as string : ''
      });
    }
  } catch (e) {
    return out;
  }
  return out;
}

export async function saveProfile(context: Context, profile: AgentProfile): Promise<void> {
  const store: preferences.Preferences = await preferences.getPreferences(context, STORE_NAME);
  const current: Map<string, AgentProfile> = await loadProfiles(context);
  if (profile.name.length === 0 && profile.color.length === 0) {
    current.delete(profile.id);
  } else {
    current.set(profile.id, profile);
  }
  const list: AgentProfile[] = [];
  current.forEach((value: AgentProfile): void => {
    list.push(value);
  });
  await store.put(KEY, JSON.stringify(list));
  await store.flush();
}
