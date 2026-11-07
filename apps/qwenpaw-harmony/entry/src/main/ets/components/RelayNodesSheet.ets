/*
 * 自部署连接管理半模态 —— 移植 PR #7378 features/platform/RelayNodesSheet.tsx。
 * 展示 Platform 汇总的自部署连接（QwenPaw 节点）：额度、在线状态、当前节点，并可解除绑定。
 *
 * 半模态由调用方 .bindSheet 承载，本组件只渲染内容（与 OptionsSheet 同口径）：
 *   · 顶部留白让开系统关闭叉（✕）与拖拽条，底部让开系统导航区；
 *   · 卡片走灰色 token sheet_card_bg（与玻璃背板拉开层次）；
 *   · 数据由父组件（设置页）取，本组件只渲染 + 发动作（面板节点会被复用，数据留在父侧更稳）。
 */

import { window } from '@kit.ArkUI';
import { UiTokens, pxPerVp } from '../theme/UiTokens';
import { accentColor } from '../theme/Accent';
import { PlatformRelayNode, PlatformRelayQuota } from '../services/PlatformRelay';
import { t, tf } from '../services/I18n';

const NAV_FALLBACK_INSET: number = 12;
const TOP_ZONE_H: number = 76;

@Component
export struct RelayNodesSheet {
  // 要经 @Prop 进面板：均为类实例/基本类型（ArkUI @Prop 口径）
  @Prop nodes: PlatformRelayNode[] = [];
  @Prop quota: PlatformRelayQuota = new PlatformRelayQuota();
  // 当前正在使用的节点 id（用于打「当前」标）；空 = 未连接
  @Prop currentNodeId: string = '';
  @Prop loading: boolean = false;
  @Prop removingId: string = '';
  @Prop error: string = '';
  @State navInset: number = 0;
  onReload: () => void = (): void => {};
  onRevoke: (nodeId: string) => void = (): void => {};
  @StorageLink('appIsDark') dark: boolean = false;

