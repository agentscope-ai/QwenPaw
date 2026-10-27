/*
 * 文件树行（工作台 · 文件页的宽屏横排形态专用）：
 *   层级缩进 + 竖向引导线 + 紧跟名称的展开/收起 chevron + 右侧文件大小。
 *
 * 为什么单独一个组件而不复用 IosRow：
 *   IosRow 是「清单行」（图标 + 标题 + 副标题 + 尾部箭头），整行是一个带底色的卡片块；用它做
 *   层级只能靠"把整块卡片右移"表达父子关系，缩进越深卡片越窄，读起来像错位而不是树。文件树要
 *   表达的是"同一棵树里的父子"，所以按层级画竖向引导线、箭头紧跟名称、行高收紧（与系统文件
 *   管理器一致）。数据与交互（点开后取子目录/预览）仍由页面持有。
 *
 * 两条工程内既有约束照旧：内容区沉浸材质不生效 → 底色用 backgroundColor；分隔线用独立 Divider
 * 子节点（受光组件设 border 会覆盖点光源）。
 */

import { UiTokens } from '../theme/UiTokens';
import { PressLatch, pressEffect, pressTouch } from '../theme/PressFx';

// 每层缩进（vp）：一层的层级差要看得出来，又不至于把可用宽度吃光
const INDENT: number = 22;
// 引导线宽 / 缩进车道宽度
const GUIDE_W: number = 1;
// 展开箭头的占位宽度（文件行留同宽空位，名称才对齐）
const CHEVRON_W: number = 18;
// 行高（比清单行的 60vp 收紧）
const ROW_H: number = 46;

@Component
export struct FileTreeRow {
  @Prop name: string = '';
  @Prop icon: Resource = $r('app.media.file_text');
  @Prop isDir: boolean = false;
  @Prop sizeText: string = '';
  @Prop depth: number = 0;
  @Prop expanded: boolean = false;
  @Prop tappable: boolean = true;
  onPress: () => void = (): void => {};
  @State pressed: boolean = false;
  private latch: PressLatch = new PressLatch();

  // 该行左侧要画的引导线条数 = 层级数（ForEach 需要数组，build 里不能用 for 循环）
  private guideSlots(): number[] {
    const out: number[] = [];
    for (let i = 0; i < this.depth; i++) {
      out.push(i);
    }
    return out;
  }

  build() {
    Column() {
      Row() {
        // 层级引导线：一层一条车道，线画在车道中央（正好落在上层的箭头/图标列中心下方）
        ForEach(this.guideSlots(), (_i: number) => {
          Row() {
            Divider()
              .vertical(true)
              .height('100%')
              .strokeWidth(GUIDE_W)
              .color($r('app.color.line'))
          }
          .width(INDENT)
          .height('100%')
          .justifyContent(FlexAlign.Center)
        }, (i: number) => i.toString())
        // 展开箭头：只有目录有；文件行留同宽空位保证名称对齐
        if (this.isDir) {
          Image(this.expanded ? $r('app.media.chevron_down') : $r('app.media.chevron_right'))
            .width(14)
            .height(14)
            .fillColor($r('app.color.text_tertiary'))
            .margin({ left: 2, right: 4 })
        } else {
          Column().width(CHEVRON_W).height(1)
        }
        Image(this.icon)
          .width(18)
          .height(18)
          .fillColor($r('app.color.text_secondary'))
        Text(this.name)
          .fontSize(UiTokens.fsBody)
          .fontColor($r('app.color.text_primary_strong'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
          .margin({ left: 10 })
        if (this.sizeText.length > 0) {
          Text(this.sizeText)
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_tertiary'))
            .maxLines(1)
            .margin({ left: 8 })
        }
      }
      .width('100%')
      .height(ROW_H)
      .padding({ left: UiTokens.cardPad - 4, right: UiTokens.cardPad })
      .alignItems(VerticalAlign.Center)
      .backgroundColor(this.pressed ? $r('app.color.card_bg') : $r('app.color.card_surface'))
      .visualEffect(pressEffect(this.pressed))
      .onTouch((e: TouchEvent): void => {
        if (!this.tappable) {
          return;
        }
        pressTouch(this.getUIContext(), e, this.latch, (v: boolean): void => {
          this.pressed = v;
        });
      })
      .onClick((): void => {
        if (this.tappable) {
          this.onPress();
        }
      })
      Divider()
        .color($r('app.color.line'))
        .strokeWidth(0.5)
    }
    .width('100%')
  }
}
