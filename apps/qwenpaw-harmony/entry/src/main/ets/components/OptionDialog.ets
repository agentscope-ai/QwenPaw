/*
 * 单选紧凑弹窗 —— 聊天页「模型 / 循环 / 审批」三个运行控制面板的统一出口。
 *
 * 设计口径（CustomDialogController 官方规格，API 26）：
 * - systemMaterial：沉浸材质，默认 ULTRA_THICK；开启后弹窗自身 backgroundColor 等背景属性
 *   全部不生效（材质层自带背景）→ 根节点不铺底色，避免与材质层出现色差接缝；
 * - customStyle(false) + width：宽度按栅格自适应、高度随内容（紧凑小弹窗而非通栏面板）；
 * - builder 参数不支持动态刷新 → 宿主每次打开新建 controller 并传入参数快照
 *   （见 SessionRuntimeBar.openDialog），故本组件入参以普通属性为主（构造时快照语义）；
 *   思考节 8 个快照字段是 @State：初值仍是打开瞬间的快照，但点选模型行后
 *   需要就地重排整节（思考视图实时跟随所选模型，不等点确定）；
 * - 框架注入的 controller 成员属性（属性名固定为 controller）：注入成功后 close() 直接关。
 *
 * 两种形态：
 * - 选项分支：标题 + 副标题 + 选项列表（图标 + 名称 + 描述 + 勾选）+ 取消/确定；
 * - 只读提示分支：循环非 idle 时只出一张只读卡（模式图标 + 模式名与状态词 + 提示），
 *   无选项无按钮（服务端无「结束循环」接口，对齐 console 的 disabled 语义；点遮罩关闭）。
 *
 * 思考强度节（仅模型面板传 thinkKind，其余面板为空隐藏）：对齐 console ThinkingControl——
 * effort 型 = 离散档位滑块（supports_off 时 off 前置为首档）；budget 型 = 连续 token 滑块
 * （supports_off 时配「关闭思考」芯片）；unsupported/unknown 型 = 只读提示行；
 * 恢复默认 = 回落默认（inherit）。节内选择只落本地 @State，确定时经
 * onConfirm 第二个参数（ThinkingPick）交宿主统一写服务端。
 * 实时跟随：宿主对模型面板传入 thinkingFetcher 时，点选某模型行立即取该模型的
 * thinking-default 视图重排本节（加载中头部转圈），不等点确定。
 *
 * 思考滑块（官方 Slider 参考、《组件适配沉浸光感》与真机像素实测口径）：
 * - 传入材质参数即激活系统材质（参数仅开关标记，滑块观感用组件内部预设），
 *   且「设置系统材质后，Slider 滑动过程中会产生粒子动画效果」= 原生粒子效果；
 * - 光感交互反馈仅在滑块形状 SliderBlockType.DEFAULT 且 SliderStyle 非 NONE 时生效；
 * - 材质渲染区域 = 组件布局区域（官方 FAQ「材质渲染区域与组件可视区域不一致」：
 *   用 width/height/borderRadius 控制两者一致）→ 盒体不能限高加胶囊圆角：
 *   盒太小，粒子/光感在盒缘被裁切（即「光感超出组件被裁」）；盒高 44 给粒子/光感
 *   留舒展空间，盒体左右以负 margin 外扩，两端光感不在卡缘被裁；
 * - 轨粗比例是官方样式规则：trackThickness:blockSize 默认 OutSet 1:4 / InSet 5:3，
 *   且「blockSize 跟随 trackThickness 同比例增减」——真机实测 OutSet 下轨恒按块
 *   的 1/4 派生（两块都显式 18 仍得 4.5vp 细轨，条点大小失衡）；故用 InSet 并
 *   显式 18:18 使滑轨与圆点同径（1:1），白块浮于选段之上；
 * - 材质不开 interactive（交互形变）→ 圆点按压不放大。
 *
 * 行卡片 / 按压反馈 / 底部按钮与 OptionsSheet 同一配方：内容区沉浸材质不生效，
 * 行用自绘按压（pressEffect + pressTouch），按钮用 Toggle(ToggleType.Button) 材质外壳。
 *
 * 按钮边框：本应用 MaterialState 为 enable（module.json5 metadata），官方口径此模式下
 * 材质样式优先级高于组件自身设置的背景/模糊/阴影/边框样式（@ohos.arkui.uiMaterial
 * MaterialState 枚举说明）→ 边框不能挂在材质组件上，改在与按钮同几何（高 44 / 圆角 22）
 * 的独立顶层描边环呈现，hitTestBehavior(None) 让触摸穿透给材质按钮。
 */

