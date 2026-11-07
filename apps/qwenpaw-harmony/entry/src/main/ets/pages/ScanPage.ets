/*
 * 扫码配对 —— 移植 PR #7378 app/scan.tsx（同网段扫码直连）：
 *   深色全屏页（安全配对标识 + 取景框 + 状态/错误）→ 扫码 → 解析配对码 → 兑换票据 → 落盘连接 → 回跳。
 *
 * 扫码通道（官方《Scan Kit 默认界面扫码》口径）：
 *   - startScanForResult 提供系统一致的扫码界面（含相册扫码入口），且对系统相机权限做了预授权、
 *     调用期间处于安全访问状态 —— 无需开发者再申请相机权限（旧 startScan 已标注 @useinstead）。
 *   - 因此本页与连接页统一改用 startScanForResult，并移除 module.json5 里的 CAMERA 权限申请。
 *
 * 与 7378 的差异（有意）：7378 用 expo-camera 在页内渲染相机预览流当底图（扫码界面自绘）；
 *   本工程走官方推荐路径 —— 系统默认扫码界面负责取景，本页作为进入前的状态页（取景框可点按重扫，
 *   进页自动拉起一次扫码）。
 *
 * 路由：scan（router_map）。参数 ScanRouteParam.stack 供本页 pop 回跳；
 *   调用方用 pushPathByName 的 onPop 回调接收「配对流程结束」（成功落盘 / 用户放弃）后自行刷新。
 */

import { scanBarcode, scanCore } from '@kit.ScanKit';
import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { BusinessError } from '@kit.BasicServicesKit';
import { saveConnection } from '../services/ConnectionStore';
import { connectToQwenPaw, describeConnectError, ConnectOutcome } from '../services/ConnectionService';
import { parsePairingUri, parseManualInput, DirectPairing } from '../services/PairingModel';
import { ScanRouteParam } from '../services/AppEvents';
import { UiTokens, pxPerVp } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { t } from '../services/I18n';

// 取景框几何（对齐 7378 styles.frame / styles.corner）
const FRAME_H: number = 260;
const CORNER_H: number = 54;
const CORNER_RADIUS: number = 24;
const CORNER_BORDER: number = 4;

// 安全区保底值（vp）：窗口避让区取不到时兜底
const TOP_FALLBACK: number = 48;
const BOTTOM_FALLBACK: number = 24;

// Scan Kit 错误码：用户取消扫码（官方 FAQ《默认界面扫码取消后，如何感知》）
const SCAN_CANCELLED: number = 1000500002;

@Builder
export function ScanPageBuilder(_name: string, param: Object) {
  ScanPage({ params: param })
}