  aboutToAppear(): void {
    // 底部系统导航区高度：面板最后一屏内容 / 列表末端不能被手势条压住
    window.getLastWindow(getContext(this)).then((w: window.Window): void => {
      const indicator: number = w.getWindowAvoidArea(window.AvoidAreaType.TYPE_NAVIGATION_INDICATOR)
        .bottomRect.height;
      const system: number = w.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM).bottomRect.height;
      const px: number = indicator > 0 ? indicator : system;
      this.navInset = px > 0 ? px / pxPerVp() : NAV_FALLBACK_INSET;
    }).catch((): void => {
      this.navInset = NAV_FALLBACK_INSET;
    });
    this.onReload();
  }

  private accent(): ResourceColor {
    return accentColor(this.dark);
  }

  // 额度过文案：不限量（limit < 0）时只报已用（对齐 7378 allowance）
  private allowance(): string {
    if (this.quota.limit < 0) {
      return tf($r('app.string.relay_quota_used'), this.quota.used);
    }
    return `${this.quota.used} / ${this.quota.limit}`;
  }

  private lastSeenText(node: PlatformRelayNode): string {
    if (node.lastSeenAt.length === 0) {
      return ` · ${t($r('app.string.relay_never_seen'))}`;
    }
    const ms: number = Date.parse(node.lastSeenAt);
    if (isNaN(ms)) {
      return '';
    }
    const d: Date = new Date(ms);
    return ` · ${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
  }

  // 解除绑定前确认（与设置页移除连接同一套：系统弹窗 + 破坏性按钮）
  private confirmRevoke(node: PlatformRelayNode): void {
    const label: string = node.name.length > 0 ? node.name : node.id;
    this.getUIContext().showAlertDialog({
      title: `${t($r('app.string.relay_revoke_title'))}“${label}”？`,
      message: t($r('app.string.relay_revoke_copy')),
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {
        }
      },
      secondaryButton: {
        value: t($r('app.string.relay_revoke_action')),
        action: (): void => {
          this.onRevoke(node.id);
        }
      }
    });
  }

  // copy 走闭包：错误文案可在重试后变化，@Builder 简单值参数按值传递不会刷新（官方口径）
  @Builder
  stateBlock(title: Resource, copy: () => string) {
    Column() {
      Image($r('app.media.cloud'))
        .width(26).height(26)
        .fillColor($r('app.color.text_tertiary'))
        .margin({ bottom: 10 })
      Text(title)
        .fontSize(17)
        .fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.text_primary_strong'))
        .textAlign(TextAlign.Center)
      Text(copy())
        .fontSize(UiTokens.fsSecondary)
        .fontColor($r('app.color.text_tertiary'))
        .textAlign(TextAlign.Center)
        .lineHeight(19)
        .margin({ top: 6 })
    }
    .width('100%')
    .padding({ left: 32, right: 32, top: 36, bottom: 36 })
    .alignItems(HorizontalAlign.Center)
  }

  @Builder
  nodeRow(node: PlatformRelayNode) {
    Row() {
      Column() {
        Image($r('app.media.cloud'))
          .width(19).height(19)
          .fillColor(this.accent())
      }
      .width(36)
      .height(36)
      .borderRadius(11)
      .backgroundColor($r('app.color.sheet_card_bg'))
      .justifyContent(FlexAlign.Center)

      Column() {
        Row({ space: 7 }) {
          Text(node.name.length > 0 ? node.name : node.id)
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.text_primary_strong'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
          if (node.id === this.currentNodeId) {
            Text($r('app.string.relay_current'))
              .fontSize(UiTokens.fsChip)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.accent())
          }
        }
        .width('100%')

        Text(`${node.status === 'online' ? t($r('app.string.relay_online'))
          : t($r('app.string.relay_offline'))}${this.lastSeenText(node)}`)
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 3 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      .margin({ left: 12 })

      if (this.removingId === node.id) {
        LoadingProgress()
          .width(20)
          .height(20)
          .color($r('app.color.status_error'))
      } else {
        Image($r('app.media.trash_2'))
          .width(18).height(18)
          .fillColor($r('app.color.status_error'))
          .padding(8)
          .onClick((): void => {
            this.confirmRevoke(node);
          })
      }
    }
    .width('100%')
    .constraintSize({ minHeight: 64 })
    .padding({ left: UiTokens.cardPad, right: UiTokens.cardPad, top: 10, bottom: 10 })
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.sheet_card_bg'))
    .margin({ bottom: 8 })
  }

  build() {
    Column() {
      // 顶部标题区：让开系统关闭叉（✕）与拖拽条
      Column() {
        Text($r('app.string.relay_nodes_title'))
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary_strong'))
          .width('100%')
        Text(`${t($r('app.string.relay_quota_prefix'))}${this.allowance()}`)
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_tertiary'))
          .width('100%')
          .margin({ top: 4 })
      }
      .width('100%')
      .height(TOP_ZONE_H)
      .padding({ left: 4, right: 4, top: 34 })
      .alignItems(HorizontalAlign.Start)

      if (this.loading && this.nodes.length === 0) {
        this.stateBlock($r('app.string.relay_loading'), (): string => {
          return t($r('app.string.relay_loading_copy'));
        })
      } else if (this.error.length > 0 && this.nodes.length === 0) {
        this.stateBlock($r('app.string.relay_error_title'), (): string => {
          return this.error;
        })
      } else if (this.nodes.length === 0) {
        this.stateBlock($r('app.string.relay_empty_title'), (): string => {
          return t($r('app.string.relay_empty_copy'));
        })
      } else {
        List() {
          ForEach(this.nodes, (node: PlatformRelayNode) => {
            ListItem() {
              this.nodeRow(node)
            }
          }, (node: PlatformRelayNode) => node.id)
        }
        .width('100%')
        .layoutWeight(1)
        // 列表末端留出系统导航区高度（列表自身不被处理，只让位）
        .padding({ bottom: this.navInset })
        .scrollBar(BarState.Off)
      }

      if (this.error.length > 0 && this.nodes.length > 0) {
        Text(this.error)
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.status_error'))
          .width('100%')
          .margin({ top: 4, bottom: 4 })
      }
    }
    .width('100%')
    .layoutWeight(1)
    .padding({ left: 20, right: 20 })
  }
}
