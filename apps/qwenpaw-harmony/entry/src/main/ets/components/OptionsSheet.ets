/*
 * 单选菜单半模态 —— 工作台模块页里「在一组选项里选一个」的统一菜单
 * （审批等级 / 思考等级 / Agent 语言 …），不落系统 ActionSheet。
 *
 * 观感与设置页主题色菜单一致：标题 + 选项行（当前项打勾 + 主题色）+ 取消。
 * 行按压用内容区自绘反馈（官方 FAQ：内容区沉浸材质不生效，改用通用属性 + 自绘）。
 * 半模态由调用方 .bindSheet 承载，本组件只渲染内容。
 */

import { common } from '@kit.AbilityKit';
import { UiTokens } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { isDarkMode, accentColor } from '../theme/Accent';

export class SheetOption {
  value: string = '';
  label: string = '';
}

export function optionOf(value: string, label: string): SheetOption {
  const o: SheetOption = new SheetOption();
  o.value = value;
  o.label = label;
  return o;
}

@Component
export struct OptionsSheet {
  title: string = '';
  @Prop options: SheetOption[] = [];
  // 当前选中值（与 SheetOption.value 比对，命中项打勾）——会随父组件改值 → @Prop
  @Prop current: string = '';
  onPick: (value: string) => void = (): void => {};
  onClose: () => void = (): void => {};
  @State pressed: number = -1;
  private latch: PressLatch = new PressLatch();
  private dark: boolean = false;

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.dark = isDarkMode(ctx);
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
  optionRow(o: SheetOption, idx: number) {
    Row() {
      Text(o.label)
        .fontSize(UiTokens.fsBody)
        .fontWeight(this.current === o.value ? FontWeight.Medium : FontWeight.Normal)
        .fontColor($r('app.color.text_primary_strong'))
        .layoutWeight(1)
      if (this.current === o.value) {
        SymbolGlyph($r('sys.symbol.checkmark'))
          .fontSize(18)
          .fontColor([accentColor(this.dark)])
      }
    }
    .width('100%')
    .constraintSize({ minHeight: 52 })
    .padding({ left: UiTokens.cardPad, right: UiTokens.cardPad })
    .borderRadius(UiTokens.cardRadius)
    // 选项卡片统一走 sheet_card_bg（灰色 token）：半模态玻璃背板逐档压暗后，
    // 纯 card_surface 与背板过近（真机实测两者像素仅差 1–2）；改一处 token 即可全局调整
    .backgroundColor($r('app.color.sheet_card_bg'))
    .margin({ bottom: 8 })
    .scale({ x: this.pressed === idx ? PRESS_SCALE : 1, y: this.pressed === idx ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.pressed === idx))
    .onTouch((e: TouchEvent): void => {
      pressTouch(this.getUIContext(), e, this.latch, (v: boolean): void => {
        this.pressed = v ? idx : -1;
      });
    })
    .onClick((): void => {
      this.onPick(o.value);
      this.onClose();
    })
  }

  build() {
    Column() {
      Text(this.title)
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Bold)
        .width('100%')
        .margin({ bottom: 12 })
      ForEach(this.options, (o: SheetOption, i: number) => {
        this.optionRow(o, i)
      }, (o: SheetOption) => o.value)
      Button($r('app.string.common_cancel'))
        .width('100%')
        .height(46)
        .margin({ top: 4 })
        .backgroundColor($r('app.color.card_bg'))
        .fontColor($r('app.color.btn_gray_text'))
        .stateEffect(false)
        .onClick((): void => {
          this.onClose();
        })
    }
    .width('100%')
    // 顶部留出系统关闭叉（✕）与拖拽条的高度，避免与标题/选项重叠
    .padding({ left: 20, right: 20, top: 64 })
  }
}
