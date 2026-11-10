/*
 * 主题同步 —— 读取 QwenPaw 控制台主题（GET /api/config/theme），
 * 供移动端「主题色与 console 同步」使用。ThemeConfig 形状对齐
 * console/src/api/modules/theme.ts（accent / accent_bg / radius / dark.accent）。
 */

import { http } from '@kit.NetworkKit';
import { common } from '@kit.AbilityKit';
import { doRequest, jsonOf } from './ConnectionService';
import { QpConnection, loadConnection } from './ConnectionStore';
import { ThemeManager } from '../theme/ThemeManager';

export interface ConsoleTheme {
  accent: string;       // 浅色主色（'' = 控制台未配置自定义色）
  accentDark: string;   // 深色主色（'' = 未配置 → 回落浅色主色）
}

function strOf(rec: Record<string, Object>, key: string): string {
  const v: Object = rec[key];
  return typeof v === 'string' ? v as string : '';
}

export async function fetchConsoleTheme(baseUrl: string, token: string,
  agentId: string): Promise<ConsoleTheme | null> {
  try {
    const resp: http.HttpResponse = await doRequest(`${baseUrl}/api/config/theme`,
      http.RequestMethod.GET, null, token.length > 0 ? token : null, agentId);
    if (resp.responseCode !== 200) {
      return null;
    }
    const data: Record<string, Object> = jsonOf(resp);
    const accent: string = strOf(data, 'accent');
    let accentDark: string = '';
    const dark: Object = data['dark'];
    if (dark !== null && dark !== undefined && typeof dark === 'object' && !Array.isArray(dark)) {
      accentDark = strOf(dark as Record<string, Object>, 'accent');
    }
    if (accentDark.length === 0) {
      accentDark = accent;
    }
    const out: ConsoleTheme = { accent: accent, accentDark: accentDark };
    return out;
  } catch (e) {
    return null;
  }
}

// 取控制台主题并应用到 ThemeManager（App 启动 / 手动刷新调用）。
// 控制台未自定义主色（accent 空）→ 关闭同步，回落预设；返回是否成功取到。
export async function syncConsoleThemeToManager(ctx: common.UIAbilityContext): Promise<boolean> {
  const conn: QpConnection | null = await loadConnection(ctx);
  if (conn === null) {
    return false;
  }
  const theme: ConsoleTheme | null = await fetchConsoleTheme(conn.baseUrl, conn.token, conn.agentId);
  if (theme === null) {
    return false;
  }
  if (theme.accent.length === 0) {
    await ThemeManager.get().setSyncEnabled(false, ctx);
    return true;
  }
  await ThemeManager.get().applySyncedTheme(theme.accent, theme.accentDark, ctx);
  return true;
}
