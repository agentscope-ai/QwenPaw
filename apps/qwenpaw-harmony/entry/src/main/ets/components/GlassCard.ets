/*
 * 玻璃卡片（内容区唯一卡组件）
 *
 * 为什么不再用 systemMaterial：官方《沉浸光感常见问题》明确——沉浸光感开启后，只有弹窗类
 * 组件/接口（弹窗、菜单、半模态等）与 Slider/Toggle/Select 可在全页面生效；**其他组件仅在
 * Navigation/NavDestination 标题栏或 barPosition=End 的底部 TabBar 内生效**，放在内容区会打印
 * `Material inactive: out of scope`，材质完全不生效（真机日志实证）。官方给出的替代措施即
 * 「改用 backgroundColor 等通用属性替代材质效果」→ 本组件就是该措施的统一实现。
 *
 * 统一内容：会话 / 智能体 / 工作台三页的卡片全部走这里，观感一致
 *   - 玻璃底色 card_glass + 统一圆角 UiTokens.cardRadius（不加描边：受光组件设 border 会覆盖点光源）
 *   - 按压弹性反馈：按下 90ms 跟手收缩、抬手弹簧回弹（PressFx.pressTouch）
 *   - 按压点光源：按下自身发光、照亮相邻卡片（PressFx.pressEffect）
 *   - 水平留白用内 padding（padding 在盒内）：列表滚动条贴屏幕右缘、卡片居中不溢出
 */
import { UiTokens } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';

@Component
export struct GlassCard {
  @BuilderParam content: () => void;
  onTap: () => void = (): void => {};
  // 外层水平留白（内 padding）与上下间距
  insetH: number = UiTokens.pageHMargin;
  gapTop: number = UiTokens.cardVGap;
  gapBottom: number = UiTokens.cardVGap;
  // 卡内间距（内容自带内间距的卡片传 0）
  padH: number = UiTokens.cardPad;
  padV: number = UiTokens.cardPad;
  radius: number = UiTokens.cardRadius;
  @State pressed: boolean = false;
  private latch: PressLatch = new PressLatch();

  build() {
    Column() {
      Button() {
        this.content()
      }
      .type(ButtonType.Normal)
      .width('100%')
      .padding({ left: this.padH, right: this.padH, top: this.padV, bottom: this.padV })
      .backgroundColor($r('app.color.card_glass'))
      // 圆角只由 borderRadius 给（见文件头：受光组件设 border 会覆盖点光源效果）
      .borderRadius(this.radius)
      // 按压弹性反馈 + 点光源（按下照亮相邻卡片），动画由 pressTouch 的 animateTo 驱动
      .scale({ x: this.pressed ? PRESS_SCALE : 1, y: this.pressed ? PRESS_SCALE : 1 })
      .stateEffect(false)
      .visualEffect(pressEffect(this.pressed))
      .onTouch((e: TouchEvent): void => {
        pressTouch(this.getUIContext(), e, this.latch, (v: boolean): void => {
          this.pressed = v;
        });
      })
      .onClick((): void => {
        this.onTap();
      })
    }
    .width('100%')
    .padding({ left: this.insetH, right: this.insetH })
    .margin({ top: this.gapTop, bottom: this.gapBottom })
  }
}