@Component
export struct ScanPage {
  params: Object = new Object();
  // 正在兑换票据（标题显示「正在配对…」）
  @State linking: boolean = false;
  @State error: string = '';
  @State topInset: number = TOP_FALLBACK;
  @State bottomInset: number = BOTTOM_FALLBACK;
  @State pressed: number = -1;
  private stack: NavPathStack | null = null;
  private latch: PressLatch = new PressLatch();
  // 系统扫码界面是否已拉起（防止重复拉起）
  private scanning: boolean = false;
  private autoStarted: boolean = false;

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const st: Object = rec['stack'];
    this.stack = (st === undefined || st === null) ? null : st as NavPathStack;
    this.applyInsets();
  }

  // 深色页自行让开状态栏 / 手势条（页面 expandSafeArea 后内容须按避让区留白）
  private applyInsets(): void {
    window.getLastWindow(getContext(this)).then((w: window.Window): void => {
      const topPx: number = w.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM).topRect.height;
      const indicatorPx: number =
        w.getWindowAvoidArea(window.AvoidAreaType.TYPE_NAVIGATION_INDICATOR).bottomRect.height;
      this.topInset = topPx > 0 ? topPx / pxPerVp() : TOP_FALLBACK;
      this.bottomInset = indicatorPx > 0 ? indicatorPx / pxPerVp() : BOTTOM_FALLBACK;
    }).catch((): void => {
      this.topInset = TOP_FALLBACK;
      this.bottomInset = BOTTOM_FALLBACK;
    });
  }

  private isDark(): boolean {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    return ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
  }

  // 本页恒定深色 → 状态栏图标切白；离开时按当前主题还原（浅色主题下图标复原为深色）
  private applyBarIcons(lightIcons: boolean): void {
    window.getLastWindow(getContext(this)).then((w: window.Window): void => {
      w.setWindowSystemBarProperties({
        statusBarContentColor: lightIcons ? '#FFFFFF' : '#000000'
      }).catch((): void => {
      });
    }).catch((): void => {
    });
  }

  // 手动添加连接：地址支持 IPv4 / IPv6 / 域名（可带端口与 http(s)），配对码可留空直连
  @State manualMode: boolean = false;
  @State baseUrlInput: string = '';
  @State ticketInput: string = '';

  private close(): void {
    if (this.stack !== null) {
      this.stack.pop(true);
    }
  }

  // 拉起系统默认扫码界面（免相机权限；页面生命周期内调用，官方要求）
  // 通道选择：扫码 or 手动输入（弹窗形态；取消则留在本页，页内按钮仍可重扫/切手输）
  private askMode(): void {
    this.getUIContext().showAlertDialog({
      title: t($r('app.string.scan_choose_title')),
      message: t($r('app.string.scan_choose_copy')),
      primaryButton: {
        value: t($r('app.string.scan_choose_scan')),
        action: (): void => {
          this.startScan();
        }
      },
      secondaryButton: {
        value: t($r('app.string.scan_manual_enter')),
        action: (): void => {
          this.manualMode = true;
        }
      }
    });
  }

  private startScan(): void {
    if (this.scanning || this.linking) {
      return;
    }
    this.scanning = true;
    this.error = '';
    const ctx: common.Context = this.getUIContext().getHostContext() as common.Context;
    const options: scanBarcode.ScanOptions = {
      scanTypes: [scanCore.ScanType.QR_CODE],
      enableMultiMode: false,
      enableAlbum: true
    };
    scanBarcode.startScanForResult(ctx, options)
      .then((result: scanBarcode.ScanResult): void => {
        this.scanning = false;
        this.handleValue(result.originalValue);
      })
      .catch((err: BusinessError): void => {
        this.scanning = false;
        if (err.code === SCAN_CANCELLED) {
          this.error = t($r('app.string.scan_cancelled'));
          return;
        }
        this.error = `${t($r('app.string.scan_failed'))}（${err.code}）`;
      });
  }

  // 手动连接（与扫码同一条落盘链路，仅取址来源不同）
  private async connectManual(): Promise<void> {
    if (this.linking) {
      return;
    }
    this.error = '';
    let baseUrl: string = '';
    this.linking = true;
    try {
      let rawUrl: string = this.baseUrlInput.trim();
      let rawTicket: string = this.ticketInput.trim();
      if (rawUrl.startsWith('qwenpaw://')) {
        const pasted: DirectPairing = parsePairingUri(rawUrl);
        rawUrl = pasted.baseUrl;
        rawTicket = rawTicket.length > 0 ? rawTicket : pasted.ticket;
      }
      const parsed: DirectPairing = parseManualInput(rawUrl, rawTicket);
      baseUrl = parsed.baseUrl;
      const outcome: ConnectOutcome = await connectToQwenPaw(parsed.baseUrl, parsed.ticket);
      const ctx: common.UIAbilityContext =
        this.getUIContext().getHostContext() as common.UIAbilityContext;
      await saveConnection(ctx, outcome.connection);
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.scan_paired'))
      });
      this.close();
    } catch (e) {
      const err: Error = e as Error;
      this.error = baseUrl.length > 0 ? describeConnectError(baseUrl, err) : err.message;
    } finally {
      this.linking = false;
    }
  }

  // 手动输入表单：深色页上用一层半透明白卡承载（页面底色近黑 #0A0C0A，
  // 卡的 20% 白与其拉开层级；输入框再压一层 35% 黑作内嵌面），文字一律显式白色，
  // 否则输入框与文字都会沉进深色底里看不见（默认字色按亮底设计）。
  @Builder
  manualForm() {
    Column() {
      Text($r('app.string.scan_manual_title'))
        .fontSize(20)
        .fontWeight(FontWeight.Medium)
        .fontColor(Color.White)
      Text($r('app.string.scan_manual_copy'))
        .fontSize(UiTokens.fsSecondary)
        .fontColor($r('app.color.scan_text_dim'))
        .margin({ top: 8 })
      TextInput({ text: $$this.baseUrlInput, placeholder: $r('app.string.scan_manual_addr_ph') })
        .width('100%')
        .height(48)
        .margin({ top: 18 })
        .fontSize(UiTokens.fsBody)
        .fontColor(Color.White)
        .placeholderColor($r('app.color.scan_text_dim'))
        .padding({ left: 12, right: 12 })
        .backgroundColor($r('app.color.scan_scrim'))
        .borderRadius(12)
      TextInput({ text: $$this.ticketInput, placeholder: $r('app.string.scan_manual_ticket_ph') })
        .width('100%')
        .height(48)
        .margin({ top: 10 })
        .fontSize(UiTokens.fsBody)
        .fontColor(Color.White)
        .placeholderColor($r('app.color.scan_text_dim'))
        .padding({ left: 12, right: 12 })
        .backgroundColor($r('app.color.scan_scrim'))
        .borderRadius(12)
      Button(this.linking ? $r('app.string.scan_linking') : $r('app.string.scan_manual_connect'))
        .width('100%')
        .height(48)
        .margin({ top: 16 })
        .fontColor($r('app.color.scan_bg'))
        .backgroundColor(Color.White)
        .stateEffect(false)
        .onClick((): void => {
          this.connectManual();
        })
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding(20)
    .borderRadius(24)
    .backgroundColor($r('app.color.scan_glass'))
  }

  private async handleValue(data: string): Promise<void> {
    this.linking = true;
    this.error = '';
    let baseUrl: string = '';
    try {
      const pairing: DirectPairing = parsePairingUri(data);
      baseUrl = pairing.baseUrl;
      const outcome: ConnectOutcome = await connectToQwenPaw(pairing.baseUrl, pairing.ticket);
      const ctx: common.UIAbilityContext =
        this.getUIContext().getHostContext() as common.UIAbilityContext;
      // saveConnection 同时把该连接置为当前（多连接 v2 模型）
      await saveConnection(ctx, outcome.connection);
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.scan_paired'))
      });
      this.close();
    } catch (e) {
      const err: Error = e as Error;
      // 连接类错误（含兑换失败/票据校验）按地址给可操作提示；解析类错误原样透出（已是中文文案）
      this.error = baseUrl.length > 0 ? describeConnectError(baseUrl, err) : err.message;
    } finally {
      this.linking = false;
    }
  }

  build() {
    NavDestination() {
      Column() {
        this.header()
        Column() {
          if (this.manualMode) {
            this.manualForm()
          } else {
          this.frame()
          Text(this.linking ? $r('app.string.scan_linking') : $r('app.string.scan_title'))
            .fontSize(24)
            .fontWeight(FontWeight.Medium)
            .fontColor(Color.White)
            .margin({ top: 24 })
          Text($r('app.string.scan_copy'))
            .fontSize(UiTokens.fsBody)
            .fontColor($r('app.color.scan_text_dim'))
            .margin({ top: 8 })
          if (this.error.length > 0) {
            Text(this.error)
              .fontSize(UiTokens.fsBody)
              .fontColor($r('app.color.scan_error'))
              .textAlign(TextAlign.Center)
              .maxLines(4)
              .margin({ top: 12 })
          }
          }
          // 手动添加连接入口（对齐 7378 配对页的手输通道）
          Text(this.manualMode ? $r('app.string.scan_manual_back')
            : $r('app.string.scan_manual_enter'))
            .fontSize(UiTokens.fsBody)
            .fontColor($r('app.color.scan_text_dim'))
            .decoration({ type: TextDecorationType.Underline, color: $r('app.color.scan_glass') })
            .margin({ top: 18 })
            .onClick((): void => {
              this.manualMode = !this.manualMode;
              this.error = '';
            })
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)

        this.footer()
      }
      .width('100%')
      .height('100%')
      .padding({
        top: this.topInset + 8,
        bottom: this.bottomInset + 12,
        left: 24,
        right: 24
      })
      .backgroundColor($r('app.color.scan_bg'))
      .alignItems(HorizontalAlign.Center)
    }
    .hideTitleBar(true)
    // 本页是整屏深色页：expandSafeArea 只扩绘制区、内容不动，要让内容真正铺进上下安全区
    // （状态栏/home 指示条区域不再露窗口底色）须再给布局级 ignoreLayoutSafeArea（官方口径：两者同设时它优先）。
    // 交互元素仍由本页 topInset/bottomInset 内边距让开系统区域。
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM],
      [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM, LayoutSafeAreaEdge.START, LayoutSafeAreaEdge.END])
    .expandSafeArea([SafeAreaType.SYSTEM],
      [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
    .onShown((_reason: VisibilityChangeReason): void => {
      this.applyBarIcons(true);
      // 进页先让用户选通道（扫码 / 手动输入地址），不直接拉起扫码；
      // 关掉选择框后仍可用页内按钮重扫或切手输（两条通道都保留）
      if (!this.autoStarted) {
        this.autoStarted = true;
        this.askMode();
      }
    })
    .onHidden((_reason: VisibilityChangeReason): void => {
      this.applyBarIcons(this.isDark());
    })
    .onBackPressed((): boolean => {
      this.close();
      return true;
    })
  }

  // 顶栏：返回（44 圆钮）+ 居中「安全配对」胶囊 + 右侧等宽占位（7378 header 布局）
  @Builder
  header() {
    Row() {
      Button() {
        Image($r('app.media.arrow_left'))
          .width(22).height(22)
          .fillColor(Color.White)
      }
      .type(ButtonType.Normal)
      .width(44)
      .height(44)
      .borderRadius(22)
      .backgroundColor($r('app.color.scan_scrim'))
      .stateEffect(false)
      .onClick((): void => {
        this.close();
      })

      Row({ space: 7 }) {
        Image($r('app.media.shield_check'))
          .width(16).height(16)
          .fillColor(Color.White)
        Text($r('app.string.scan_secure'))
          .fontSize(UiTokens.fsSecondary)
          .fontWeight(FontWeight.Medium)
          .fontColor(Color.White)
      }
      .height(38)
      .padding({ left: 14, right: 14 })
      .borderRadius(19)
      .backgroundColor($r('app.color.scan_scrim'))

      Row()
        .width(44)
        .height(44)
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
    .justifyContent(FlexAlign.SpaceBetween)
  }

  // 取景框：四个角标（7378 的 4 个圆角描边角）——点按重扫
  @Builder
  frame() {
    Stack() {
      this.corner(0)
      this.corner(1)
      this.corner(2)
      this.corner(3)
    }
    .width(FRAME_H)
    .height(FRAME_H)
    .margin({ bottom: 12 })
    .onClick((): void => {
      this.startScan();
    })
  }

  @Builder
  corner(idx: number) {
    if (idx === 0) {
      Stack()
        .width(CORNER_H)
        .height(CORNER_H)
        .borderColor(Color.White)
        .borderWidth({ top: CORNER_BORDER, left: CORNER_BORDER })
        .borderRadius({ topLeft: CORNER_RADIUS })
        .position({ x: 0, y: 0 })
    } else if (idx === 1) {
      Stack()
        .width(CORNER_H)
        .height(CORNER_H)
        .borderColor(Color.White)
        .borderWidth({ top: CORNER_BORDER, right: CORNER_BORDER })
        .borderRadius({ topRight: CORNER_RADIUS })
        .position({ x: FRAME_H - CORNER_H, y: 0 })
    } else if (idx === 2) {
      Stack()
        .width(CORNER_H)
        .height(CORNER_H)
        .borderColor(Color.White)
        .borderWidth({ bottom: CORNER_BORDER, left: CORNER_BORDER })
        .borderRadius({ bottomLeft: CORNER_RADIUS })
        .position({ x: 0, y: FRAME_H - CORNER_H })
    } else {
      Stack()
        .width(CORNER_H)
        .height(CORNER_H)
        .borderColor(Color.White)
        .borderWidth({ bottom: CORNER_BORDER, right: CORNER_BORDER })
        .borderRadius({ bottomRight: CORNER_RADIUS })
        .position({ x: FRAME_H - CORNER_H, y: FRAME_H - CORNER_H })
    }
  }

  // 底部动作：系统扫码界面由按钮/取景框拉起（内容区材质不生效 → 自绘按压反馈）
  @Builder
  footer() {
    Button(this.error.length > 0 ? $r('app.string.scan_retry') : $r('app.string.scan_start'))
      .width('100%')
      .height(48)
      .borderRadius(24)
      .backgroundColor($r('app.color.scan_glass'))
      .fontColor(Color.White)
      .fontSize(UiTokens.fsBody)
      .stateEffect(false)
      .scale({ x: this.pressed === 0 ? PRESS_SCALE : 1, y: this.pressed === 0 ? PRESS_SCALE : 1 })
      .visualEffect(pressEffect(this.pressed === 0))
      .onTouch((e: TouchEvent): void => {
        pressTouch(this.getUIContext(), e, this.latch, (v: boolean): void => {
          this.pressed = v ? 0 : -1;
        });
      })
      .onClick((): void => {
        this.startScan();
      })
  }
}
