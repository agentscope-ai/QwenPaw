/*
 * 分栏右栏的空态占位（平板 / PC 横屏、会话页分栏时）。
 *
 * 平台行为：Navigation 分栏下路由栈为空时右侧为空白（深色下观感即一片纯黑）。官方 FAQ
 * (faqs-arkui-1276)《Navigation 在分栏模式下，如何给右侧空白部分设置默认页面》给两条路：
 * 把默认页 push 进路由栈，或由 splitPlaceholder 指定占位内容。这里取后者 —— 占位内容不进
 * 路由栈，因此不占返回、也不会在切回单栏后被压在会话页下面；"占位页仅作为UI展示页，不可获焦
 * 和响应事件"，也不需要额外的返回键消耗逻辑。
 *
 * 本文件只提供占位内容本身，ComponentContent 由 pages/Index.ets 构造并挂到 HdsNavigation 上。
 */

import { UiTokens } from '../theme/UiTokens';

@Builder
export function chatPlaceholderPane() {
  Column() {
    Image($r('app.media.qwenpaw_ip'))
      .width(180)
      .objectFit(ImageFit.Contain)
      .draggable(false)
    Text($r('app.string.split_placeholder_hint'))
      .fontSize(UiTokens.fsBody)
      .fontColor($r('app.color.text_tertiary'))
      .margin({ top: 16 })
  }
  .width('100%')
  .height('100%')
  .justifyContent(FlexAlign.Center)
  .alignItems(HorizontalAlign.Center)
  .backgroundColor($r('app.color.page_bg'))
  .expandSafeArea([SafeAreaType.SYSTEM],
    [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
}