import { uiMaterial } from '@kit.ArkUI';
import { UiTokens } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { accentColor } from '../theme/Accent';
import { parseThinkingView, ThinkingSnapshot } from './ThinkingView';
import { t } from '../services/I18n';

export class DialogOption {
  value: string = '';
  label: string = '';
  detail: string = '';
  icon: Resource | null = null;
}

export function dialogOptionOf(value: string, label: string, detail: string, icon: Resource | null): DialogOption {
  const o: DialogOption = new DialogOption();
  o.value = value;
  o.label = label;
  o.detail = detail;
  o.icon = icon;
  return o;
}

// 思考强度选择结果（模型面板确定时回传；无思考节的面板回传 changed=false 的空选择）：
// level '' = 回落默认（inherit）；level 'budget' 时 budgetTokens 生效（服务端要求成对）
export interface ThinkingPick {
  level: string;
  budgetTokens: number;
  changed: boolean;
}

// 弹窗沉浸材质统一出口（THICK + interactive）：弹窗属官方「弹窗类组件」生效域，
// 材质直接可用；等级与聊天页状态条/OptionsSheet 底部按钮同一档，观感一致。
export function optionDialogMaterial(): uiMaterial.ImmersiveMaterial {
  return new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.THICK,
    interactive: true,
    lightEffect: {}
  });
}

// 思考滑块几何：圆点直径 = 滑轨厚度（1:1）；盒高给原生粒子/光感留舒展空间
//（材质渲染区域 = 组件布局区域，盒太小光感在盒缘被裁）；盒体左右外扩量
const THINK_SLIDER_SIZE: number = 18;
const THINK_SLIDER_H: number = 44;
const THINK_SLIDER_SIDE_SLACK: number = 12;

// 思考滑块材质（口径均出自 uiMaterial/Slider 官方文档）：
// - style 取 REGULAR（档位表：ULTRA_THIN/THIN 用于「悬浮按钮和轻量提示」，
//   粒子偏淡；实测方形外框来自 lightEffect 白色光感盘而非厚档，故在
//   lightEffect:null 前提下取 REGULAR 拿更强的滑动粒子/高光）
// - lightEffect 显式传 null = 禁用光感交互反馈（不传=undefined 走 Slider
//   组件默认交互光感：按压亮、松手瞬断无动画；null 后圆点无额外光感）
// - 不传 interactive → 圆点按压不放大
// - 设置系统材质后 Slider 滑动过程中自带粒子动画（原生粒子效果）
function thinkSliderMaterial(): uiMaterial.ImmersiveMaterial {
  return new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.REGULAR,
    lightEffect: null
  });
}

