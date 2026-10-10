/*
 * 主题色取色口径（工作台模块页共用）
 *
 * 内容区沉浸材质不生效（官方《沉浸光感常见问题》）→ 模块页的强调色一律取主题色：
 * 浅色模式 accent / 深色模式 accentDark（与底部页签、标题栏同一口径）。
 * 深浅判定取当前 UIAbility 配置（ConfigurationConstant.ColorMode）。
 */

import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { ThemeManager, ThemeSnapshot } from './ThemeManager';

export function isDarkMode(ctx: common.UIAbilityContext): boolean {
  return ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
}

export function accentColor(dark: boolean): ResourceColor {
  const snap: ThemeSnapshot = ThemeManager.get().snapshot();
  return dark ? snap.accentDark : snap.accent;
}

function hexToInt(hex: string): number {
  const s: string = hex.replace('#', '').slice(-6).toLowerCase();
  let v: number = 0;
  for (let i = 0; i < s.length; i++) {
    const c: number = s.charCodeAt(i);
    const d: number = c >= 48 && c <= 57 ? c - 48 : c - 87;
    v = v * 16 + d;
  }
  return v;
}

// 两个 #RRGGBB 按比例混色（ratio = front 占比），返回**不透明** #RRGGBB。
// 用途：实底按钮的"弱化/置灰"态用混色表达，不引入透明度（alpha 会被底衬影响，观感发虚）。
export function blendHex(front: string, back: string, ratio: number): string {
  const f: number = hexToInt(front);
  const b: number = hexToInt(back);
  let out: string = '#';
  const shifts: number[] = [16, 8, 0];
  for (const shift of shifts) {
    const v: number = Math.round((((f >> shift) & 0xFF) * ratio) + (((b >> shift) & 0xFF) * (1 - ratio)));
    out += (v < 16 ? '0' : '') + v.toString(16);
  }
  return out;
}
