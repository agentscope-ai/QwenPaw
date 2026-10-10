/*
 * 模块页状态位 —— 对齐 PR #7378 features/workbench/ModuleState.tsx。
 * 读取中 / 读取失败（可重试）/ 空态 / 页脚说明，工作台各模块设置页共用。
 * 只用既有色板（danger_bg / status_error / text_tertiary），不依赖主题色，故为无状态 @Builder。
 */

import { UiTokens } from '../theme/UiTokens';

@Builder
export function ModuleLoading(label: string) {
  Column() {
    LoadingProgress()
      .width(28)
      .height(28)
    Text(label)
      .fontSize(UiTokens.fsSecondary)
      .fontColor($r('app.color.text_tertiary'))
      .textAlign(TextAlign.Center)
      .margin({ top: 10 })
  }
  .width('100%')
  .constraintSize({ minHeight: 170 })
  .justifyContent(FlexAlign.Center)
  .borderRadius(UiTokens.cardRadius)
  .backgroundColor($r('app.color.card_surface'))
}

@Builder
export function ModuleError(message: string, onRetry: () => void) {
  Row() {
    SymbolGlyph($r('sys.symbol.exclamationmark_circle'))
      .fontSize(22)
      .fontColor([$r('app.color.status_error')])
      .margin({ right: 10 })
    Column() {
      Text($r('app.string.module_error_title'))
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.status_error'))
      Text(message)
        .fontSize(UiTokens.fsCaption)
        .fontColor($r('app.color.status_error'))
        .margin({ top: 3 })
        .width('100%')
        .wordBreak(WordBreak.BREAK_ALL)
    }
    .alignItems(HorizontalAlign.Start)
    .layoutWeight(1)
    SymbolGlyph($r('sys.symbol.arrow_clockwise'))
      .fontSize(20)
      .fontColor([$r('app.color.status_error')])
      .padding(6)
      .onClick((): void => {
        onRetry();
      })
  }
  .width('100%')
  .padding(UiTokens.cardPad)
  .borderRadius(UiTokens.cardRadius)
  .backgroundColor($r('app.color.danger_bg'))
  .alignItems(VerticalAlign.Top)
}

@Builder
export function ModuleEmpty(icon: Resource, title: string, subtitle: string) {
  Column() {
    SymbolGlyph(icon)
      .fontSize(28)
      .fontColor([$r('app.color.text_tertiary')])
    Text(title)
      .fontSize(UiTokens.fsBody)
      .fontWeight(FontWeight.Medium)
      .fontColor($r('app.color.text_primary_strong'))
      .margin({ top: 8 })
    Text(subtitle)
      .fontSize(UiTokens.fsSecondary)
      .fontColor($r('app.color.text_tertiary'))
      .textAlign(TextAlign.Center)
      .margin({ top: 4 })
  }
  .width('100%')
  .constraintSize({ minHeight: 170 })
  .justifyContent(FlexAlign.Center)
  .padding(UiTokens.cardPad)
  .borderRadius(UiTokens.cardRadius)
  .backgroundColor($r('app.color.card_surface'))
}

@Builder
export function ModuleFooter(text: string) {
  Text(text)
    .fontSize(UiTokens.fsCaption)
    .fontColor($r('app.color.text_tertiary'))
    .textAlign(TextAlign.Center)
    .width('100%')
    .margin({ top: 4, bottom: 8 })
}
