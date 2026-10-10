/*
 * 主题色管理 —— 对齐 QwenPaw 控制台 themePresets.ts（6 预设，默认 QwenPaw 橙）。
 * 快照（ThemeSnapshot）供 UI 层 @State 读取；切换后重建快照触发重渲染。
 * 持久化：preferences（theme.json：presetId / customAccent）。
 *
 * 手指跟随光（沉浸光感 lightColor）：比主题色浅一点的 tint，浅色模式更明显。
 */

import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';

export interface ThemePreset {
  id: string;
  name: string;
  accent: string;      // 浅色模式主色
  accentDark: string;  // 深色模式主色
}

export interface ThemeSnapshot {
  presetId: string;
  customAccent: string;   // '' = 跟随预设浅色主色
  accent: string;         // 当前生效浅色主色
  accentDark: string;     // 当前生效深色主色
  accentBg: string;       // 浅色主色浅底（ARGB）
  accentBgDark: string;
  fingerGlow: string;     // 手指光（浅色模式）
  fingerGlowDark: string; // 手指光（深色模式）
}

// 与 console/src/pages/SettingsCenter/themePresets.ts 逐一对齐
export const THEME_PRESETS: ThemePreset[] = [
  { id: 'qwenpaw', name: 'QwenPaw', accent: '#ff7f16', accentDark: '#ff9d4d' },
  { id: 'codex', name: 'Codex', accent: '#2563eb', accentDark: '#60a5fa' },
  { id: 'ayu', name: 'Ayu', accent: '#c56a00', accentDark: '#ffb454' },
  { id: 'catppuccin', name: 'Catppuccin', accent: '#7c3aed', accentDark: '#c4a7e7' },
  { id: 'dracula', name: 'Dracula', accent: '#c0268f', accentDark: '#ff79c6' },
  { id: 'everforest', name: 'Everforest', accent: '#2f7d4b', accentDark: '#a7c080' },
];

export const DEFAULT_THEME_PRESET: ThemePreset = THEME_PRESETS[0];

function parseHex(color: string): number[] {
  let h: string = color.replace('#', '');
  if (h.length === 8) {
    h = h.substring(2);
  }
  if (h.length !== 6) {
    return [255, 127, 22];
  }
  const r: number = parseInt(h.substring(0, 2), 16);
  const g: number = parseInt(h.substring(2, 4), 16);
  const b: number = parseInt(h.substring(4, 6), 16);
  return [r, g, b];
}

function toHex(r: number, g: number, b: number): string {
  const f = (v: number): string => {
    const c: number = Math.max(0, Math.min(255, Math.round(v)));
    return c.toString(16).padStart(2, '0');
  };
  return `#${f(r)}${f(g)}${f(b)}`;
}

// a 向 b 混合，t ∈ [0,1]
export function mixHex(a: string, b: string, t: number): string {
  const pa: number[] = parseHex(a);
  const pb: number[] = parseHex(b);
  return toHex(pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t, pa[2] + (pb[2] - pa[2]) * t);
}

export function withAlpha(hex: string, alpha: number): string {
  const p: number[] = parseHex(hex);
  const a: string = Math.max(0, Math.min(255, Math.round(alpha))).toString(16).padStart(2, '0');
  return `#${a}${p[0].toString(16).padStart(2, '0')}${p[1].toString(16).padStart(2, '0')}${p[2].toString(16).padStart(2, '0')}`;
}

const PREF_NAME: string = 'theme';
const KEY_PRESET_ID: string = 'presetId';
const KEY_CUSTOM_ACCENT: string = 'customAccent';
// 与控制台同步（GET /api/config/theme）：开关 + 同步下来的浅/深主色
const KEY_SYNC_ENABLED: string = 'syncEnabled';
const KEY_SYNCED_ACCENT: string = 'syncedAccent';
const KEY_SYNCED_ACCENT_DARK: string = 'syncedAccentDark';

// 主题变更监听：UI 层（Index 等）订阅后即时刷新 @State 快照
export type ThemeListener = (snap: ThemeSnapshot) => void;

export class ThemeManager {
  private static inst: ThemeManager | null = null;
  private presetId: string = DEFAULT_THEME_PRESET.id;
  private customAccent: string = '';
  private syncEnabled: boolean = false;
  private syncedAccent: string = '';
  private syncedAccentDark: string = '';
  private listeners: ThemeListener[] = [];

  subscribe(fn: ThemeListener): void {
    this.listeners.push(fn);
  }

  unsubscribe(fn: ThemeListener): void {
    const i: number = this.listeners.indexOf(fn);
    if (i >= 0) {
      this.listeners.splice(i, 1);
    }
  }

  private notify(): void {
    const snap: ThemeSnapshot = this.snapshot();
    for (const fn of this.listeners) {
      fn(snap);
    }
  }

  static get(): ThemeManager {
    if (ThemeManager.inst === null) {
      ThemeManager.inst = new ThemeManager();
    }
    return ThemeManager.inst;
  }

