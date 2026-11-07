/*
 * 单选菜单半模态 —— 工作台模块页里「在一组选项里选一个」的统一菜单
 * （审批等级 / 思考等级 / Agent 语言 …），不落系统 ActionSheet。
 *
 * 观感与设置页主题色菜单一致：标题 + 选项行（当前项打勾 + 主题色）+ 取消。
 * 行按压用内容区自绘反馈（官方 FAQ：内容区沉浸材质不生效，改用通用属性 + 自绘）。
 * 半模态由调用方 .bindSheet 承载，本组件只渲染内容。
 */

import { window, uiMaterial } from '@kit.ArkUI';
import { UiTokens, pxPerVp } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { accentColor } from '../theme/Accent';

// 底部导航区避让保底值（vp）：窗口避让区报 0 时仍让出约一个手势条的高度
const NAV_FALLBACK_INSET: number = 12;

// 顶部标题区高度（让开系统关闭叉 ✕ 与拖拽条后紧贴标题行，不浪费列表空间）
const TOP_ZONE_H: number = 76;
// 列表首/末渐变模糊带占列表高度的比例（两端各留一段做"渐变模糊"）。
// 顶部比例调大 = 模糊更早开始、更深，标题背后的卡片被糊得更彻底 → 标题更清楚
const BLUR_TOP_FRACTION: number = 0.30;
const BLUR_BOTTOM_FRACTION: number = 0.24;
// 渐变模糊的最大半径（linearGradientBlur 的首参）
const BLUR_MAX_RADIUS: number = 64;

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
  // 确认模式（可选）：true 时不显示「取消」——右上角 ✕ / 下拉即取消；
  // 点选项只切换选中态（打勾），点「确定」才提交（不再走 onPick）
  confirmPick: boolean = false;
  onPick: (value: string) => void = (): void => {};
  onConfirm: (value: string) => void = (): void => {};
  onClose: () => void = (): void => {};
  @State picked: string = '';
  // 是否已经点过某个选项：不能用 picked.length > 0 代替 ——「跟随 Agent / 继承默认」这类选项的
  // value 就是空串，用长度判据会让「确定」永远禁用，用户再也回不到默认档（实测：审批面板选中
  // 「跟随 Agent」后确定键点不动）
  @State pickedSet: boolean = false;
  @State navInset: number = 0;
  @State pressed: number = -1;
  private latch: PressLatch = new PressLatch();
  @StorageLink('appIsDark') dark: boolean = false;

  aboutToAppear(): void {
    this.picked = this.current;
    this.pickedSet = false;
    // 底部系统导航区高度：面板底部的「确定」不能被导航条/手势条压住。
    // 官方 window.getWindowAvoidArea：优先取导航指示条（手势条）避让区，退化到系统避让区；
    // 两者都为 0（沉浸窗口可能报 0）时用保底值，确保按钮不在手势条上。
    window.getLastWindow(getContext(this)).then((w: window.Window): void => {
      const indicator: number = w.getWindowAvoidArea(window.AvoidAreaType.TYPE_NAVIGATION_INDICATOR)
        .bottomRect.height;
      const system: number = w.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM).bottomRect.height;
      const px: number = indicator > 0 ? indicator : system;
      this.navInset = px > 0 ? px / pxPerVp() : NAV_FALLBACK_INSET;
    }).catch((): void => {
      this.navInset = NAV_FALLBACK_INSET;
    });
  }

  private isPicked(value: string): boolean {
    return this.confirmPick ? this.picked === value : this.current === value;
  }


  @Builder
  optionRow(o: SheetOption, idx: number) {
    Row() {
      Text(o.label)
        .fontSize(UiTokens.fsBody)
        .fontWeight(this.isPicked(o.value) ? FontWeight.Medium : FontWeight.Normal)
        .fontColor($r('app.color.text_primary_strong'))
        .layoutWeight(1)
      if (this.isPicked(o.value)) {
        Image($r('app.media.check'))
          .width(18).height(18)
          .fillColor(accentColor(this.dark))
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
      if (this.confirmPick) {
        this.picked = o.value;
        // 点过即视为"已选择"，确定键据此启用（空值选项也算）
        this.pickedSet = true;
        return;
      }
      this.onPick(o.value);
      this.onClose();
    })
  }

  // 顶部标题区高度（含系统关闭叉 ✕ 与拖拽条的留白）
  private topZone(): number {
    return TOP_ZONE_H;
  }

  // 底部按钮条高度（按钮 46 + 上渐变过渡区 16 + 下留白 12 + 系统导航区）
  private footerHeight(): number {
    return 46 + 16 + 12 + this.navInset;
  }

  build() {
    // 结构：列表照常占满面板（保留原生滚动）；顶栏与按钮条各自作为**显式高度的浮层**
    // 贴在列表/面板的同侧边缘 —— 卡片滑动时从两条下面穿过（渐变模糊透出、不被裁切），
    // 两条自身只做毛玻璃 + 竖向渐变，不压实底黑块；显式高度也避免浮层没撑满时被拉到中间。
    Column() {
      Scroll() {
        Column() {
          ForEach(this.options, (o: SheetOption, i: number) => {
            this.optionRow(o, i)
          }, (o: SheetOption) => o.value)
        }
        .width('100%')
      }
      .width('100%')
      .layoutWeight(1)
      .align(Alignment.Top)
      .scrollBar(BarState.Off)
      // 真·渐变模糊（官方 linearGradientBlur：内容线性渐变模糊）——
      // 列表两端各有一段由模糊渐入清晰，卡片滑入/滑出顶栏与按钮条时被"渐隐"而不是被实底盖住
      .linearGradientBlur(BLUR_MAX_RADIUS, {
        fractionStops: [
          [1, 0],
          [0, BLUR_TOP_FRACTION],
          [0, 1 - BLUR_BOTTOM_FRACTION],
          [1, 1]
        ],
        direction: GradientDirection.Bottom
      })
      // 首项从顶栏下缘开始、末项能滚到按钮条之上（留白只影响首尾；滑动中卡片照常穿过两条）
      .padding({
        top: this.topZone(),
        bottom: this.footerHeight(),
        left: 20,
        right: 20
      })
    }
    .width('100%')
    .height('100%')
    // 两条浮层挂在**外层 Column**（不在 Scroll 上）：Scroll 的 linearGradientBlur 会把自身
    // overlay 内容一起糊掉 —— 挂在 Scroll 上时"选择模型"标题被糊得看不清；移出后模糊只作用于
    // 列表内容，标题与按钮保持清晰。
    .overlay(this.bands(), { align: Alignment.Top })
  }

  // 顶栏 + 按钮条（同一浮层内分别贴上/贴下；根与占位层 None：自身不挡列表，子节点照常响应）
  @Builder
  bands() {
    Column() {
      this.topBar()
      Blank()
        .hitTestBehavior(HitTestMode.None)
      this.footerBand()
    }
    .width('100%')
    .height('100%')
    .hitTestBehavior(HitTestMode.None)
  }

  // 顶栏：渐变模糊（像主页标题栏）—— 卡片滑到此处被虚化并向下淡出
  @Builder
  topBar() {
    Row() {
      Text(this.title)
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary_strong'))
        .maxLines(1)
    }
    .width('100%')
    .height(this.topZone())
    .alignItems(VerticalAlign.Center)
    .padding({ left: 20, right: 20, bottom: 8 })
    // 顶栏不再铺统一毛玻璃（那只是"不完全的磨砂"）：改由列表自身的端点渐变模糊承担，
    // 这里只保留一层很淡的玻璃色渐变，保证标题在内容之上仍清晰可读
    .linearGradient({
      angle: 180,
      colors: [[$r('app.color.card_glass'), 0], [Color.Transparent, 1]]
    })
  }

  // 按钮条：上缘全透明（卡片从按钮上方穿过时被虚化淡出），到按钮处只剩一层极淡玻璃色
  @Builder
  footerBand() {
    Column() {
      this.footer()
    }
    .width('100%')
    .height(this.footerHeight())
    .justifyContent(FlexAlign.End)
    // 同顶栏：不铺统一毛玻璃，只留很淡的玻璃色渐变（端点模糊由列表的 linearGradientBlur 给）
    .linearGradient({
      angle: 180,
      colors: [[Color.Transparent, 0], [$r('app.color.card_glass'), 1]]
    })
  }

  // 面板底部按钮的沉浸材质：Button 属官方"其他组件"（内容区/面板内都不在生效域，实测会打印
  // Material inactive），故与聊天页状态条同一路径 —— 用 Toggle(ToggleType.Button)
  // （官方口径"效果与 Button 组件设置沉浸光感相同"，且在"全页面生效"豁免名单内）。
  private actionMaterial(): uiMaterial.ImmersiveMaterial {
    return new uiMaterial.ImmersiveMaterial({
      style: uiMaterial.ImmersiveStyle.THIN,
      interactive: true,
      lightEffect: {}
    });
  }

  // 主题色玻璃：把主题色按低 alpha 作为 materialColor 掺进材质层（不透明色会遮掉材质滤镜，
  // 故必须半透明）——「加一点点主题色但不丢失沉浸光感」。
  private accentGlass(): ResourceColor {
    const a: ResourceColor = accentColor(this.dark);
    if (typeof a === 'string' && a.length === 7) {
      return `#4D${(a as string).substring(1)}`;
    }
    return a;
  }

  private confirmMaterial(): uiMaterial.ImmersiveMaterial {
    return new uiMaterial.ImmersiveMaterial({
      style: uiMaterial.ImmersiveStyle.THIN,
      interactive: true,
      lightEffect: {},
      materialColor: this.accentGlass()
    });
  }

  @Builder
  footer() {
    // 按钮条只做渐变模糊：上缘全透明（卡片从按钮上方穿过时被虚化淡出），
    // 到按钮处仅一层极淡玻璃色 —— 不再是一坨实底遮挡列表。
    Column() {
      if (this.confirmPick) {
        Toggle({ type: ToggleType.Button, isOn: false }) {
          Text($r('app.string.common_confirm'))
            .fontSize(UiTokens.fsBody)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.pickedSet
              ? $r('app.color.text_primary_strong') : $r('app.color.text_tertiary'))
        }
        .width('100%')
        .height(46)
        .backgroundColor(Color.Transparent)
        .systemMaterial(this.confirmMaterial())
        .enabled(this.pickedSet)
        .onChange((isOn: boolean): void => {
          if (isOn) {
            this.onConfirm(this.picked);
            this.onClose();
          }
        })
      } else {
        Toggle({ type: ToggleType.Button, isOn: false }) {
          Text($r('app.string.common_cancel'))
            .fontSize(UiTokens.fsBody)
            .fontColor($r('app.color.text_primary_strong'))
        }
        .width('100%')
        .height(46)
        .backgroundColor(Color.Transparent)
        .systemMaterial(this.actionMaterial())
        .onChange((isOn: boolean): void => {
          if (isOn) {
            this.onClose();
          }
        })
      }
    }
    .width('100%')
    .padding({ left: 20, right: 20, bottom: this.navInset + 12 })
  }
}
