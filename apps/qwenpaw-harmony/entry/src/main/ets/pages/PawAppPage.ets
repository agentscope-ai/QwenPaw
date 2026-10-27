/*
 * QwenPaw App 详情（内嵌 Web）—— 对齐 7378 app/pawapp/[id].tsx（从 App Center 打开扩展页面）。
 * 用 ArkWeb 的 Web 组件打开插件自声明入口：{baseUrl}{entry_page}（/api/pawapps 下发，
 * 如 /plugin/{id}；为空时回退 {baseUrl}/apps/{id}），并在**文档加载前**注入脚本，给同源
 * fetch / XHR 补 Authorization 与 X-Agent-Id —— 等价 RN 的 injectedJavaScriptBeforeContentLoaded
 * + authenticationBridge（官方 FAQ faqs-arkweb-59：加载前注入用 javaScriptOnDocumentStart）。
 * 同一段注入脚本还补一个 window.Notification 桩：插件前端用标准 Web Notification API
 * 发桌面通知（审批提醒等），ArkWeb 内建 Notification 无法授权 —— 桩把 new Notification(t,{body})
 * 转成 window.prompt('qwpaw.notify|{t,b}')，由 .onPrompt 回调接住转发系统通知中心
 * （官方 Web 事件 onPrompt：回调返回 true = 应用接管，须 handlePromptConfirm 解除阻塞）。
 * 整屏全屏：官方 faqs-arkui-1644 场景一「特定子页面缩小与放大」——AppStorage 状态变量
 * 控根 Navigation.mode 切单栏（左导航栏收起，本页放大为整屏）；窗口层按 faqs-arkui-360
 * setWindowLayoutFullScreen + setSpecificSystemBarEnabled('status', false) 隐藏状态栏，
 * Web 边到边铺满物理屏。退出走系统返回手势：onBackPressed 两级消费——第一级退出全屏
 * （先恢复状态栏再还原窗口布局），第二级出栈离开本页。
 * 另配 hideTitleBar 隐藏 HDS 标题栏（官方 API，带显隐动画）。
 * 深色模式：Web.darkMode(WebDarkMode.Auto)（官方 faqs-arkweb-112）——Web 引擎层的
 * prefers-color-scheme / color-scheme 跟随系统深浅色；页面实际配色仍由页面自身决定
 * （本插件跟随宿主 Console 主题，与服务端 /config/theme 一致）。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy } from '@kit.UIDesignKit';
import { webview } from '@kit.ArkWeb';
import { common } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { url } from '@kit.ArkTS';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { publishNotice } from '../services/NotifyService';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';

import { popSelfOnBack, slideCoverTransition } from '../services/NavPush';
import { t } from '../services/I18n';

@Builder
export function PawAppPageBuilder(_name: string, param: Object) {
  PawAppPage({ params: param })
}

@Component
export struct PawAppPage {
  params: Object = new Object();
  @State appId: string = '';
  // 插件自声明显示名（标题栏主标题；空时回退 appId）
  @State appName: string = '';
  // 插件自声明入口路由（/api/pawapps 的 entry_page）；空时回退 /apps/{id}
  private entryPage: string = '';
  @State target: string = '';
  @State injected: string = '';
  @State ready: boolean = false;
  @State opened: boolean = false;
  @State failed: string = '';
  @StorageLink('appIsDark') isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 整屏全屏（Navigation.mode 单栏 + 窗口全屏隐藏状态栏 + Web 边到边；系统返回手势退出）
  @State fullScreen: boolean = false;
  // 主窗口对象：进出全屏时设窗口全屏布局与状态栏显隐（官方 FAQ faqs-arkui-360）
  private win: window.Window | null = null;
  private controller: webview.WebviewController = new webview.WebviewController();
  private themeListener: ThemeListener | null = null;

  // 导航栈（onReady 时由框架注入）：标题栏返回按钮与系统侧滑都走它出栈
  private stack: NavPathStack | null = null;
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';
  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const id: Object = rec['appId'];
    this.appId = typeof id === 'string' ? id as string : '';
    const ep: Object = rec['entryPage'];
    this.entryPage = typeof ep === 'string' ? ep as string : '';
    const nm: Object = rec['name'];
    this.appName = typeof nm === 'string' ? nm as string : '';
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.themeListener = (snap: ThemeSnapshot): void => {
      this.theme = snap;
    };
    ThemeManager.get().subscribe(this.themeListener);
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
    });
    // 主窗口对象（整屏全屏用：窗口全屏布局 + 状态栏显隐）
    window.getLastWindow(ctx).then((w: window.Window): void => {
      this.win = w;
    }).catch((): void => {
      this.win = null;
    });
    loadConnection(ctx).then((conn: QpConnection | null): void => {
      if (conn === null) {
        this.failed = t($r('app.string.pawapp_no_connection'));
        return;
      }
      // 优先用插件自声明入口（entry_page），否则回退 /apps/{id}
      const path: string = this.entryPage.length > 0 ? this.entryPage : `/apps/${encodeURIComponent(this.appId)}`;
      // qpw_embed=1：通知宿主 Console 走原生客户端嵌入模式——宿主自绘的
      // Sidebar（左栏）与 Header（顶栏）不渲染，插件页全屏铺进原生壳
      //（原生标题栏已提供返回/全屏）。entry_page 自带查询参数时用 & 连接。
      const sep: string = path.indexOf('?') >= 0 ? '&' : '?';
      this.target = `${conn.baseUrl}${path}${sep}qpw_embed=1`;
      this.injected = this.bridge(conn);
      this.ready = true;
    });
  }

  aboutToDisappear(): void {
    // 整屏全屏状态下离开本页（返回键/侧滑出栈）：整屏要随之还原，否则根导航停在单栏
    if (this.fullScreen) {
      AppStorage.set('pawappFullScreen', false);
      this.setSystemBars(false);
    }
    if (this.themeListener !== null) {
      ThemeManager.get().unsubscribe(this.themeListener);
      this.themeListener = null;
    }
  }

  private accent(): string {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  // 整屏全屏开关：状态变量同步给根导航（Index 的 @StorageLink 联动 Navigation.mode），
  // 并切换窗口全屏布局与状态栏显隐（官方 FAQ faqs-arkui-360：进全屏先设窗口全屏再隐
  // 状态栏；退出先启状态栏再还原布局）
  private setFullScreen(on: boolean): void {
    this.fullScreen = on;
    AppStorage.set('pawappFullScreen', on);
    this.setSystemBars(on);
  }

  private setSystemBars(fs: boolean): void {
    if (this.win === null) {
      return;
    }
    if (fs) {
      this.win.setWindowLayoutFullScreen(true).catch((): void => {
      });
      this.win.setSpecificSystemBarEnabled('status', false).catch((): void => {
      });
    } else {
      this.win.setSpecificSystemBarEnabled('status', true).catch((): void => {
      });
      this.win.setWindowLayoutFullScreen(false).catch((): void => {
      });
    }
  }

  // 同源判定用 origin（官方 @ohos.url：protocol + host + port）
  private originOf(base: string): string {
    try {
      const u: url.URL = new url.URL(base);
      const port: string = u.port.length > 0 ? `:${u.port}` : '';
      return `${u.protocol}//${u.hostname}${port}`;
    } catch (e) {
      return base;
    }
  }

  // 文档加载前注入：仅对同源请求补鉴权头（对齐 7378 authenticationBridge 行为）
  private bridge(conn: QpConnection): string {
    const origin: string = this.originOf(conn.baseUrl);
    const agentId: string = conn.agentId.length > 0 ? conn.agentId : 'default';
    return `(function(){var allowedOrigin=${JSON.stringify(origin)};var token=${JSON.stringify(conn.token)};var agentId=${JSON.stringify(agentId)};`
      + `var same=function(input){try{var raw=(typeof input==='string')?input:input.url;return new URL(raw,window.location.href).origin===allowedOrigin;}catch(e){return false;}};`
      + `var of=window.fetch.bind(window);window.fetch=function(input,init){init=init||{};if(!same(input))return of(input,init);`
      + `var h=new Headers(init.headers||{});if(token)h.set('Authorization','Bearer '+token);h.set('X-Agent-Id',agentId);`
      + `return of(input,Object.assign({},init,{headers:h,credentials:'include'}));};`
      + `var oo=XMLHttpRequest.prototype.open;var os=XMLHttpRequest.prototype.send;`
      + `XMLHttpRequest.prototype.open=function(m,u){this.__qpwSame=same(u);return oo.apply(this,arguments);};`
      + `XMLHttpRequest.prototype.send=function(){if(this.__qpwSame){if(token)this.setRequestHeader('Authorization','Bearer '+token);this.setRequestHeader('X-Agent-Id',agentId);}return os.apply(this,arguments);};})();`
      // Notification 桩：覆盖内建（webview 里其权限恒不可授），构造调用转 prompt 桥
      + `(function(){function QPN(t,o){var b=(o&&o.body)?String(o.body):'';var p;`
      + `try{p=JSON.stringify({t:String(t),b:b});}catch(e){return;}`
      + `window.prompt('qwpaw.notify|'+p,'');}`
      + `QPN.permission='granted';`
      + `QPN.requestPermission=function(){return Promise.resolve('granted');};`
      + `QPN.prototype.close=function(){};`
      + `window.Notification=QPN;})();`;
  }

  build() {
    HdsNavDestination() {
      Stack() {
        if (this.failed.length > 0) {
          Column() {
            Text(this.failed)
              .fontSize(UiTokens.fsBody)
              .fontColor($r('app.color.status_error'))
          }
          .width('100%')
          .height('100%')
          .justifyContent(FlexAlign.Center)
        } else if (this.ready) {
          // 非沉浸布局：HDS 标题栏是覆盖层（不参与内容布局），顶部按二级页统一口径
          // 让出 UiTokens.topInset，插件自带上栏（胶囊 / 菜单栏）不再被标题栏遮挡。
          // 整屏全屏：窗口已全屏且状态栏隐藏，无需让位条 —— Web 边到边铺满物理屏。
          Column() {
            if (!this.fullScreen) {
              Column().width('100%').height(UiTokens.topInset)
            }
            Web({ src: this.target, controller: this.controller })
              .javaScriptAccess(true)
              .domStorageAccess(true)
              // Web 引擎层深色模式跟随系统（官方 faqs-arkweb-112）：页面标准的
              // prefers-color-scheme / color-scheme 据此取值；默认 Off 时页面恒见浅色
              .darkMode(WebDarkMode.Auto)
              // 文档加载前注入（官方 FAQ：加载前用 javaScriptOnDocumentStart）
              .javaScriptOnDocumentStart([{ script: this.injected, scriptRules: ['*'] }])
              .onPageEnd((): void => {
                this.opened = true;
              })
              // 通知桥：注入的 Notification 桩把 new Notification(t,{body}) 转成
              // window.prompt('qwpaw.notify|{...}')，这里接住转发系统通知中心。
              // 官方口径：回调返回 true = 应用接管（不再弹系统 prompt 框），且必须
              // handlePromptConfirm / handleCancel 通知结果，否则渲染进程阻塞；
              // 返回 false = 结果视为取消（本网桥之外的 prompt 一律静默取消）。
              .onPrompt((event): boolean => {
                const prefix: string = 'qwpaw.notify|';
                if (!event.message.startsWith(prefix)) {
                  return false;
                }
                let title: string = '';
                let body: string = '';
                try {
                  const rec: Object = JSON.parse(event.message.substring(prefix.length));
                  const rt: Object = (rec as Record<string, Object>)['t'];
                  const rb: Object = (rec as Record<string, Object>)['b'];
                  title = typeof rt === 'string' ? rt as string : '';
                  body = typeof rb === 'string' ? rb as string : '';
                } catch (e) {
                  // 载荷损坏：按取消处理，不弹空通知
                }
                if (title.length === 0 && body.length === 0) {
                  return false;
                }
                const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
                publishNotice(ctx, title, body).catch((): void => {
                });
                event.result.handlePromptConfirm('');
                return true;
              })
              .width('100%')
              .layoutWeight(1)
          }
          .width('100%')
          .height('100%')
        }

        if (this.ready && !this.opened) {
          Column() {
            LoadingProgress()
              .width(36)
              .height(36)
              .color(this.accent())
            Text($r('app.string.pawapp_loading'))
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .margin({ top: 10 })
            Text($r('app.string.pawapp_hint'))
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .margin({ top: 6 })
              .padding({ left: 24, right: 24 })
              .textAlign(TextAlign.Center)
          }
          .width('100%')
          .height('100%')
          .justifyContent(FlexAlign.Center)
          .backgroundColor($r('app.color.page_bg'))
        }

      }
      .width('100%')
      .height('100%')
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
    // 两级消费：整屏全屏时第一级返回先退出全屏（还原分栏/标题栏/状态栏），第二级才出栈。
    .onBackPressed((): boolean => {
      if (this.fullScreen) {
        this.setFullScreen(false);
        return true;
      }
      return popSelfOnBack(this.stack);
    })
    // 全屏模式：隐藏标题栏（官方 API，带显隐动画）。全屏下退出入口 = 系统返回手势。
    .hideTitleBar(this.fullScreen, true)
    .titleBar({
      // 本页标题栏 = 顶部毛玻璃、非沉浸（内嵌 Web 是整页应用，顶部不能被覆盖遮挡）：
      // 不开 systemMaterialEffect、不铺主题色实底 —— 官方 HdsNavigationBackgroundStyle 口径：
      // GRADIENT_BLUR + enableScrollEffect=false 且未配置沉浸光感时，originalStyle.backgroundColor
      // 默认 #99000000 磨砂底、blurRadius 默认 16.0，主标题默认 sys.color.font_on_primary。
      style: {
        scrollEffectOpts: {
          // enableScrollEffect = false：官方口径「不随内容区滚动动态生效标题栏样式，仅生效 originalStyle」。
          // Web 的滚动发生在 WebView 内部（不驱动 HDS 滚动链路），标题栏样式只取静止态一档。
          enableScrollEffect: false,
          scrollEffectType: ScrollEffectType.GRADIENT_BLUR
        },
        // blurStrategy 用 ENABLE 而不是 ADAPTIVE：官方口径 ADAPTIVE 只在系统"精美"档生效模糊，
        // 策略落在轻柔/流畅档时标题栏模糊整块不生效；ENABLE 恒生效，观感稳定。
        blurStrategy: BlurStrategy.ENABLE,
        originalStyle: {
          backgroundStyle: {
            // 未配置 systemMaterialEffect 时官方默认 16.0，显式固定口径
            blurRadius: 16.0,
            // 蒙层外扩归零（生效态在 originalStyle）：默认外扩 32vp 会在标题栏底边之下
            // 多出一段蒙层带（真机实测约 56vp 灰带，浅色模式即"接缝"）
            maskExtraHeight: 0.0
          }
        }
      },
      content: {
        // 主标题用插件显示名（空时回退 appId）；不再带副标题，标题栏只留一行，视觉更薄
        title: {
          mainTitle: this.appName.length > 0 ? this.appName : this.appId
        },
        // 右上角全屏入口（官方标题栏菜单项：icon + 点击回调）
        menu: {
          value: [
            {
              content: {
                icon: $r('sys.symbol.fullscreen'),
                label: $r('app.string.pawapp_fullscreen'),
                action: (): void => {
                  this.setFullScreen(true);
                }
              }
            }
          ]
        }
      },
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
    .backgroundColor($r('app.color.page_bg'))
    .expandSafeArea([SafeAreaType.SYSTEM],
      [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
  }
}