@CustomDialog
export struct OptionDialog {
  // 框架注入的 CustomDialogController（@CustomDialog 必须含此属性，属性名固定 controller）：
  // 注入成功时 doClose() 直接 close()；万一注入失败则回落宿主回调
  controller?: CustomDialogController;
  // 以下均为构造时快照（builder 参数不支持动态刷新，宿主每次打开新建 controller）
  title: string = '';
  subtitle: string = '';
  options: DialogOption[] = [];
  // 当前选中值（空串合法：审批「跟随 Agent」就是空值选项）
  current: string = '';
  // 只读提示分支（循环非 idle）
  noticeTitle: string = '';
  noticeSub: string = '';
  noticeIcon: Resource | null = null;
  // 思考强度节快照（模型面板才有；宿主打开前从 GET /chats/{id}/thinking 解析，见 openModel）。
  // @State：点选模型行后就地重排整节（实时跟随所选模型），初值 = 打开瞬间快照。
  // thinkKind: ''=不显示 | effort=离散档位 | budget=token 预算 | unsupported / unknown=只读提示
  @State thinkKind: string = '';
  @State thinkStops: string[] = [];          // effort 档位序列（supports_off 时 'off' 已前置为首档）
  @State thinkSupportsOff: boolean = false;  // budget 型用：是否配「关闭思考」芯片
  @State thinkBudgetMin: number = 1;
  @State thinkBudgetMax: number = 1;
  @State thinkLevel: string = '';            // 当前生效档位（'' = 默认 inherit；budget 型可能是 'budget'/'off'）
  @State thinkBudgetTokens: number = 0;      // 当前生效 token 值（budget 型滑块初值）
  @State thinkCanReset: boolean = false;     // 会话偏好非 inherit 或会话模型覆盖在用时可恢复默认
  // 思考节当前归属的模型（'provider||model'）：点行时按它判是否重复点同一行
  thinkForModel: string = '';
  // 实时跟随入口：模型面板由宿主传入（model → thinking-default 端点）；其余面板不传
  thinkingFetcher: ((model: string) => Promise<Record<string, Object> | null>) | null = null;
  @State thinkLoading: boolean = false;
  // 思考视图取数代次：连点模型行时防乱序写回
  private thinkFetchGen: number = 0;
  onConfirm: (value: string, thinking: ThinkingPick) => void =
    (v: string, t: ThinkingPick): void => {};
  onCancel: () => void = (): void => {};
  @State picked: string = '';
  // 「确定」可用性不能用 picked.length>0 判 —— 空值选项（跟随 Agent）会永远禁用（OptionsSheet 同坑）
  @State pickedSet: boolean = false;
  @State pressed: number = -1;
  // 思考节本地选择（确定前不落服务端）：level '' = 默认；budget 值随滑块
  @State thinkSel: string = '';
  @State thinkBudget: number = 0;
  // 滑块当前值（effort = 档位索引 / budget = token 数），拖动中同步、松手才提交选择
  @State thinkSlider: number = 0;
  // 思考节是否被碰过（没碰过、模型也没选时「确定」保持禁用）
  @State thinkTouched: boolean = false;
  // 思考滑块拖动中（指示值实时跟随，console onPreview 口径；松手/点轨道才提交选择）
  @State thinkDragging: boolean = false;
  private latch: PressLatch = new PressLatch();
  @StorageLink('appIsDark') dark: boolean = false;

  aboutToAppear(): void {
    this.picked = this.current;
    this.pickedSet = false;
    // 思考节初值 = 打开瞬间的生效值（console 口径：displayed = value，inherit 时回退 effective）
    this.thinkSel = this.thinkLevel;
    this.thinkBudget = this.thinkBudgetTokens;
    if (this.thinkKind === 'effort') {
      // 生效值不在档位序列（如 inherit）时落首档，console 同款 Math.max(0, indexOf)
      let idx: number = this.thinkStops.indexOf(this.thinkSel);
      if (idx < 0) {
        idx = 0;
      }
      this.thinkSlider = idx;
    } else if (this.thinkKind === 'budget') {
      this.thinkSlider = this.thinkBudgetTokens;
    }
  }

  aboutToDisappear(): void {
    // 弹窗销毁：作废在途的思考视图取数（then 里代次不符直接丢弃，不写状态）
    this.thinkFetchGen += 1;
  }

  private isPicked(value: string): boolean {
    return this.picked === value;
  }

  // 关弹窗：controller 注入成功则直接 close()（宿主 onWillDismiss 清引用）；
  // 注入失败时回落 onCancel（宿主同样清引用），保证不会关不掉
  private doClose(): void {
    if (this.controller !== undefined) {
      this.controller.close();
    } else {
      this.onCancel();
    }
  }