  // 从 preferences 恢复（应用启动时调用一次）
  async load(ctx: common.UIAbilityContext): Promise<void> {
    try {
      const pref: preferences.Preferences = await preferences.getPreferences(ctx, PREF_NAME);
      this.presetId = (await pref.get(KEY_PRESET_ID, DEFAULT_THEME_PRESET.id)) as string;
      this.customAccent = (await pref.get(KEY_CUSTOM_ACCENT, '')) as string;
      this.syncEnabled = (await pref.get(KEY_SYNC_ENABLED, false)) as boolean;
      this.syncedAccent = (await pref.get(KEY_SYNCED_ACCENT, '')) as string;
      this.syncedAccentDark = (await pref.get(KEY_SYNCED_ACCENT_DARK, '')) as string;
      if (this.findPreset(this.presetId) === null) {
        this.presetId = DEFAULT_THEME_PRESET.id;
      }
    } catch (e) {
      // 首次运行 / 读失败：保持默认
    }
  }

  private findPreset(id: string): ThemePreset | null {
    for (const p of THEME_PRESETS) {
      if (p.id === id) {
        return p;
      }
    }
    return null;
  }

  private async persist(ctx: common.UIAbilityContext): Promise<void> {
    try {
      const pref: preferences.Preferences = await preferences.getPreferences(ctx, PREF_NAME);
      await pref.put(KEY_PRESET_ID, this.presetId);
      await pref.put(KEY_CUSTOM_ACCENT, this.customAccent);
      await pref.put(KEY_SYNC_ENABLED, this.syncEnabled);
      await pref.put(KEY_SYNCED_ACCENT, this.syncedAccent);
      await pref.put(KEY_SYNCED_ACCENT_DARK, this.syncedAccentDark);
      await pref.flush();
    } catch (e) {
      // 持久化失败不影响本次会话
    }
  }

  async selectPreset(id: string, ctx: common.UIAbilityContext): Promise<boolean> {
    if (this.findPreset(id) === null) {
      return false;
    }
    this.presetId = id;
    // 手动选预设 = 显式覆盖「与控制台同步」：同步开着时若不关闭，snapshot 仍取同步色，
    // 菜单点了没反应（死 UI）
    this.syncEnabled = false;
    this.syncedAccent = '';
    this.syncedAccentDark = '';
    this.notify();
    await this.persist(ctx);
    return true;
  }

  async setCustomAccent(hex: string, ctx: common.UIAbilityContext): Promise<void> {
    this.customAccent = hex;
    this.notify();
    await this.persist(ctx);
  }

  // 同步开关（开/关）；开启并不立即取色（取色由调用方 fetch 后 applySynced）
  async setSyncEnabled(enabled: boolean, ctx: common.UIAbilityContext): Promise<void> {
    this.syncEnabled = enabled;
    if (!enabled) {
      this.syncedAccent = '';
      this.syncedAccentDark = '';
    }
    this.notify();
    await this.persist(ctx);
  }

  // 应用从控制台同步来的主色（浅色 accent / 深色 accentDark）
  async applySyncedTheme(accent: string, accentDark: string, ctx: common.UIAbilityContext): Promise<void> {
    this.syncedAccent = accent;
    this.syncedAccentDark = accentDark.length > 0 ? accentDark : accent;
    this.syncEnabled = true;
    this.notify();
    await this.persist(ctx);
  }

  isSyncEnabled(): boolean {
    return this.syncEnabled;
  }

  snapshot(): ThemeSnapshot {
    const preset: ThemePreset = this.findPreset(this.presetId) ?? DEFAULT_THEME_PRESET;
    // 与控制台同步优先：同步到主色时直接用控制台浅/深色
    const useSync: boolean = this.syncEnabled && this.syncedAccent.length > 0;
    const hasCustom: boolean = this.customAccent.length > 0;
    const accent: string = useSync ? this.syncedAccent
      : (hasCustom ? this.customAccent : preset.accent);
    const accentDark: string = useSync
      ? (this.syncedAccentDark.length > 0 ? this.syncedAccentDark : this.syncedAccent)
      : (hasCustom ? mixHex(this.customAccent, '#ffffff', 0.3) : preset.accentDark);
    // accentBg 对齐 console：浅色 rgba(…,0.1)≈#1A，深色 rgba(…,0.16)≈#29
    const accentBg: string = withAlpha(accent, 0x1A);
    const accentBgDark: string = withAlpha(accentDark, 0x29);
    // 手指光：浅色模式 = 纯主题色半透明（浅底上向白混会发白，改用饱和主题色才可见）；
    // 深色模式 = 主题色向白提亮 25%，弱一点（深底上更柔和）。
    const fingerGlow: string = withAlpha(accent, 0x80);
    const fingerGlowDark: string = withAlpha(mixHex(accentDark, '#ffffff', 0.25), 0x60);
    const snap: ThemeSnapshot = {
      presetId: this.presetId,
      customAccent: this.customAccent,
      accent: accent,
      accentDark: accentDark,
      accentBg: accentBg,
      accentBgDark: accentBgDark,
      fingerGlow: fingerGlow,
      fingerGlowDark: fingerGlowDark
    };
    return snap;
  }
}
