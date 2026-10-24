/*
 * 会话消息骨架屏。
 *
 * 依据官方 FAQ《点击进入页面后，页面内的单个组件异常闪动》(faqs-arkui-1489)：
 *   「应用没有使用骨架屏占位，部分组件需要在获取数据后才会出现。如果组件突然出现，
 *     会导致闪动。修改建议：页面建议使用骨架屏功能，避免组件突然出现造成闪动。」
 * 其骨架屏做法 = 灰底占位块 + 渐变高光横扫（linearGradient + translate 循环补间）。
 *
 * 本组件只做占位，不发起任何请求；数据到位后由页面替换为真实列表。
 */

import { UiTokens } from '../theme/UiTokens';

@Component
export struct ChatSkeleton {
  // 高光横扫位移（-100% → 100% 循环）
  @State sweepX: string = '-100%';

  aboutToAppear(): void {
    // 官方 animateTo 显式动画：iterations -1 = 无限循环
    this.getUIContext().animateTo({
      duration: 1400, curve: Curve.Linear, iterations: -1
    }, (): void => {
      this.sweepX = '100%';
    });
  }

  @Builder
  private placeholderBlock(w: string, h: number) {
    Stack() {
      Row()
        .width('100%')
        .height(h)
        .borderRadius(10)
        .backgroundColor($r('app.color.card_bg'))
      // 高光条：渐变透明→亮→透明，随 sweepX 横扫；靠外层 clip 收在圆角内
      Row()
        .width('45%')
        .height(h)
        .borderRadius(10)
        .linearGradient({
          angle: 90,
          colors: [['#00FFFFFF', 0.0], ['#26FFFFFF', 0.5], ['#00FFFFFF', 1.0]]
        })
        .translate({ x: this.sweepX })
    }
    .width(w)
    .height(h)
    .borderRadius(10)
    .clip(true)
    .margin({ top: 12 })
    .alignSelf(ItemAlign.Start)
  }

  build() {
    Column() {
      // 与消息节奏相近的几行占位（发送方右对齐留白一块，其余左对齐）
      this.placeholderBlock('62%', 46)
      this.placeholderBlock('86%', 46)
      this.placeholderBlock('48%', 46)
      this.placeholderBlock('74%', 46)
      Row()
        .width('38%')
        .height(46)
        .borderRadius(10)
        .backgroundColor($r('app.color.card_bg'))
        .margin({ top: 12 })
        .alignSelf(ItemAlign.End)
      this.placeholderBlock('70%', 46)
    }
    .width('100%')
    // 顶部让开沉浸标题栏带：与消息列表首项 spacer 同口径（UiTokens.topInset）
    .padding({ left: 16, right: 16, top: UiTokens.topInset })
    .alignItems(HorizontalAlign.Start)
  }
}
