/*
 * 工作区徽章 + 切换面板 —— 对齐 7378 features/workspaces/WorkspaceSwitcher.tsx。
 *
 * 徽章（WorkspaceBadge）：工作区名（本地 / 私人 | Platform 云端）+ 智能体名 · 运行状态 + 下拉箭头，
 *   点按打开切换面板。多连接模型直接复用 services/ConnectionStore v2（connections[] + current key）。
 * 切换面板：已配对连接列表（平台/本地图标 + 工作区名 + baseUrl，当前项打勾）；
 *   点非当前项 = 切换连接；左滑 = 取消配对（ArkUI ListItem.swipeAction）；末尾「再配对一只 QwenPaw」。
 *
 * 与 7378 的差异（有意）：7378 的「再配对一只」跳到配对页（add=1）；本工程由调用方（连接面板）
 *   把该入口接到扫码配对页（路由 scan），行为一致。
 */

import { common } from '@kit.AbilityKit';
import {
  QpConnection, connectionKey, loadConnections, loadConnection, switchConnection, removeConnection
} from '../services/ConnectionStore';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { UiTokens } from '../theme/UiTokens';
import { accentColor } from '../theme/Accent';
import { t } from '../services/I18n';

const SHEET_HEIGHT: number = 460;
// 连接行高度（图标 40vp + 上下卡内边距各 12vp）
const WS_ROW_H: number = 64;

@Component
export struct WorkspaceBadge {
  // 运行状态文案（由调用方给出，如「已连接」）与当前智能体名
  @Prop statusText: string = '';
  @Prop agentName: string = '';
  // 外部连接变化（如重连/登出/切换工作区）时递增 → 重取已配对连接列表（@Watch 才能真正生效）
  @Prop @Watch('onReloadToken') reloadToken: number = 0;
  onSwitched: () => void = (): void => {
  };
  onAdd: () => void = (): void => {
  };
  @State list: QpConnection[] = [];
  @State currentKey: string = '';
  @State shown: boolean = false;
  @State busy: boolean = false;
  private gate: SheetGate = new SheetGate();
  @StorageLink('appIsDark') dark: boolean = false;

  aboutToAppear(): void {
    this.load();
  }

  // reloadToken 变化（会话页重连 / 登出 / 切换工作区后递增）→ 重取已配对连接，
  // 徽章上的工作区名与面板里的列表跟着变（此前该 prop 无人读取，刷新实际没发生）
  private onReloadToken(): void {
    this.load();
  }

