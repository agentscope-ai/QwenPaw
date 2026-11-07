/*
 * 工作台模块 · Tool Offload —— 对齐 PR #7378 features/workbench/OffloadSettings.tsx。
 *   GET /settings/offload-policy                     → { default_action }
 *   PUT /settings/offload-policy { default_action }  → 保存
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { ThemeManager, ThemeSnapshot } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { GlassCard } from './GlassCard';
import { t } from '../services/I18n';

@Component
export struct ModuleOffload {
  @State action: string = '';
  @State error: string = '';
  @State loaded: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @StorageLink('appIsDark') isDark: boolean = false;

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
    });
    this.load();
  }

  private async conn(): Promise<QpConnection | null> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    return await loadConnection(ctx);
  }

  private async load(): Promise<void> {
    const c: QpConnection | null = await this.conn();
    if (c === null) {
      this.error = t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    try {
      const resp: http.HttpResponse = await doRequest(`${c.baseUrl}/api/settings/offload-policy`,
        http.RequestMethod.GET, null, c.token.length > 0 ? c.token : null, c.agentId);
      if (resp.responseCode !== 200) {
        this.error = `HTTP ${resp.responseCode}`;
        this.loaded = true;
        return;
      }
      const a: Object = jsonOf(resp)['default_action'];
      this.action = (typeof a === 'string' && (a as string) === 'offload') ? 'offload' : 'keep_foreground';
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private async save(value: string): Promise<void> {
    const c: QpConnection | null = await this.conn();
    if (c === null) {
      return;
    }
    const body: Record<string, string> = { 'default_action': value };
    try {
      const resp: http.HttpResponse = await doRequest(`${c.baseUrl}/api/settings/offload-policy`,
        http.RequestMethod.PUT, JSON.stringify(body),
        c.token.length > 0 ? c.token : null, c.agentId);
      if (resp.responseCode >= 200 && resp.responseCode < 300) {
        const a: Object = jsonOf(resp)['default_action'];
        this.action = typeof a === 'string' ? a as string : value;
      } else {
        this.getUIContext().getPromptAction().showToast({ message: `HTTP ${resp.responseCode}` });
      }
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({ message: (e as Error).message });
    }
  }

  @Builder
  optionRow(icon: Resource, titleRes: Resource, subtitleRes: Resource, value: string) {
    GlassCard({
      insetH: 0,
      onTap: (): void => {
        this.save(value);
      }
    }) {
      Row() {
        Image(icon)
          .width(20).height(20)
          .fillColor($r('app.color.text_secondary'))
          .margin({ right: 8 })
        Column() {
          Text(titleRes)
            .fontSize(UiTokens.fsBody)
            .fontWeight(FontWeight.Medium)
          Text(subtitleRes)
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_tertiary'))
            .margin({ top: 2 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        if (this.action === value) {
          Text($r('app.string.module_selected'))
            .fontSize(UiTokens.fsChip)
            .fontColor(this.isDark ? this.theme.accentDark : this.theme.accent)
            .backgroundColor($r('app.color.card_bg'))
            .borderRadius(UiTokens.chipRadius)
            .padding({ left: 8, right: 8, top: 3, bottom: 3 })
        }
      }
      .width('100%')
    }
  }

  build() {
    Column() {
      if (this.error.length > 0) {
        Text(this.error)
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.status_error'))
          .width('100%')
          .margin({ bottom: 8 })
      } else if (!this.loaded) {
        LoadingProgress().width(28).height(28)
      } else {
        Text($r('app.string.module_offload_group'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .width('100%')
          .margin({ bottom: 6 })
        this.optionRow($r('app.media.zap'), $r('app.string.module_offload_keep'),
          $r('app.string.module_offload_keep_hint'), 'keep_foreground')
        this.optionRow($r('app.media.archive'),
          $r('app.string.module_offload_bg'), $r('app.string.module_offload_bg_hint'), 'offload')
        Text($r('app.string.module_offload_footer'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .width('100%')
          .margin({ top: 10 })
      }
    }
    .width('100%')
  }
}