  // 档位名（对齐 console thinkingControl.* 的中文口径）；未知值原样透出
  private levelLabelOf(level: string): string {
    if (level === '') {
      return t($r('app.string.chat_thinking_default'));
    }
    if (level === 'off') {
      return t($r('app.string.chat_thinking_off'));
    }
    if (level === 'minimal') {
      return t($r('app.string.chat_thinking_minimal'));
    }
    if (level === 'low') {
      return t($r('app.string.chat_thinking_low'));
    }
    if (level === 'medium') {
      return t($r('app.string.chat_thinking_medium'));
    }
    if (level === 'high') {
      return t($r('app.string.chat_thinking_high'));
    }
    if (level === 'xhigh') {
      return t($r('app.string.chat_thinking_xhigh'));
    }
    if (level === 'max') {
      return t($r('app.string.chat_thinking_max'));
    }
    return level;
  }

  // 节头部当前值标签 —— 拖动中实时显示滑块位置（console onPreview 口径），非拖动显示已提交值：
  // budget 型 = 紧凑 token 数（"81.9K tokens"）/ off 芯片选中显示关闭 / 未提交显示默认；
  // effort 型 = 档位名
  private thinkStatusLabel(): string {
    if (this.thinkKind === 'budget') {
      if (this.thinkSel === 'off' && !this.thinkDragging) {
        return t($r('app.string.chat_thinking_off'));
      }
      if (this.thinkDragging || this.thinkSel === 'budget') {
        return `${this.compactTokens(this.thinkSlider)} tokens`;
      }
      return t($r('app.string.chat_thinking_default'));
    }
    if (this.thinkDragging && this.thinkSlider >= 0 && this.thinkSlider < this.thinkStops.length) {
      return this.levelLabelOf(this.thinkStops[this.thinkSlider]);
    }
    return this.levelLabelOf(this.thinkSel);
  }

  // 紧凑 token 数（console NumberFlow compact 口径：81920 → "81.9K"，1000 → "1K"）
  private compactTokens(v: number): string {
    if (v >= 1000) {
      let s: string = (v / 1000).toFixed(1);
      if (s.endsWith('.0')) {
        s = s.substring(0, s.length - 2);
      }
      return `${s}K`;
    }
    return `${v}`;
  }

  // 确定时回传的选择：与打开瞬间的生效值相比，档位或 budget 值变了才算 changed
  private buildThinkPick(): ThinkingPick {
    let changed: boolean = this.thinkSel !== this.thinkLevel;
    if (!changed && this.thinkKind === 'budget' && this.thinkSel === 'budget'
      && this.thinkBudget !== this.thinkBudgetTokens) {
      changed = true;
    }
    return {
      level: this.thinkSel,
      budgetTokens: this.thinkBudget,
      changed: changed
    };
  }