  private ctx(): common.UIAbilityContext {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  private async load(): Promise<void> {
    const list: QpConnection[] = await loadConnections(this.ctx());
    this.list = list;
    const cur: QpConnection | null = await loadConnection(this.ctx());
    this.currentKey = cur !== null ? connectionKey(cur) : '';
  }

  // 工作区名（对齐 7378 workspaceName）
  private nameOf(c: QpConnection): string {
    return c.source === 'platform'
      ? t($r('app.string.ws_platform')) : t($r('app.string.ws_local'));
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.shown = false;
  }

  private open(): void {
    this.load();
    if (this.gate.request()) {
      this.shown = true;
    }
  }

  private async select(c: QpConnection): Promise<void> {
    const key: string = connectionKey(c);
    if (key === this.currentKey) {
      this.closeSheet();
      return;
    }
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      await switchConnection(this.ctx(), key);
      this.closeSheet();
      this.onSwitched();
      await this.load();
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.ws_switch_failed'))
      });
    } finally {
      this.busy = false;
    }
  }

  private async unpair(c: QpConnection): Promise<void> {
    const key: string = connectionKey(c);
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      await removeConnection(this.ctx(), key);
      if (key !== this.currentKey) {
        this.getUIContext().getPromptAction().showToast({
          message: `${this.nameOf(c)}${t($r('app.string.ws_unpaired'))}`
        });
        await this.load();
        return;
      }
      // 当前连接被移除：交给调用方（首页会切回配对表单）
      this.closeSheet();
      this.onSwitched();
      await this.load();
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.ws_unpair_failed'))
      });
    } finally {
      this.busy = false;
    }
  }

  private rowIcon(c: QpConnection): Resource {
    return c.source === 'platform' ? $r('app.media.cloud') : $r('app.media.monitor');
  }

  build() {
    Row() {
      // QwenPaw 品牌符号（源 175x235，偏瘦高 → 按高 22 给宽）
      Image($r('app.media.qwenpaw_symbol'))
        .width(17)
        .height(22)
        .draggable(false)
        .margin({ right: 8 })
      Column() {
        Text(this.nameOf(this.current()))
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.text_primary_strong'))
          .maxLines(1)
        Text(`${this.agentName.length > 0 ? this.agentName : '—'} · ${this.statusText}`)
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 2 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Image($r('app.media.chevron_down'))
        .width(16).height(16)
        .fillColor($r('app.color.text_tertiary'))
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .onClick((): void => {
      this.open();
    })
    .bindSheet(this.shown, this.sheet(), moduleSheetOptions(SHEET_HEIGHT, this.gate,
      (v: boolean): void => {
        this.shown = v;
      }))
  }

  private current(): QpConnection {
    const key: string = this.currentKey;
    for (const c of this.list) {
      if (connectionKey(c) === key) {
        return c;
      }
    }
    // 列表尚未取回时用空壳，避免 build 期空指针（文案会随 load 完成后刷新）
    return this.list.length > 0 ? this.list[0] : {
      baseUrl: '', token: '', username: '', agentId: '', source: 'private', serverMode: '',
      platformAccessPath: ''
    };
  }

  @Builder
  sheet() {
    Column() {
      // 关闭按钮不在此自绘：半模态系统关闭叉（moduleSheetOptions 的 showClose）已在右上角，
      // 这里再画一个就会同时出现两个关闭入口，故只留系统那个。
      Column() {
        Text($r('app.string.ws_switch_title'))
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary_strong'))
        Text($r('app.string.ws_switch_copy'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 4 })
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .margin({ bottom: 12 })

      // 列表贴内容高度，「再配对一只」紧随其后（不贴面板底部）
      Scroll() {
        Column() {
          List() {
            ForEach(this.list, (c: QpConnection) => {
              ListItem() {
                Row() {
                  Column() {
                    Image(this.rowIcon(c))
                      .width(20).height(20)
                      .fillColor(connectionKey(c) === this.currentKey
                        ? this.themeAccent() : $r('app.color.text_secondary'))
                  }
                  .width(40)
                  .height(40)
                  .borderRadius(20)
                  .backgroundColor($r('app.color.card_bg'))
                  .justifyContent(FlexAlign.Center)

                  Column() {
                    Text(this.nameOf(c))
                      .fontSize(UiTokens.fsBody)
                      .fontColor($r('app.color.text_primary_strong'))
                      .maxLines(1)
                    Text(c.baseUrl)
                      .fontSize(UiTokens.fsCaption)
                      .fontColor($r('app.color.text_tertiary'))
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                      .margin({ top: 2 })
                  }
                  .alignItems(HorizontalAlign.Start)
                  .layoutWeight(1)
                  .margin({ left: 10 })

                  if (connectionKey(c) === this.currentKey) {
                    Image($r('app.media.check'))
                      .width(18).height(18)
                      .fillColor(this.themeAccent())
                  }
                }
                .width('100%')
                .padding(UiTokens.cardPad)
                .borderRadius(UiTokens.cardRadius)
                .backgroundColor($r('app.color.sheet_card_bg'))
                .onClick((): void => {
                  this.select(c);
                })
              }
              // 左滑取消配对（官方 ListItem.swipeAction）
              .swipeAction({ end: this.unpairAction(c) })
            }, (c: QpConnection) => connectionKey(c))
          }
          .width('100%')
          // 列表按行数取高（不占满剩余空间），「再配对一只」才能紧跟列表之后
          .height(this.list.length * WS_ROW_H)
          .scrollBar(BarState.Off)
          .listDirection(Axis.Vertical)

          Row() {
            Column() {
              Image($r('app.media.plus'))
                .width(20).height(20)
                .fillColor(this.themeAccent())
            }
            .width(40)
            .height(40)
            .borderRadius(20)
            .backgroundColor($r('app.color.card_bg'))
            .justifyContent(FlexAlign.Center)

            Column() {
              Text($r('app.string.ws_add'))
                .fontSize(UiTokens.fsBody)
                .fontColor($r('app.color.text_primary_strong'))
                .maxLines(1)
              Text($r('app.string.ws_add_copy'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .maxLines(1)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
                .margin({ top: 2 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            .margin({ left: 10 })
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.sheet_card_bg'))
          .margin({ top: 8 })
          .onClick((): void => {
            this.closeSheet();
            this.onAdd();
          })
        }
        .width('100%')
      }
      .width('100%')
      .layoutWeight(1)
      // Scroll 配 layoutWeight 时内容少于视口会**居中**排布（官方 FAQ faqs-arkui-725）→
      // 卡片刻意置顶必须显式 align(Top)，否则"卡片不是靠上"。
      .align(Alignment.Top)
      .scrollBar(BarState.Off)
    }
    .width('100%')
    .height('100%')
    // 顶部留出系统关闭叉（✕）与拖拽条高度
    .padding({ left: 20, right: 20, top: 64 })
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  unpairAction(c: QpConnection) {
    Button() {
      Column() {
        Image($r('app.media.trash_2'))
          .width(20).height(20)
          .fillColor(Color.White)
        Text($r('app.string.ws_unpair'))
          .fontSize(UiTokens.fsCaption)
          .fontColor(Color.White)
          .margin({ top: 4 })
      }
    }
    .type(ButtonType.Normal)
    .width(88)
    .height('100%')
    .backgroundColor($r('app.color.status_error'))
    .onClick((): void => {
      this.unpair(c);
    })
  }

  private themeAccent(): ResourceColor {
    return accentColor(this.dark);
  }
}
