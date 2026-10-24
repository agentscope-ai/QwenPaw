/*
 * AgentScope Platform · GitHub 授权（内嵌 ArkWeb）—— 移植 PR #7378
 * `app/platform-auth.tsx`（回跳落地）与 `features/platform/EmbeddedPlatformOAuth.tsx`（内嵌授权视图）：
 * 在 App 内的 Web 视图里打开 Platform 授权页，**加载前**拦下环回回跳地址，取授权码换令牌。
 *
 * 与 7378 的差异（有意）：本端不比 7378 少做一步授权，但**不用外部浏览器 + 自定义 Scheme 回跳、
 * 也不起本机 loopback 监听**（7378 走 expo-web-browser + 本机 HTTP 服务）；内嵌 Web 在请求发起前
 * 就把回跳拦下（官方 onLoadIntercept 时机 = 加载 url 之前），等价且少一个监听口。
 * 取消路径 = 标题栏返回/系统返回（不产生会话）。
 *
 * 路由：platform-oauth（router_map）。参数 stack 供本页 pop 回登录页。
 */
import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { webview } from '@kit.ArkWeb';
import { common } from '@kit.AbilityKit';
import { url } from '@kit.ArkTS';
import {
  PLATFORM_BASE_URL, platformOAuthExchange, PlatformSession
} from '../services/PlatformSession';
import {
  OAuthNavigation, OAuthPkce, buildAuthorizeUrl, classifyOAuthNavigation,
  createOAuthPkce, oauthRedirectUri, parseOAuthCallback
} from '../services/PlatformOAuth';
import { ThemeManager, ThemeSnapshot } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';

import { popSelfOnBack, slideCoverTransition } from '../services/NavPush';
import { t } from '../services/I18n';

@Builder
export function PlatformOAuthPageBuilder(_name: string, param: Object) {
  PlatformOAuthPage({ params: param })
}

