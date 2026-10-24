/*
 * 审批卡片 —— 对齐 PR #7378 features/approvals/ApprovalCard.tsx：
 *   eyebrow「需要你的审批」+ 标题（tool_display_name || tool_name）；reasoning；severity 徽章 + N 项安全检查；
 *   详情折叠（本次目标 exact_target / 始终允许范围 similar_target / 工具参数 JSON）；
 *   底部三键：拒绝 / 仅本次(exact) / 始终允许(similar)。
 *   RN 显示条件：is_generalized && similar_target && tool_source !== "STRICT mode" 才给「始终允许」。
 * 卡片壳走 GlassCard（内容区统一玻璃卡），按钮按压走 PressFx（缩放 + 点光源）。
 */
import { common } from '@kit.AbilityKit';
import { UiTokens } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { ApprovalInfo } from '../services/ApprovalsService';
import { GlassCard } from './GlassCard';

@Component
export struct ApprovalCard {
  item: ApprovalInfo = {
    requestId: '', rootSessionId: '', agentId: '', toolName: '', toolSource: '',
    severity: '', findingsCount: 0, findingsSummary: '', timeoutSeconds: 0,
    createdAt: 0, reasoning: '', toolParams: '', isGeneralized: false,
    exactTarget: '', similarTarget: ''
  };
  onDeny: () => void = (): void => {};
  onApprove: (scope: string) => void = (_scope: string): void => {};
  @State details: boolean = false;
  @State btnPressed: number = -1;
  private btnLatch: PressLatch = new PressLatch();

  private highRisk(): boolean {
    return this.item.severity === 'high' || this.item.severity === 'critical';
  }

  // 对齐 RN：仅泛化目标且非 STRICT 模式才允许「始终允许」
  private canAlways(): boolean {
    return this.item.isGeneralized && this.item.similarTarget.length > 0
      && this.item.toolSource !== 'STRICT mode';
  }

  private onBtnTouch(idx: number, e: TouchEvent): void {
    pressTouch(this.getUIContext(), e, this.btnLatch, (v: boolean): void => {
      this.btnPressed = v ? idx : -1;
    });
  }

  private checksText(): string {
    if (this.item.findingsCount <= 0) {
      return '';
    }
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      const unit: string = host.resourceManager.getStringSync($r('app.string.approval_checks').id);
      return `${this.item.findingsCount} ${unit}`;
    } catch (e) {
      return `${this.item.findingsCount}`;
    }
  }

  build() {
    GlassCard() {
      Column() {
        Row() {
          Text($r('app.string.approval_need'))
            .fontSize(UiTokens.fsChip)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.highRisk() ? $r('app.color.status_error') : $r('app.color.text_secondary'))
            .layoutWeight(1)
          if (this.highRisk()) {
            Text(this.item.severity.toUpperCase())
              .fontSize(10)
              .fontWeight(FontWeight.Bold)
              .fontColor(Color.White)
              .backgroundColor($r('app.color.status_error'))
              .borderRadius(UiTokens.chipRadius)
              .padding({ left: 6, right: 6, top: 2, bottom: 2 })
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        Text(this.item.toolName)
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Medium)
          .margin({ top: 6 })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        if (this.item.findingsCount > 0) {
          Text(this.checksText())
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_tertiary'))
            .margin({ top: 4 })
        }
        if (this.item.reasoning.length > 0) {
          Text(this.item.reasoning)
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_secondary'))
            .margin({ top: 6 })
            .maxLines(3)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }

        Text(this.details ? $r('app.string.common_cancel') : $r('app.string.approval_details'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.btn_gray_text'))
          .margin({ top: 8 })
          .onClick((): void => {
            this.details = !this.details;
          })
        if (this.details) {
          if (this.item.exactTarget.length > 0) {
            Text(this.item.exactTarget)
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_secondary'))
              .margin({ top: 4 })
          }
          if (this.item.similarTarget.length > 0) {
            Text(this.item.similarTarget)
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_secondary'))
              .margin({ top: 4 })
          }
          if (this.item.toolParams.length > 0) {
            Text(this.item.toolParams)
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .margin({ top: 4 })
              .wordBreak(WordBreak.BREAK_ALL)
          }
        }

        Row() {
          Button($r('app.string.approval_deny'))
            .layoutWeight(1)
            .height(38)
            .fontSize(UiTokens.fsSecondary)
            .backgroundColor($r('app.color.card_bg'))
            .fontColor($r('app.color.status_error'))
            .scale({ x: this.btnPressed === 0 ? PRESS_SCALE : 1, y: this.btnPressed === 0 ? PRESS_SCALE : 1 })
            .stateEffect(false)
            .visualEffect(pressEffect(this.btnPressed === 0))
            .onTouch((e: TouchEvent): void => {
              this.onBtnTouch(0, e);
            })
            .onClick((): void => {
              this.onDeny();
            })
          Button($r('app.string.approval_once'))
            .layoutWeight(1)
            .height(38)
            .margin({ left: 8 })
            .fontSize(UiTokens.fsSecondary)
            .backgroundColor($r('app.color.card_bg'))
            .fontColor($r('app.color.text_secondary'))
            .scale({ x: this.btnPressed === 1 ? PRESS_SCALE : 1, y: this.btnPressed === 1 ? PRESS_SCALE : 1 })
            .stateEffect(false)
            .visualEffect(pressEffect(this.btnPressed === 1))
            .onTouch((e: TouchEvent): void => {
              this.onBtnTouch(1, e);
            })
            .onClick((): void => {
              this.onApprove('exact');
            })
          if (this.canAlways()) {
            Button($r('app.string.approval_always'))
              .layoutWeight(1)
              .height(38)
              .margin({ left: 8 })
              .fontSize(UiTokens.fsSecondary)
              .backgroundColor($r('app.color.card_bg'))
              .fontColor($r('app.color.text_secondary'))
              .scale({ x: this.btnPressed === 2 ? PRESS_SCALE : 1, y: this.btnPressed === 2 ? PRESS_SCALE : 1 })
              .stateEffect(false)
              .visualEffect(pressEffect(this.btnPressed === 2))
              .onTouch((e: TouchEvent): void => {
                this.onBtnTouch(2, e);
              })
              .onClick((): void => {
                this.onApprove('similar');
              })
          }
        }
        .width('100%')
        .margin({ top: 12 })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }
}