  @Builder
  dialogOptionRow(o: DialogOption, idx: number) {
    Row() {
      if (o.icon !== null) {
        Image(o.icon)
          .width(18).height(18)
          .fillColor($r('app.color.text_secondary'))
          .margin({ right: 10 })
      } else {
        Column().width(18).height(18).margin({ right: 10 })
      }
      Column() {
        Text(o.label)
          .fontSize(UiTokens.fsBody)
          .fontWeight(this.isPicked(o.value) ? FontWeight.Medium : FontWeight.Normal)
          .fontColor($r('app.color.text_primary_strong'))
        if (o.detail.length > 0) {
          Text(o.detail)
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_secondary'))
            .maxLines(2)
            .margin({ top: 2 })
        }
      }
      .alignItems(HorizontalAlign.Start)
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
      this.picked = o.value;
      this.pickedSet = true;
      // 思考视图实时跟随：点中的模型行与当前思考节归属不同 → 立即取新模型视图重排本节
      if (this.thinkingFetcher !== null && o.value !== this.thinkForModel) {
        this.refreshThinkingFor(o.value);
      }
    })
  }

  // 点选模型行后取该模型的思考视图（thinking-default 端点，宿主经 thinkingFetcher 提供）：
  // 代次守卫防连点乱序；结果 null（无思考控制）→ 整节清除
  private refreshThinkingFor(model: string): void {
    const fetcher: ((m: string) => Promise<Record<string, Object> | null>) | null = this.thinkingFetcher;
    if (fetcher === null) {
      return;
    }
    const gen: number = ++this.thinkFetchGen;
    this.thinkLoading = true;
    fetcher(model).then((view: Record<string, Object> | null): void => {
      if (gen !== this.thinkFetchGen) {
        return;
      }
      this.thinkLoading = false;
      this.applyThinkingSnapshot(view, model);
    }).catch((): void => {
      if (gen === this.thinkFetchGen) {
        this.thinkLoading = false;
      }
    });
  }

  // 思考视图落地到弹窗：写快照 + 重置本地选择到新模型生效值（没碰过，确定不写库）
  private applyThinkingSnapshot(view: Record<string, Object> | null, model: string): void {
    const snap: ThinkingSnapshot | null = parseThinkingView(view);
    if (snap === null) {
      this.clearThinkingSection();
      this.thinkForModel = model;
      return;
    }
    this.thinkKind = snap.kind;
    this.thinkStops = snap.stops;
    this.thinkSupportsOff = snap.supportsOff;
    this.thinkBudgetMin = snap.budgetMin;
    this.thinkBudgetMax = snap.budgetMax;
    this.thinkLevel = snap.level;
    this.thinkBudgetTokens = snap.budgetTokens;
    this.thinkCanReset = snap.canReset;
    this.thinkSel = snap.level;
    this.thinkBudget = snap.budgetTokens;
    if (snap.kind === 'effort') {
      let idx: number = snap.stops.indexOf(snap.level);
      if (idx < 0) {
        idx = 0;
      }
      this.thinkSlider = idx;
    } else if (snap.kind === 'budget') {
      this.thinkSlider = snap.budgetTokens;
    } else {
      this.thinkSlider = 0;
    }
    this.thinkTouched = false;
    this.thinkDragging = false;
    this.thinkForModel = model;
  }

  // 无思考控制（视图缺失/解析不出）→ 思考节整体隐藏并复位
  private clearThinkingSection(): void {
    this.thinkKind = '';
    this.thinkStops = [];
    this.thinkSupportsOff = false;
    this.thinkBudgetMin = 1;
    this.thinkBudgetMax = 1;
    this.thinkLevel = '';
    this.thinkBudgetTokens = 0;
    this.thinkCanReset = false;
    this.thinkSel = '';
    this.thinkBudget = 0;
    this.thinkSlider = 0;
    this.thinkTouched = false;
    this.thinkDragging = false;
  }

  // 「确定」可用性：选过选项或碰过思考节即可提交（取消恒可用）。
  // 动态启用态不能走 builder 参数传递 —— @Builder 默认按值传递，多参数时状态变化
  // 不刷新 builder 内 UI（官方构建函数参数传递口径）；改为体内经 this 直读状态
  // （与 dialogOptionRow 体内读 this.pressed 同一模式），isConfirm 是构造常量可安全传参。
  private actionButtonEnabled(isConfirm: boolean): boolean {
    return isConfirm ? (this.pickedSet || this.thinkTouched) : true;
  }

  // 底部操作按钮（取消/确定统一出口）：材质按钮 + 同几何顶层描边环。
  // 描边环必须独立成层：enable 模式下边框挂材质组件上被材质优先级覆盖不渲染。
  @Builder
  dialogActionButton(label: Resource, strong: boolean, isConfirm: boolean, onFire: () => void) {
    Stack() {
      Toggle({ type: ToggleType.Button, isOn: false }) {
        Text(label)
          .fontSize(UiTokens.fsBody)
          .fontWeight(strong ? FontWeight.Medium : FontWeight.Normal)
          .fontColor(this.actionButtonEnabled(isConfirm)
            ? $r('app.color.text_primary_strong') : $r('app.color.text_tertiary'))
      }
      .width('100%')
      .height(44)
      .borderRadius(22)
      .backgroundColor(Color.Transparent)
      .systemMaterial(optionDialogMaterial())
      .enabled(this.actionButtonEnabled(isConfirm))
      .onChange((isOn: boolean): void => {
        if (isOn) {
          onFire();
        }
      })
      Row()
        .width('100%')
        .height(44)
        .borderRadius(22)
        .border({ width: 1, color: $r('app.color.line') })
        .hitTestBehavior(HitTestMode.None)
    }
    .layoutWeight(1)
  }

  @Builder
  noticeCard() {
    Row() {
      if (this.noticeIcon !== null) {
        Image(this.noticeIcon)
          .width(18).height(18)
          .fillColor($r('app.color.text_secondary'))
          .margin({ right: 10 })
      }
      Column() {
        Text(this.noticeTitle)
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.text_primary_strong'))
        if (this.noticeSub.length > 0) {
          Text(this.noticeSub)
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_secondary'))
            .margin({ top: 2 })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .constraintSize({ minHeight: 52 })
    .padding({ left: UiTokens.cardPad, right: UiTokens.cardPad })
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.sheet_card_bg'))
    .margin({ top: 12 })
    .alignItems(VerticalAlign.Center)
  }

  // 思考强度节：头部（标题 + 当前值 + 恢复默认）+ 按 kind 分型的控件。
  // 卡片底色与选项行同 token；交互形变不挂（Slider/芯片是生效域组件，无需自绘按压）
  @Builder
  thinkingSection() {
    Column({ space: 10 }) {
      Row() {
        Text(t($r('app.string.chat_thinking_title')))
          .fontSize(UiTokens.fsCaption)
          .fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.text_secondary'))
        Blank()
        Text(this.thinkStatusLabel())
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_primary_strong'))
        // 实时跟随加载中：点选模型行后新模型视图未回前转圈
        if (this.thinkLoading) {
          LoadingProgress()
            .width(14)
            .height(14)
            .color($r('app.color.text_tertiary'))
            .margin({ left: 8 })
        }
        if (this.thinkCanReset && this.thinkKind !== 'unsupported' && this.thinkKind !== 'unknown') {
          Image($r('app.media.rotate_ccw'))
            .width(14)
            .height(14)
            .fillColor($r('app.color.text_secondary'))
            .margin({ left: 6 })
            .onClick((): void => {
              this.thinkSel = '';
              this.thinkTouched = true;
            })
        }
      }
      .width('100%')
      if (this.thinkKind === 'effort') {
        // 离散档位：每档一个刻度（showSteps 默认 false 须显式开）；松手/点轨道才提交
        // InSet + 显式 18:18 使轨与块同径（1:1，比例规则见文件头口径）；
        // 盒高 44 给原生粒子/光感留舒展空间，盒体左右外扩让两端光感不在卡缘被裁
        Slider({
          value: this.thinkSlider,
          min: 0,
          max: Math.max(1, this.thinkStops.length - 1),
          step: 1,
          style: SliderStyle.InSet
        })
        .showSteps(true)
        .blockSize({ width: THINK_SLIDER_SIZE, height: THINK_SLIDER_SIZE })
        .trackThickness(THINK_SLIDER_SIZE)
        .trackBorderRadius(THINK_SLIDER_SIZE / 2)
        .selectedBorderRadius(THINK_SLIDER_SIZE / 2)
        .selectedColor(accentColor(this.dark))
        .systemMaterial(thinkSliderMaterial())
        .enabled(this.thinkStops.length >= 2)
        .onChange((v: number, mode: SliderChangeMode): void => {
          this.onThinkSliderChange(v, mode, (): void => {
            this.thinkSel = this.thinkStops[this.thinkSlider];
          });
        })
        .width('100%')
        .height(THINK_SLIDER_H)
        .margin({ left: -THINK_SLIDER_SIDE_SLACK, right: -THINK_SLIDER_SIDE_SLACK })
      } else if (this.thinkKind === 'budget') {
        Row({ space: 8 }) {
          // off 不在 token 数值域里 → 独立芯片表达（console 用滑块间隙表达，移动端点按更直接）
          if (this.thinkSupportsOff) {
            Text(t($r('app.string.chat_thinking_off')))
              .fontSize(UiTokens.fsCaption)
              .fontColor(this.thinkSel === 'off'
                ? accentColor(this.dark) : $r('app.color.text_secondary'))
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
              .borderRadius(12)
              .backgroundColor($r('app.color.sheet_card_bg'))
              .border({ width: 1, color: this.thinkSel === 'off'
                ? accentColor(this.dark) : $r('app.color.line') })
              .onClick((): void => {
                this.thinkSel = 'off';
                this.thinkTouched = true;
              })
          }
          // 与 effort 同档几何（InSet + 18:18 轨块同径）；无级 token 调节不画刻度
          Slider({
            value: this.thinkSlider,
            min: this.thinkBudgetMin,
            max: this.thinkBudgetMax,
            step: 1,
            style: SliderStyle.InSet
          })
          .blockSize({ width: THINK_SLIDER_SIZE, height: THINK_SLIDER_SIZE })
          .trackThickness(THINK_SLIDER_SIZE)
          .trackBorderRadius(THINK_SLIDER_SIZE / 2)
          .selectedBorderRadius(THINK_SLIDER_SIZE / 2)
          .selectedColor(accentColor(this.dark))
          .systemMaterial(thinkSliderMaterial())
          .enabled(this.thinkBudgetMax > this.thinkBudgetMin)
          .onChange((v: number, mode: SliderChangeMode): void => {
            this.onThinkSliderChange(v, mode, (): void => {
              this.thinkSel = 'budget';
              this.thinkBudget = Math.round(v);
            });
          })
          .layoutWeight(1)
          .height(THINK_SLIDER_H)
          .margin({ left: -THINK_SLIDER_SIDE_SLACK, right: -THINK_SLIDER_SIDE_SLACK })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
      } else {
        // unsupported / unknown：只读提示（console 为锁图标 + tooltip）
        Row({ space: 8 }) {
          Image($r('app.media.key'))
            .width(14)
            .height(14)
            .fillColor($r('app.color.text_tertiary'))
          Text(this.thinkKind === 'unknown'
            ? t($r('app.string.chat_thinking_unknown'))
            : t($r('app.string.chat_thinking_unsupported')))
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_tertiary'))
            .layoutWeight(1)
        }
        .width('100%')
      }
    }
    .width('100%')
    .padding({ left: UiTokens.cardPad, right: UiTokens.cardPad, top: 10, bottom: 12 })
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.sheet_card_bg'))
    .margin({ top: 4 })
  }

  // 思考滑块统一回调：拖动中指示值实时跟随；
  // 松手（End）/点轨道（Click）提交选择（label 即时更新）；粒子/光感交原生材质
  private onThinkSliderChange(v: number, mode: SliderChangeMode, commit: () => void): void {
    this.thinkSlider = Math.round(v);
    this.thinkDragging = true;
    this.thinkTouched = true;
    if (mode === SliderChangeMode.End || mode === SliderChangeMode.Click) {
      commit();
      this.thinkDragging = false;
    }
  }

  build() {
    Column() {
      Text(this.title)
        .fontSize(UiTokens.fsTitle)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary_strong'))
        .width('100%')
      if (this.subtitle.length > 0) {
        Text(this.subtitle)
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_secondary'))
          .width('100%')
          .margin({ top: 4 })
      }
      if (this.options.length > 0) {
        Scroll() {
          Column() {
            ForEach(this.options, (o: DialogOption, i: number) => {
              this.dialogOptionRow(o, i)
            }, (o: DialogOption) => o.value)
          }
          .width('100%')
        }
        .width('100%')
        .constraintSize({ maxHeight: 360 })
        .align(Alignment.Top)
        .scrollBar(BarState.Off)
        .margin({ top: 12 })

        if (this.thinkKind.length > 0) {
          this.thinkingSection()
        }

        Row({ space: 10 }) {
          this.dialogActionButton($r('app.string.common_cancel'), false, false, (): void => {
            this.doClose();
          })
          // 「确定」在选过模型项或碰过思考节时都可点（只改思考强度不动模型也要能提交）
          this.dialogActionButton($r('app.string.common_confirm'), true, true, (): void => {
            this.onConfirm(this.picked, this.buildThinkPick());
            this.doClose();
          })
        }
        .width('100%')
        .margin({ top: 4 })
      } else {
        this.noticeCard()
      }
    }
    // 根不铺底色：systemMaterial 开启后弹窗自身背景属性不生效，材质层自带背景
    .padding({ left: 16, top: 16, right: 16, bottom: 14 })
  }
}