@Component
export struct PlatformOAuthPage {
  params: Object = new Object();
  @State target: string = '';
  @State ready: boolean = false;
  @State loading: boolean = true;
  @State exchanging: boolean = false;
  @State error: string = '';
  @State pressed: number = -1;
  @StorageLink('appIsDark') isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  private verifier: string = '';
  private redirect: string = '';
  private oauthState: string = '';
  private settled: boolean = false;
  private stack: NavPathStack | null = null;
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';
  private controller: webview.WebviewController = new webview.WebviewController();
  private latch: PressLatch = new PressLatch();

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const st: Object = rec['stack'];
    this.stack = (st === undefined || st === null) ? null : st as NavPathStack;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.begin();
  }

  // 生成 PKCE + state 并给出授权 URL（重试时重新生成，避免复用已用过的授权码）
  private begin(): void {
    const pkce: OAuthPkce = createOAuthPkce();
    this.verifier = pkce.verifier;
    this.oauthState = pkce.state;
    this.redirect = oauthRedirectUri();
    this.target = buildAuthorizeUrl(PLATFORM_BASE_URL, pkce.challenge, this.redirect, pkce.state);
    this.error = '';
    this.loading = true;
    this.settled = false;
    this.ready = true;
  }

  // 加载前拦截：回跳地址 → 结束本次导航并换取令牌；其余按 7378 口径决定放行
  private intercept(value: string): boolean {
    const action: OAuthNavigation = classifyOAuthNavigation(value, this.redirect);
    if (action === OAuthNavigation.CALLBACK) {
      this.exchange(value);
      return true;
    }
    return action !== OAuthNavigation.ALLOW;
  }

  // 授权码换令牌（对齐 7378：校验 state → 取 code → POST /api/cli/v1/oauth/token）
  private async exchange(callbackUrl: string): Promise<void> {
    if (this.settled) {
      return;
    }
    this.settled = true;
    this.exchanging = true;
    this.loading = false;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    try {
      const code: string = parseOAuthCallback(callbackUrl, this.oauthState);
      const session: PlatformSession =
        await platformOAuthExchange(ctx, code, this.redirect, this.verifier);
      this.toast(session.username.length > 0
        ? `${t($r('app.string.platform_login_ok'))} · ${session.username}`
        : t($r('app.string.platform_login_ok')));
      this.close();
    } catch (e) {
      this.error = (e as Error).message;
      this.settled = false;
    } finally {
      this.exchanging = false;
    }
  }

  private close(): void {
    const stack: NavPathStack | null = this.stack;
    if (stack !== null) {
      stack.pop(true);
    }
  }

  private accent(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  // 标题栏副标题 = 平台主机名（用 hostname：本实现下 host 可能为空，工程内 originOf 同口径）
  private host(): string {
    try {
      return new url.URL(PLATFORM_BASE_URL).hostname;
    } catch (e) {
      return PLATFORM_BASE_URL;
    }
  }

  private toast(message: string): void {
    this.getUIContext().getPromptAction().showToast({ message: message });
  }

  build() {
    HdsNavDestination() {
      Stack() {
        if (this.error.length > 0) {
          this.errorBlock()
        } else if (this.ready) {
          Web({ src: this.target, controller: this.controller })
            .javaScriptAccess(true)
            .domStorageAccess(true)
            // 授权页不需要本地文件能力与多窗口（对齐 7378 allowFileAccess=false / setSupportMultipleWindows=false）
            .fileAccess(false)
            .multiWindowAccess(false)
            .onPageBegin((): void => {
              this.loading = true;
            })
            .onPageEnd((): void => {
              this.loading = false;
            })
            // 加载前拦截回跳（官方 onLoadIntercept：返回 true = 阻止本次访问）
            .onLoadIntercept((event: OnLoadInterceptEvent): boolean => {
              return this.intercept(event.data.getRequestUrl());
            })
            .width('100%')
            .height('100%')
          if (this.loading || this.exchanging) {
            Column() {
              LoadingProgress()
                .width(36)
                .height(36)
                .color(this.accent())
              Text(this.exchanging
                ? $r('app.string.platform_oauth_returning')
                : $r('app.string.platform_oauth_loading'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .margin({ top: 10 })
            }
            .width('100%')
            .height('100%')
            .justifyContent(FlexAlign.Center)
            .backgroundColor($r('app.color.page_bg'))
          }
        }
      }
      .width('100%')
      .height('100%')
    }
    // 内容扩到安全区外（布局级）：二级页四边都扩，否则底部/左右两侧会露出窗口底色
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM],
      [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM, LayoutSafeAreaEdge.START, LayoutSafeAreaEdge.END])
    // 二级页转场：整页自右水平覆盖进来（退出滑回右侧）——见 services/NavPush.slideCoverTransition。
    // 系统默认档在分栏下动的是"内容区左边缘 0 → 分栏位"，观感从左侧摊过来（判"方向反了"），
    // 故改用官方 customTransition（NavDestinationTransitionDelegate）自己定方向。
    .customTransition((op: NavigationOperation, isEnter: boolean)
      : Array<NavDestinationTransition> | undefined => slideCoverTransition(op, isEnter,
        (v: string): void => { this.pageX = v; }))
    .translate({ x: this.pageX })
    // 返回键：系统侧滑与标题栏左上角返回按钮都投递到当前 NavDestination 的 onBackPressed
    //（官方 FAQ faqs-arkui-1117：该回调"支持拦截系统侧滑及 NavDestination 标题栏的返回事件"）；
    // 没挂它时标题栏返回按钮点了没有反应 —— 这里自己出栈并消费。
    .onBackPressed((): boolean => popSelfOnBack(this.stack))
    .titleBar({
      style: {
        scrollEffectOpts: {
          // 与其余二级页同口径：关掉滚动插值，底色/模糊只有一个状态（避免上滚"先变暗再回主题色"）
          enableScrollEffect: false,
          scrollEffectType: ScrollEffectType.GRADIENT_BLUR
        },
        blurStrategy: BlurStrategy.ENABLE,
        // maskExtraHeight 必须写在生效态（enableScrollEffect=false 时只生效 originalStyle），
        // 否则退回平台默认外扩（实测比标题栏底边多约 56vp），在工具条下方留下中性灰带。
        originalStyle: {
          backgroundStyle: { blurRadius: 12.0, maskExtraHeight: 0.0, backgroundColor: this.accent() }
        },
        scrollEffectStyle: {
          backgroundStyle: { blurRadius: 12.0, backgroundColor: this.accent() }
        },
        systemMaterialEffect: {
          materialType: hdsMaterial.MaterialType.ADAPTIVE,
          materialLevel: hdsMaterial.MaterialLevel.ADAPTIVE
        }
      },
      content: {
        title: {
          mainTitle: $r('app.string.platform_oauth_title'),
          subTitle: this.host()
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
  errorBlock() {
    Column() {
      Image($r('app.media.triangle_alert'))
        .width(30)
        .height(30)
        .fillColor($r('app.color.status_error'))
      Text($r('app.string.platform_oauth_failed'))
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Medium)
        .margin({ top: 12 })
      Text(this.error)
        .fontSize(UiTokens.fsCaption)
        .fontColor($r('app.color.text_tertiary'))
        .textAlign(TextAlign.Center)
        .lineHeight(19)
        .margin({ top: 6 })
        .padding({ left: 32, right: 32 })
      Text($r('app.string.platform_oauth_copy'))
        .fontSize(UiTokens.fsCaption)
        .fontColor($r('app.color.text_tertiary'))
        .textAlign(TextAlign.Center)
        .lineHeight(19)
        .margin({ top: 12 })
        .padding({ left: 32, right: 32 })
      Text($r('app.string.platform_oauth_retry'))
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Medium)
        .fontColor(Color.White)
        .textAlign(TextAlign.Center)
        .width('100%')
        .height(46)
        .borderRadius(14)
        .backgroundColor(this.accent())
        .margin({ top: 22 })
        .scale({ x: this.pressed === 0 ? PRESS_SCALE : 1, y: this.pressed === 0 ? PRESS_SCALE : 1 })
        .visualEffect(pressEffect(this.pressed === 0))
        .onTouch((e: TouchEvent): void => {
          pressTouch(this.getUIContext(), e, this.latch, (v: boolean): void => {
            this.pressed = v ? 0 : -1;
          });
        })
        .onClick((): void => {
          this.begin();
        })
    }
    .width('100%')
    .height('100%')
    .justifyContent(FlexAlign.Center)
    .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
  }
}
