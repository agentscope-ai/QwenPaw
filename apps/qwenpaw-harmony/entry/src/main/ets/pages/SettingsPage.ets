/*
 * 账户与设备（设置页）—— 移植 PR #7378 app/(tabs)/me.tsx：
 *   账户卡 + 已配对连接（切换 / 移除）+ 外观（主题）+ 安全 + 关于与自检。
 * 路由：settings（由标题栏齿轮 / 工作台「连接与设置」打开；param.stack 用于跳转模块页）。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { common, Configuration, ConfigurationConstant } from '@kit.AbilityKit';
import { emitter } from '@kit.BasicServicesKit';
import { ThemeManager, ThemeSnapshot, ThemePreset, THEME_PRESETS } from '../theme/ThemeManager';
import { MinePage } from '../components/MinePage';
import {
  QpConnection, loadConnection, loadConnections, switchConnection, removeConnection,
  clearConnection, connectionKey
} from '../services/ConnectionStore';
import { hostOf } from '../services/PairingModel';
import { syncConsoleThemeToManager } from '../services/ConsoleTheme';
import { UiTokens } from '../theme/UiTokens';
import { SheetGate, moduleSheetOptions } from '../components/SheetGate';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { CONN_CHANGE_EVENT } from '../components/WorkbenchTab';

@Builder
export function SettingsPageBuilder(_name: string, param: Object) {
  SettingsPage({ params: param })
}

@Component
export struct SettingsPage {
  params: Object = new Object();
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @State isDark: boolean = false;
  @State conns: QpConnection[] = [];
  @State currentKey: string = '';
  @State themePickerShown: boolean = false;
  // 半模态开关走统一闸门（单向绑定 + 回退动画期间排队；材质/避让由 moduleSheetOptions 统一给）
  private themeGate: SheetGate = new SheetGate();
  @State syncEnabled: boolean = false;
  @State syncing: boolean = false;
  // 内容区沉浸光感（官方：内容区材质不生效）→ 自绘按压反馈：按下收缩 + 点光源
  @State pressed: number = -1;
  private pressLatch: PressLatch = new PressLatch();
  private stack: NavPathStack | null = null;

  private onPress(idx: number, e: TouchEvent): void {
    pressTouch(this.getUIContext(), e, this.pressLatch, (v: boolean): void => {
      this.pressed = v ? idx : -1;
    });
  }

  private isPressed(idx: number): boolean {
    return this.pressed === idx;
  }

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const st: Object = rec['stack'];
    this.stack = (st === undefined || st === null) ? null : st as NavPathStack;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.isDark = ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
      this.syncEnabled = ThemeManager.get().isSyncEnabled();
    });
    this.reloadConns(ctx);
  }

  onConfigurationUpdate(newConfig: Configuration): void {
    this.isDark = newConfig.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
  }

  private async reloadConns(ctx: common.UIAbilityContext): Promise<void> {
    const list: QpConnection[] = await loadConnections(ctx);
    this.conns = list;
    const cur: QpConnection | null = await loadConnection(ctx);
    this.currentKey = cur !== null ? connectionKey(cur) : '';
  }

  private currentThemeName(): string {
    for (const p of THEME_PRESETS) {
      if (p.id === this.theme.presetId) {
        return p.name;
      }
    }
    return '';
  }

  // 与控制台同步：开 → 立即取一次色；关 → 回落本地预设
  private async onToggleSync(on: boolean): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.syncEnabled = on;
    if (!on) {
      await ThemeManager.get().setSyncEnabled(false, ctx);
      this.theme = ThemeManager.get().snapshot();
      return;
    }
    await this.onRefreshTheme();
  }

  private async onRefreshTheme(): Promise<void> {
    if (this.syncing) {
      return;
    }
    this.syncing = true;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const ok: boolean = await syncConsoleThemeToManager(ctx);
    this.theme = ThemeManager.get().snapshot();
    this.syncEnabled = ThemeManager.get().isSyncEnabled();
    this.syncing = false;
    if (!ok) {
      this.getUIContext().getPromptAction().showToast({ message: this.t($r('app.string.settings_sync_failed')) });
    }
  }

  private accentColor(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  private async onPresetTap(preset: ThemePreset): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const ok: boolean = await ThemeManager.get().selectPreset(preset.id, ctx);
    if (ok) {
      this.theme = ThemeManager.get().snapshot();
      // 选预设会显式关闭同步，开关状态跟着回落
      this.syncEnabled = ThemeManager.get().isSyncEnabled();
    }
    this.themeGate.beginClose();
    this.themePickerShown = false;
  }

  private openThemePicker(): void {
    if (this.themeGate.request()) {
      this.themePickerShown = true;
    }
  }

  private async onSwitch(key: string): Promise<void> {
    if (key === this.currentKey) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    await switchConnection(ctx, key);
    await this.reloadConns(ctx);
    emitter.emit(CONN_CHANGE_EVENT);
  }

  private confirmRemove(conn: QpConnection): void {
    const host: string = hostOf(conn.baseUrl);
    this.getUIContext().showAlertDialog({
      title: this.t($r('app.string.settings_remove_title')),
      message: `${host}\n${this.t($r('app.string.settings_remove_msg'))}`,
      primaryButton: {
        value: this.t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: this.t($r('app.string.settings_remove')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          this.doRemove(conn);
        }
      }
    });
  }

  private async doRemove(conn: QpConnection): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    await removeConnection(ctx, connectionKey(conn));
    await this.reloadConns(ctx);
    emitter.emit(CONN_CHANGE_EVENT);
  }

  private confirmDisconnectAll(): void {
    this.getUIContext().showAlertDialog({
      title: this.t($r('app.string.settings_disconnect_title')),
      message: $r('app.string.settings_disconnect_msg'),
      primaryButton: {
        value: this.t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: this.t($r('app.string.settings_disconnect')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
          clearConnection(ctx).then((): void => {
            this.reloadConns(ctx);
            emitter.emit(CONN_CHANGE_EVENT);
          });
        }
      }
    });
  }

  private openModule(key: string): void {
    if (this.stack !== null) {
      const param: Record<string, string> = { 'key': key };
      this.stack.pushPath({ name: 'module', param: param });
    }
  }

  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  @Builder
  sectionTitle(res: Resource) {
    Text(res)
      .fontSize(UiTokens.fsCaption)
      .fontColor($r('app.color.text_tertiary'))
      .width('100%')
      .margin({ top: 18, bottom: 6 })
  }

  // 主题色选择半模态（主题色整合进菜单）
  @Builder
  themePickerSheet() {
    Column() {
      Text($r('app.string.settings_theme'))
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Bold)
        .margin({ bottom: 12 })
      Column() {
        ForEach(THEME_PRESETS, (preset: ThemePreset, i: number) => {
          this.presetSwatch(preset, 100 + i)
        }, (preset: ThemePreset) => preset.id)
      }
      .width('100%')
    }
    .width('100%')
    // 顶部留出系统关闭叉（✕）与拖拽条高度，避免标题落进关闭叉命中区
    .padding({ left: 20, right: 20, top: 64, bottom: 16 })
  }

  @Builder
  presetSwatch(preset: ThemePreset, idx: number) {
    Row() {
      Circle()
        .width(22)
        .height(22)
        .fill(this.isDark ? preset.accentDark : preset.accent)
        .stroke(this.theme.presetId === preset.id
          ? (this.isDark ? preset.accentDark : preset.accent) : $r('app.color.line'))
        .strokeWidth(this.theme.presetId === preset.id ? 3 : 1)
      Text(preset.name)
        .fontSize(UiTokens.fsSecondary)
        .fontColor(this.theme.presetId === preset.id
          ? $r('app.color.text_primary_strong') : $r('app.color.text_secondary'))
        .margin({ left: 8 })
    }
    .width('100%')
    .padding(10)
    .borderRadius(12)
    // 与其余半模态卡片统一走灰色 token，与玻璃背板拉开层次
    .backgroundColor($r('app.color.sheet_card_bg'))
    .margin({ left: 4, right: 4, top: 5, bottom: 5 })
    .scale({ x: this.isPressed(idx) ? PRESS_SCALE : 1, y: this.isPressed(idx) ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.isPressed(idx)))
    .onTouch((e: TouchEvent): void => {
      this.onPress(idx, e);
    })
    .onClick((): void => {
      this.onPresetTap(preset);
    })
  }

  @Builder
  connRow(conn: QpConnection, idx: number) {
    Row() {
      Column() {
        Text(hostOf(conn.baseUrl))
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Medium)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(conn.serverMode.length > 0 ? conn.serverMode : conn.source)
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 2 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      if (connectionKey(conn) === this.currentKey) {
        Text($r('app.string.settings_current'))
          .fontSize(UiTokens.fsChip)
          .fontColor(this.accentColor())
          .backgroundColor($r('app.color.card_bg'))
          .borderRadius(UiTokens.chipRadius)
          .padding({ left: 8, right: 8, top: 3, bottom: 3 })
          .margin({ right: 6 })
      } else {
        Text($r('app.string.settings_switch'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ right: 6 })
      }
      SymbolGlyph($r('sys.symbol.xmark'))
        .fontSize(16)
        .fontColor([$r('app.color.text_tertiary')])
        .padding(6)
        .onClick((): void => {
          this.confirmRemove(conn);
        })
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .margin({ bottom: 6 })
    .scale({ x: this.isPressed(idx) ? PRESS_SCALE : 1, y: this.isPressed(idx) ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.isPressed(idx)))
    .onTouch((e: TouchEvent): void => {
      this.onPress(idx, e);
    })
    .onClick((): void => {
      this.onSwitch(connectionKey(conn));
    })
  }

  build() {
    HdsNavDestination() {
      Scroll() {
        Column() {
          // 账户卡（对齐 RN me.tsx profile：当前连接 + Agent）
          Row() {
            Column() {
              Text($r('app.string.settings_account'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
              Text(this.conns.length > 0
                ? hostOf(this.conns[0].baseUrl) : this.t($r('app.string.wb_not_connected')))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
                .margin({ top: 3 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))
          .margin({ top: UiTokens.cardVGap })

          this.sectionTitle($r('app.string.settings_paired'))
          ForEach(this.conns, (c: QpConnection, i: number) => {
            this.connRow(c, i)
          }, (c: QpConnection) => connectionKey(c))

          this.sectionTitle($r('app.string.settings_theme'))
          Row() {
            Circle()
              .width(22)
              .height(22)
              .fill(this.isDark ? this.theme.accentDark : this.theme.accent)
              .margin({ right: 10 })
            Column() {
              Text($r('app.string.settings_theme'))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
              Text(this.syncEnabled
                ? this.t($r('app.string.settings_theme_synced'))
                : this.currentThemeName())
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .margin({ top: 2 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Text('›')
              .fontSize(20)
              .fontColor($r('app.color.text_tertiary'))
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))
          .scale({ x: this.isPressed(150) ? PRESS_SCALE : 1, y: this.isPressed(150) ? PRESS_SCALE : 1 })
          .visualEffect(pressEffect(this.isPressed(150)))
          .onTouch((e: TouchEvent): void => {
            this.onPress(150, e);
          })
          .onClick((): void => {
            this.openThemePicker();
          })

          this.sectionTitle($r('app.string.settings_theme_sync'))
          Row() {
            Column() {
              Text($r('app.string.settings_sync_title'))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
              Text($r('app.string.settings_sync_hint'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .margin({ top: 2 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Toggle({ type: ToggleType.Switch, isOn: this.syncEnabled })
              .selectedColor(this.accentColor())
              .onChange((on: boolean): void => {
                this.onToggleSync(on);
              })
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))

          Row() {
            Text($r('app.string.settings_sync_refresh'))
              .fontSize(UiTokens.fsBody)
              .fontWeight(FontWeight.Medium)
              .layoutWeight(1)
            if (this.syncing) {
              LoadingProgress()
                .width(20)
                .height(20)
                .color(this.accentColor())
            } else {
              Text('›')
                .fontSize(20)
                .fontColor($r('app.color.text_tertiary'))
            }
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))
          .margin({ top: 6 })
          .scale({ x: this.isPressed(160) ? PRESS_SCALE : 1, y: this.isPressed(160) ? PRESS_SCALE : 1 })
          .visualEffect(pressEffect(this.isPressed(160)))
          .onTouch((e: TouchEvent): void => {
            this.onPress(160, e);
          })
          .onClick((): void => {
            this.onRefreshTheme();
          })

          this.sectionTitle($r('app.string.settings_security_group'))
          Row() {
            SymbolGlyph($r('sys.symbol.checkmark_shield'))
              .fontSize(20)
              .fontColor([this.accentColor()])
              .margin({ right: 10 })
            Column() {
              Text($r('app.string.settings_security'))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
              Text($r('app.string.settings_security_hint'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .margin({ top: 2 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Text('›')
              .fontSize(20)
              .fontColor($r('app.color.text_tertiary'))
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))
          .scale({ x: this.isPressed(200) ? PRESS_SCALE : 1, y: this.isPressed(200) ? PRESS_SCALE : 1 })
          .visualEffect(pressEffect(this.isPressed(200)))
          .onTouch((e: TouchEvent): void => {
            this.onPress(200, e);
          })
          .onClick((): void => {
            this.openModule('security');
          })

          this.sectionTitle($r('app.string.about_title'))
          MinePage()

          Button($r('app.string.settings_disconnect'))
            .width('100%')
            .margin({ top: 20 })
            .backgroundColor($r('app.color.card_bg'))
            .fontColor($r('app.color.status_error'))
            .scale({ x: this.isPressed(300) ? PRESS_SCALE : 1, y: this.isPressed(300) ? PRESS_SCALE : 1 })
            .stateEffect(false)
            .visualEffect(pressEffect(this.isPressed(300)))
            .onTouch((e: TouchEvent): void => {
              this.onPress(300, e);
            })
            .onClick((): void => {
              this.confirmDisconnectAll();
            })
        }
        .width('100%')
        .padding({
          top: UiTokens.topInset,
          bottom: 32,
          left: UiTokens.pageHMargin, right: UiTokens.pageHMargin
        })
        .bindSheet(this.themePickerShown, this.themePickerSheet(),
          moduleSheetOptions(420, this.themeGate,
            (v: boolean): void => {
              this.themePickerShown = v;
            }))
      }
      .height('100%')
      .scrollBar(BarState.Auto)
      // 页面底色 + 扩绘制区到状态栏/导航栏：二级页根容器不自带底色时，标题栏以下与下带会露出窗口黑底（真机实测 (0,0,0)）
      .backgroundColor($r('app.color.page_bg'))
      .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
    }
    // 内容也扩到安全区外（布局级）：官方 NavDestination.ignoreLayoutSafeArea，
    // 与 expandSafeArea 同时设置时它优先；前置条件要求标题栏隐藏或 STACK 模式
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM], [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM])
    .titleBar({
      // 独立 NavDestination 各自配标题栏：静止态即磨砂（GRADIENT_BLUR + enableScrollEffect:false）
      style: {
        // 与主页同款沉浸：沉浸式渐变模糊 + 系统材质（等级 ADAPTIVE），静止态与滚动终点态都用主题色底。
        // 平台行为：深色下沉浸材质是"变暗玻璃"，会把底色压低（观感偏"透明"，属沉浸固有表现）。
        scrollEffectOpts: {
          enableScrollEffect: true,
          scrollEffectType: ScrollEffectType.IMMERSIVE_GRADIENT_BLUR
        },
        blurStrategy: BlurStrategy.ADAPTIVE,
        originalStyle: {
          backgroundStyle: {
            blurRadius: 12.0,
            backgroundColor: this.isDark ? this.theme.accentDark : this.theme.accent
          }
        },
        scrollEffectStyle: {
          backgroundStyle: {
            blurRadius: 12.0,
            backgroundColor: this.isDark ? this.theme.accentDark : this.theme.accent
          }
        },
        systemMaterialEffect: {
          materialType: hdsMaterial.MaterialType.ADAPTIVE,
          materialLevel: hdsMaterial.MaterialLevel.ADAPTIVE
        }
      },
      content: {
        title: {
          mainTitle: $r('app.string.settings_title')
        }
      },
      // 与主页一致：标题栏不避让安全区向上铺到状态栏区域，组件安全区关闭（否则状态栏带露系统底）
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
  }
}
