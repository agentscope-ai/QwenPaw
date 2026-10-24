/*
 * 可按压玻璃卡外壳（社区帖子卡用）—— 与 components/GlassCard.ets 逐项同款：
 * 外层 Column 只管水平留白/间距，卡片本体是 **Button**（点光源的发光/受光在 Button 语义下才完整），
 * 底色 card_glass + 统一圆角，**不加描边**（官方点光源口径：受光组件设 border 的颜色/宽度会覆盖点光源）。
 *
 * 为什么单独抽出来：社区帖子卡自带动作键（点赞/评论/浏览/分享），需要"整卡按压 + 卡内按钮各自按压"，
 * 用 @BuilderParam 槽位把帖子内容塞进来即可，不必把帖子卡内部的嵌套结构整块重写。
 */
import { UiTokens } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';

@Component
export struct PressCard {
  @BuilderParam content: () => void;
  onTap: () => void = (): void => {};
  radius: number = UiTokens.cardRadius;
  // 外层水平留白（内 padding，必须挂在这里而不是滚动容器的外层容器上）：
  // 留白若挂在包住 List 的容器上，List 视口会被一起缩窄，卡片铺满视口 →
  // 按压照亮一越过卡片边界就撞上视口边缘被裁（实测外侧 6px 处即硬落回背景值，
  // 而同页基准卡是平滑衰减 40–50px）。留白留在卡内侧，视口铺满屏宽，光才有地方落。
  insetH: number = UiTokens.pageHMargin;
  padH: number = 15;
  padV: number = 15;
  gapBottom: number = 12;
  // 高卡（帖卡）中心到边缘超出默认羽化范围 → 用 BORDER 受光让整圈边界都亮（见 PressFx.pressEffect）
  edgeGlow: boolean = false;
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
      // 卡片边界只由半透明玻璃底 + 圆角表达（禁描边，见文件头）
      .backgroundColor($r('app.color.card_glass'))
      .borderRadius(this.radius)
      // 属性顺序与 GlassCard 一致：底色/圆角在前，scale/stateEffect/visualEffect 在后
      .scale({ x: this.pressed ? PRESS_SCALE : 1, y: this.pressed ? PRESS_SCALE : 1 })
      .stateEffect(false)
      .visualEffect(pressEffect(this.pressed, this.edgeGlow))
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
    .margin({ bottom: this.gapBottom })
  }
}
