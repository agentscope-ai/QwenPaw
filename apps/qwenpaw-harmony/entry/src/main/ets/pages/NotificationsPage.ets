/*
 * 通知设置 —— 对齐 7378 app/notifications.tsx（本地偏好页，不是消息流）：
 * hero「离开 App 也不错过任务」+ 主开关 + 4 个分类开关（任务完成 / 需要输入 / 需要审批 / 任务失败）
 * + 通知预览档（完整内容 / 仅标题 / 不显示内容）。偏好按「连接 + 智能体」本地保存。
 * 真推送通道（Push Kit / AGC）属宿主侧范畴，本页只做偏好与观感适配。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { areaWidthOf, wideClampW } from '../theme/Breakpoints';
import { uiMaterial } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import {
  NotificationPrefs, PREVIEW_FULL, PREVIEW_TITLE_ONLY, PREVIEW_HIDDEN,
  loadNotificationPrefs, saveNotificationPrefs
} from '../services/NotificationPrefs';
import { OptionsSheet, SheetOption, optionOf } from '../components/OptionsSheet';
import { requestNotificationPermission } from '../services/NotifyService';
import { SheetGate, moduleSheetOptions } from '../components/SheetGate';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { popSelfOnBack, slideCoverTransition } from '../services/NavPush';
import { t } from '../services/I18n';

@Builder
export function NotificationsPageBuilder(_name: string, param: Object) {
  NotificationsPage({ params: param })
}

@Component
export struct NotificationsPage {
  params: Object = new Object();
  @State notifyOn: boolean = false;
  @State runCompleted: boolean = true;
  @State inputRequired: boolean = true;
  @State approvalRequired: boolean = true;
  @State runFailed: boolean = true;
  @State preview: string = PREVIEW_TITLE_ONLY;
  @State loading: boolean = true;
  @State error: string = '';
  @State sheetShown: boolean = false;
  @StorageLink('appIsDark') isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  private conn: QpConnection | null = null;
  private gate: SheetGate = new SheetGate();
  private themeListener: ThemeListener | null = null;

  // 大屏（平板/电脑）内容列限宽：官方《页面布局场景》缩进布局 —— 空间充足时内容列居中、两侧留白；
  // 宽度由外层满宽容器 onAreaChange 实时上报（跟随窗口缩放），实现见 theme/Breakpoints
  @State pageW: number = 0;

  private onPageArea = (_old: Area, now: Area): void => {
    this.pageW = areaWidthOf(now, this.pageW);
  };

  // 导航栈（onReady 时由框架注入）：标题栏返回按钮与系统侧滑都走它出栈
  private stack: NavPathStack | null = null;
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';
  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.themeListener = (snap: ThemeSnapshot): void => {
      this.theme = snap;
    };
    ThemeManager.get().subscribe(this.themeListener);
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
    });
    loadConnection(ctx).then((conn: QpConnection | null): void => {
      if (conn === null) {
        this.error = t($r('app.string.pawapp_no_connection'));
        this.loading = false;
        return;
      }
      this.conn = conn;
      loadNotificationPrefs(ctx, conn).then((p: NotificationPrefs): void => {
        this.notifyOn = p.enabled;
        this.runCompleted = p.runCompleted;
        this.inputRequired = p.inputRequired;
        this.approvalRequired = p.approvalRequired;
        this.runFailed = p.runFailed;
        this.preview = p.preview;
        this.loading = false;
      });
    });
  }

  aboutToDisappear(): void {
    if (this.themeListener !== null) {
      ThemeManager.get().unsubscribe(this.themeListener);
      this.themeListener = null;
    }
  }

  private accent(): string {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  // 打开主开关时同时申请系统通知授权（官方 requestEnableNotification：首次弹窗、之后直接返回；
  // 用户拒绝也不阻断本地偏好保存 —— 发布时若系统开关关闭则不会出现通知）
  private async enableSystemNotifications(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    await requestNotificationPermission(ctx);
  }

  // 每次改动即时落盘（7378 同款）
  private save(): void {
    const conn: QpConnection | null = this.conn;
    if (conn === null) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const p: NotificationPrefs = {
      enabled: this.notifyOn,
      runCompleted: this.runCompleted,
      inputRequired: this.inputRequired,
      approvalRequired: this.approvalRequired,
      runFailed: this.runFailed,
      preview: this.preview
    };
    saveNotificationPrefs(ctx, conn, p).catch((): void => {
    });
  }

  private previewLabel(): Resource {
    if (this.preview === PREVIEW_FULL) {
      return $r('app.string.notify_preview_full');
    }
    if (this.preview === PREVIEW_HIDDEN) {
      return $r('app.string.notify_preview_hidden');
    }
    return $r('app.string.notify_preview_title');
  }

  private previewOptions(): SheetOption[] {
    return [
      optionOf(PREVIEW_FULL, t($r('app.string.notify_preview_full'))),
      optionOf(PREVIEW_TITLE_ONLY, t($r('app.string.notify_preview_title'))),
      optionOf(PREVIEW_HIDDEN, t($r('app.string.notify_preview_hidden')))
    ];
  }

  // 开关行（沉浸材质：Toggle 属官方"全页面生效"清单）。
  // disabled 走闭包：@Builder 简单值参数按值传递、总开关翻转后子行禁用态不刷新
  // （官方构建函数参数传递口径）；value 仅作 Toggle 初值（Toggle 自身状态管理后续翻转）
  @Builder
  switchRow(label: Resource, value: boolean, isDisabled: () => boolean, apply: (v: boolean) => void) {
    Row() {
      Text(label)
        .fontSize(UiTokens.fsBody)
        .fontColor(isDisabled() ? $r('app.color.text_tertiary') : $r('app.color.text_primary_strong'))
        .layoutWeight(1)
      Toggle({ type: ToggleType.Switch, isOn: value })
        .enabled(!isDisabled())
        .systemMaterial(new uiMaterial.ImmersiveMaterial({
          style: uiMaterial.ImmersiveStyle.THIN,
          interactive: true,
          lightEffect: {}
        }))
        .onChange((isOn: boolean): void => {
          apply(isOn);
        })
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .margin({ bottom: 8 })
  }

  build() {
    HdsNavDestination() {
      Row() {
        Scroll() {
          Column() {
            Text($r('app.string.notify_hero_title'))
              .fontSize(20)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary_strong'))
              .width('100%')
              .margin({ top: 12 })
            Text($r('app.string.notify_hero_sub'))
              .fontSize(UiTokens.fsSecondary)
              .fontColor($r('app.color.text_tertiary'))
              .width('100%')
              .margin({ top: 6, bottom: 16 })

            if (this.error.length > 0) {
              Text(this.error)
                .fontSize(UiTokens.fsBody)
                .fontColor($r('app.color.status_error'))
                .width('100%')
            } else if (!this.loading) {
              this.switchRow($r('app.string.notify_master'), this.notifyOn, (): boolean => {
                return false;
              }, (v: boolean): void => {
                this.notifyOn = v;
                this.save();
                if (v) {
                  // 打开主开关 → 顺手请求系统通知授权（首次弹窗）
                  this.enableSystemNotifications();
                }
              })
              this.switchRow($r('app.string.notify_run_completed'), this.runCompleted, (): boolean => {
                return !this.notifyOn;
              }, (v: boolean): void => {
                this.runCompleted = v;
                this.save();
              })
              this.switchRow($r('app.string.notify_input_required'), this.inputRequired, (): boolean => {
                return !this.notifyOn;
              }, (v: boolean): void => {
                this.inputRequired = v;
                this.save();
              })
              this.switchRow($r('app.string.notify_approval_required'), this.approvalRequired, (): boolean => {
                return !this.notifyOn;
              }, (v: boolean): void => {
                this.approvalRequired = v;
                this.save();
              })
              this.switchRow($r('app.string.notify_run_failed'), this.runFailed, (): boolean => {
                return !this.notifyOn;
              }, (v: boolean): void => {
                this.runFailed = v;
                this.save();
              })

              Row() {
                Text($r('app.string.notify_preview'))
                  .fontSize(UiTokens.fsBody)
                  .fontColor(this.notifyOn
                    ? $r('app.color.text_primary_strong') : $r('app.color.text_tertiary'))
                  .layoutWeight(1)
                Text(this.previewLabel())
                  .fontSize(UiTokens.fsSecondary)
                  .fontColor($r('app.color.text_tertiary'))
                Image($r('app.media.chevron_right'))
                  .width(16).height(16)
                  .fillColor($r('app.color.text_tertiary'))
                  .margin({ left: 6 })
              }
              .width('100%')
              .padding(UiTokens.cardPad)
              .borderRadius(UiTokens.cardRadius)
              .backgroundColor($r('app.color.card_glass'))
              .onClick((): void => {
                if (!this.notifyOn) {
                  return;
                }
                if (this.gate.request()) {
                  this.sheetShown = true;
                }
              })

              Text($r('app.string.notify_scope'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .width('100%')
                .margin({ top: 14 })
              Text($r('app.string.notify_privacy'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .width('100%')
                .margin({ top: 6, bottom: 24 })
            }
          }
          .width('100%')
          .padding({ top: UiTokens.topInset, left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
          .alignItems(HorizontalAlign.Start)
        }
        .width(wideClampW(this.pageW))
        .height('100%')
        .scrollBar(BarState.Off)
        .bindSheet(this.sheetShown, this.sheet(), moduleSheetOptions(360, this.gate,
          (v: boolean): void => {
            this.sheetShown = v;
          }))
      }
      .width('100%')
      .height('100%')
      .justifyContent(FlexAlign.Center)
      .onAreaChange(this.onPageArea)
    }
    // 内容也扩到安全区外（布局级，与 expandSafeArea 同设时优先）：二级页四边都扩，
    // 否则下端/左右两侧会露出窗口底色（页面底部输入条一带表现为黑带）
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM],
      [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM, LayoutSafeAreaEdge.START, LayoutSafeAreaEdge.END])
    // 二级页转场：整页自右水平覆盖进来（退出滑回右侧）——见 services/NavPush.slideCoverTransition。
    // 系统默认档在分栏下动的是"内容区左边缘 0 → 分栏位"，观感从左侧摊过来（判"方向反了"），
    // 故改用官方 customTransition（NavDestinationTransitionDelegate）自己定方向。
    .customTransition((op: NavigationOperation, isEnter: boolean)
      : Array<NavDestinationTransition> | undefined => slideCoverTransition(op, isEnter,
        (v: string): void => { this.pageX = v; }))
    .translate({ x: this.pageX })
    // 本页未从入栈参数带 NavPathStack：按官方口径在 onReady 取导航栈（NavDestinationContext.pathStack）
    .onReady((ctx: NavDestinationContext): void => {
      this.stack = ctx.pathStack;
    })
    // 返回键：系统侧滑与标题栏左上角返回按钮都投递到当前 NavDestination 的 onBackPressed
    //（官方 FAQ faqs-arkui-1117：该回调"支持拦截系统侧滑及 NavDestination 标题栏的返回事件"）；
    // 没挂它时标题栏返回按钮点了没有反应 —— 这里自己出栈并消费。
    .onBackPressed((): boolean => popSelfOnBack(this.stack))
    .titleBar({
      style: {
        scrollEffectOpts: {
          // enableScrollEffect = false：官方口径「不随内容区滚动动态生效标题栏样式，仅生效 originalStyle」，
          // 且 GRADIENT_BLUR 下「直接生效模糊。此方式适用于列表型非沉浸式场景」。
          // 为什么不用 true：为 true 时样式会在 originalStyle→scrollEffectStyle 之间随滚动**插值**，
          // 上滚过程出现"先变暗、再慢慢回到主题色"的过渡观感（反复被报的"往上滑突然变黑然后慢慢
          // 出现主题色"）；关掉后底色/模糊只有一个状态，结构上不可能再出现滚动时变色。
          // 标题栏随滚动收起（titleMode FREE）与内容穿过时的模糊都不受影响。
          enableScrollEffect: false,
          scrollEffectType: ScrollEffectType.GRADIENT_BLUR
        },
        // blurStrategy 用 ENABLE 而不是 ADAPTIVE：官方口径 ADAPTIVE「根据系统策略调整…只有精美档位
        // 配置能够生效模糊效果」—— 系统策略落在轻柔/流畅档时标题栏模糊整块不生效，内容滚过时就露出
        // 未模糊的暗色内容（观感即"往上滑突然变黑"）；ENABLE 恒生效，观感才稳定。
        blurStrategy: BlurStrategy.ENABLE,
        originalStyle: {
          backgroundStyle: {
            blurRadius: 12.0,
            // 蒙层外扩必须写在**生效态**里：enableScrollEffect=false 时只生效 originalStyle，
            // 写在 scrollEffectStyle 里会被忽略、退回平台默认外扩（真机实测蒙层 822 → 标题栏底边
            // 710 之下多出 112px≈56vp），那段在工具条正下方留下一条中性灰带（浅色模式即"接缝"）；
            // 归零后蒙层与标题栏同底（710），渐隐在标题栏内完成，内容区不再被蒙层压到。
            maskExtraHeight: 0.0,
            backgroundColor: this.accent()
          }
        },
        scrollEffectStyle: {
          backgroundStyle: {
            blurRadius: 12.0,
            backgroundColor: this.accent()
          }
        },
        systemMaterialEffect: {
          materialType: hdsMaterial.MaterialType.ADAPTIVE,
          materialLevel: hdsMaterial.MaterialLevel.ADAPTIVE
        }
      },
      content: {
        title: {
          mainTitle: $r('app.string.notify_title')
        }
      },
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
    .backgroundColor($r('app.color.page_bg'))
    .expandSafeArea([SafeAreaType.SYSTEM],
      [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
  }

  @Builder
  sheet() {
    OptionsSheet({
      title: t($r('app.string.notify_preview')),
      options: this.previewOptions(),
      current: this.preview,
      onPick: (v: string): void => {
        this.preview = v;
        this.save();
      },
      onClose: (): void => {
        this.gate.beginClose();
        this.sheetShown = false;
      }
    })
  }
}
