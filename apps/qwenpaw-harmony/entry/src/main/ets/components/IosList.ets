/*
 * iOS 风格分组列表（IosGroup / IosRow）—— 对齐 PR #7378 components/IosList.tsx。
 *
 * 工作台各模块设置页统一走这套行组件（分组标题 + 圆角分组 + 行：图标 / 主副标题 / 尾部值 / 开关 / 箭头），
 * 避免每个模块各写一遍卡片与行样式。
 *
 * 两条官方约束决定写法：
 *   1) 内容区沉浸材质不生效（《沉浸光感常见问题》：材质只在弹窗类组件与标题栏/TabBar 作用域内生效）
 *      → 行底色用 backgroundColor，不用 systemMaterial；强调色用主题色（theme/Accent）。
 *   2) 受光组件设了 border 会覆盖点光源效果（《点光源效果》）→ 行分隔线用独立 Divider 子节点，
 *      不写成受压行的 border；按压反馈 = 底色变化 + 点光源（不做缩放：行在分组内缩放会露出分组底色）。
 */

import { common } from '@kit.AbilityKit';
import { UiTokens } from '../theme/UiTokens';
import { PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { isDarkMode, accentColor } from '../theme/Accent';

@Component
export struct IosGroup {
  @BuilderParam content: () => void;
  title: string = '';

  build() {
    Column() {
      if (this.title.length > 0) {
        Text(this.title)
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .width('100%')
          .margin({ bottom: 6 })
      }
      Column() {
        this.content()
      }
      .width('100%')
      .borderRadius(UiTokens.cardRadius)
      .clip(true)
    }
    .width('100%')
    .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
    .margin({ bottom: 16 })
  }
}

@Component
export struct IosRow {
  icon: Resource = $r('sys.symbol.folder');
  // 下列参数会随父组件状态变化（加载完成、开关/选项改值）→ 必须 @Prop：
  // 无装饰器的成员变量只在构造时赋值，父组件重渲染不会同步（官方状态管理原理：更新以自定义组件为
  // 单位，仅状态变量参与同步），否则会出现"改了值但行上还显示旧值"。
  @Prop showIcon: boolean = true;
  @Prop label: string = '';
  @Prop subtitle: string = '';
  @Prop trailing: string = '';
  @Prop destructive: boolean = false;
  // 尾部开关（Toggle 在沉浸光感白名单内，全页面可用）
  @Prop hasSwitch: boolean = false;
  @Prop switchOn: boolean = false;
  onSwitch: (on: boolean) => void = (): void => {};
  // 可点击时才显示箭头
  @Prop tappable: boolean = false;
  onPress: () => void = (): void => {};
  @State pressed: boolean = false;
  private latch: PressLatch = new PressLatch();
  private dark: boolean = false;

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.dark = isDarkMode(ctx);
  }

  build() {
    Column() {
      Row() {
        if (this.showIcon) {
          Stack() {
            SymbolGlyph(this.icon)
              .fontSize(18)
              .fontColor([$r('app.color.text_secondary')])
          }
          .width(30)
          .height(30)
          .borderRadius(10)
          .backgroundColor($r('app.color.card_bg'))
          .margin({ right: 12 })
        }
        Column() {
          Text(this.label)
            .fontSize(UiTokens.fsBody)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.destructive
              ? $r('app.color.status_error') : $r('app.color.text_primary_strong'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          if (this.subtitle.length > 0) {
            Text(this.subtitle)
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .margin({ top: 2 })
          }
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        if (this.hasSwitch) {
          Toggle({ type: ToggleType.Switch, isOn: this.switchOn })
            .selectedColor(accentColor(this.dark))
            .margin({ left: 8 })
            .onChange((on: boolean): void => {
              this.onSwitch(on);
            })
        } else if (this.trailing.length > 0) {
          Text(this.trailing)
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_tertiary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .constraintSize({ maxWidth: 150 })
            .margin({ left: 8 })
        }
        if (this.tappable) {
          Text('›')
            .fontSize(20)
            .fontColor($r('app.color.text_tertiary'))
            .margin({ left: 4 })
        }
      }
      .width('100%')
      .constraintSize({ minHeight: 60 })
      .padding({ left: UiTokens.cardPad, right: UiTokens.cardPad, top: 10, bottom: 10 })
      .backgroundColor(this.pressed ? $r('app.color.card_bg') : $r('app.color.card_surface'))
      .visualEffect(pressEffect(this.pressed))
      .onTouch((e: TouchEvent): void => {
        pressTouch(this.getUIContext(), e, this.latch, (v: boolean): void => {
          this.pressed = v;
        });
      })
      .onClick((): void => {
        this.onPress();
      })
      Divider()
        .color($r('app.color.line'))
        .strokeWidth(0.5)
    }
    .width('100%')
  }
}
