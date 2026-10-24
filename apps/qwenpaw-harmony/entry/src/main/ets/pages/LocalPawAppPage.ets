/*
 * 本地 PawApp 详情（内嵌 Web，离线运行）—— 无 QwenPaw 服务端时运行本机安装的前端 JS 插件。
 * 与 PawAppPage（服务端 PawApp，同源 fetch 注入鉴权头）同构、同交互（整屏全屏 / 返回键两级消费 /
 * 加载遮罩 / 失败态），差别只在目标与桥：
 *   - 目标 = file://<filesDir>/pluginhost/index.html?paw_app=<id>&qpw_name=<名>&qpw_entry=<入口>
 *     （services/LocalPluginStore 的本地宿主 shell；Web.fileAccess(true) 允许 file 页面读同目录
 *     插件资源，官方 Web 组件 fileAccess 属性）
 *   - 无鉴权注入：host.js 自己内置离线语义（数据接口受控 503）与 Notification 桩
 *     （new Notification → window.prompt('qwpaw.notify|…')，本页 .onPrompt 接住转发系统通知中心，
 *     官方 Web 事件 onPrompt：回调返回 true = 应用接管，须 handlePromptConfirm 解除阻塞）
 * 整屏全屏机制与 PawAppPage 完全一致（官方 faqs-arkui-1644 场景一 + faqs-arkui-360：
 * AppStorage 状态变量控根 Navigation.mode + 窗口全屏布局 + 状态栏显隐，系统返回手势两级退出）。
 * 深色：WebDarkMode.Auto（官方 faqs-arkweb-112）——宿主页 antd 主题随 prefers-color-scheme 切换。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy } from '@kit.UIDesignKit';
import { webview } from '@kit.ArkWeb';
import { common } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { publishNotice } from '../services/NotifyService';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { LocalPluginStore, LocalPluginInfo } from '../services/LocalPluginStore';
import { PluginFileBridge } from '../services/PluginFileBridge';
import { popSelfOnBack, slideCoverTransition } from '../services/NavPush';
import { t } from '../services/I18n';

const DOMAIN = 0x0000;

@Builder
export function LocalPawAppPageBuilder(_name: string, param: Object) {
  LocalPawAppPage({ params: param })
}

@Component
export struct LocalPawAppPage {
  params: Object = new Object();
  @State appId: string = '';
  @State appName: string = '';
  @State target: string = '';
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
  // 插件文件读取桥：file:// fetch 被 CORS 拦截时，ESM bundle 由端侧读沙箱文件回传（见 host.js）
  private fileBridge: PluginFileBridge = new PluginFileBridge('');

  // 导航栈（onReady 时由框架注入）：标题栏返回按钮与系统侧滑都走它出栈
  private stack: NavPathStack | null = null;
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';
  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const id: Object = rec['id'];
    this.appId = typeof id === 'string' ? id as string : '';
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
    // 桥的根目录 = 本地宿主 shell 落盘目录（与 LocalPluginStore 同一布局）
    this.fileBridge = new PluginFileBridge(`${ctx.filesDir}/pluginhost`);
    this.resolveTarget(ctx);
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

  // 目标解析：宿主 shell 落盘 + 插件完整性校验，任一缺失给出明确失败态（不静默白屏）
  private resolveTarget(ctx: common.UIAbilityContext): void {
    if (this.appId.length === 0) {
      this.failed = t($r('app.string.localpawapp_failed_params'));
      return;
    }
    try {
      LocalPluginStore.ensureHostShell(ctx);
      const info: LocalPluginInfo | null = LocalPluginStore.get(ctx, this.appId);
      if (info === null || !LocalPluginStore.pluginReady(ctx, info)) {
        this.failed = t($r('app.string.localpawapp_failed_missing'));
        return;
      }
      const display: string = this.appName.length > 0 ? this.appName : this.appId;
      let query: string =
        `?paw_app=${encodeURIComponent(this.appId)}` +
        `&qpw_name=${encodeURIComponent(display)}` +
        `&qpw_entry=${encodeURIComponent(info.entry)}`;
      // PawApp（manifest meta.pawapp）→ 宿主壳走单页：不出左侧菜单壳（Sider / drawer / ☰）
      const pawapp: Record<string, Object> | null = LocalPluginStore.readPawappMeta(ctx, this.appId);
      if (pawapp !== null) {
        query += '&qpw_pawapp=1';
        const epRaw: Object = pawapp['entry_page'];
        const ep: string = typeof epRaw === 'string' ? epRaw as string : '';
        if (ep.length > 0) {
          query += `&qpw_pawapp_route=${encodeURIComponent(ep)}`;
        }
      }
      this.target = `file://${ctx.filesDir}/pluginhost/index.html${query}`;
      this.ready = true;
    } catch (e) {
      this.failed = t($r('app.string.localpawapp_failed_shell'));
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
          // 让出 UiTokens.topInset；整屏全屏时窗口已全屏且状态栏隐藏，无需让位条。
          Column() {
            if (!this.fullScreen) {
              Column().width('100%').height(UiTokens.topInset)
            }
            Web({ src: this.target, controller: this.controller })
              .javaScriptAccess(true)
              // file:// 页面读同目录插件资源（vendor / plugins/<id>）须开启文件访问
              .fileAccess(true)
              .domStorageAccess(true)
              // 插件文件读取桥（window.qpwFile.readPluginFile）：ArkWeb 对 file:// 的 fetch 被
              // CORS 拦截（官方 scheme 白名单不含 file），ESM 插件 bundle 须由端侧读沙箱文件、
              // base64 回传后按模块 import（管线见 host.js loadPlugin）。
              .javaScriptProxy({
                object: this.fileBridge,
                name: 'qpwFile',
                methodList: ['readPluginFile'],
                controller: this.controller
              })
              // Web 引擎层深色模式跟随系统（官方 faqs-arkweb-112）
              .darkMode(WebDarkMode.Auto)
              .onPageEnd((): void => {
                this.opened = true;
              })
              // Web 控制台/资源错误桥接 hilog：离线插件的 JS 日志与子资源加载失败默认不进
              // 系统日志，运行面异常（黑屏、通知缺失）无从取证；桥接后按 tag=QpwPawWeb 检索。
              .onConsole((event: OnConsoleEvent): boolean => {
                hilog.info(DOMAIN, 'QpwPawWeb', 'console L%{public}d %{public}s:%{public}d %{public}s',
                  event.message.getMessageLevel(), event.message.getSourceId(),
                  event.message.getLineNumber(), event.message.getMessage());
                return true;
              })
              .onErrorReceive((event: OnErrorReceiveEvent): void => {
                hilog.error(DOMAIN, 'QpwPawWeb', 'resource error main=%{public}s code=%{public}d %{public}s %{public}s',
                  String(event.request.isMainFrame()), event.error.getErrorCode(),
                  event.request.getRequestUrl(), event.error.getErrorInfo());
              })
              // 通知桥：host.js 的 Notification 桩把 new Notification(t,{body,kind?,target?})
              // 转成 window.prompt('qwpaw.notify|{...}')，这里接住转发系统通知中心。
              // 官方口径：回调返回 true = 应用接管（不再弹系统 prompt 框），且必须
              // handlePromptConfirm / handleCancel 通知结果，否则渲染进程阻塞。
              .onPrompt((event): boolean => {
                hilog.info(DOMAIN, 'QpwPawNotify', 'onPrompt received: %{public}s',
                  event.message.substring(0, 64));
                const prefix: string = 'qwpaw.notify|';
                if (!event.message.startsWith(prefix)) {
                  return false;
                }
                let title: string = '';
                let body: string = '';
                // 语义字段（契约 v1）：kind/target 目前仅取证留痕，P3 深链
                // （点通知直达插件内目标）将消费 target；旧插件 {t,b} 不受影响。
                let kind: string = '';
                let target: string = '';
                try {
                  const rec: Object = JSON.parse(event.message.substring(prefix.length));
                  const rt: Object = (rec as Record<string, Object>)['t'];
                  const rb: Object = (rec as Record<string, Object>)['b'];
                  const rk: Object = (rec as Record<string, Object>)['kind'];
                  const rg: Object = (rec as Record<string, Object>)['target'];
                  title = typeof rt === 'string' ? rt as string : '';
                  body = typeof rb === 'string' ? rb as string : '';
                  kind = typeof rk === 'string' ? rk as string : '';
                  target = typeof rg === 'string' ? rg as string : '';
                } catch (e) {
                  // 载荷损坏：按取消处理，不弹空通知
                }
                hilog.info(DOMAIN, 'QpwPawNotify',
                  'notify payload t.len=%{public}d b.len=%{public}d kind=%{public}s target=%{public}s',
                  title.length, body.length, kind, target);
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
            Text($r('app.string.localpawapp_loading'))
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .margin({ top: 10 })
            Text($r('app.string.localpawapp_hint'))
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
    // 内容也扩到安全区外（与 PawAppPage 同口径）：二级页四边都扩
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM],
      [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM, LayoutSafeAreaEdge.START, LayoutSafeAreaEdge.END])
    // 二级页转场：整页自右水平覆盖进来（与 PawAppPage 同口径）
    .customTransition((op: NavigationOperation, isEnter: boolean)
      : Array<NavDestinationTransition> | undefined => slideCoverTransition(op, isEnter,
        (v: string): void => { this.pageX = v; }))
    .translate({ x: this.pageX })
    // 按官方口径在 onReady 取导航栈（NavDestinationContext.pathStack）
    .onReady((ctx: NavDestinationContext): void => {
      this.stack = ctx.pathStack;
    })
    // 返回键两级消费：整屏全屏时第一级先退出全屏，第二级才出栈
    .onBackPressed((): boolean => {
      if (this.fullScreen) {
        this.setFullScreen(false);
        return true;
      }
      return popSelfOnBack(this.stack);
    })
    // 全屏模式：隐藏标题栏（官方 API，带显隐动画）
    .hideTitleBar(this.fullScreen, true)
    .titleBar({
      // 顶部毛玻璃、非沉浸（与 PawAppPage 同口径：Web 滚动不驱动 HDS 滚动链路，
      // 标题栏只取静止态一档；blurStrategy=ENABLE 恒生效；maskExtraHeight=0 无蒙层外扩）
      style: {
        scrollEffectOpts: {
          enableScrollEffect: false,
          scrollEffectType: ScrollEffectType.GRADIENT_BLUR
        },
        blurStrategy: BlurStrategy.ENABLE,
        originalStyle: {
          backgroundStyle: {
            blurRadius: 16.0,
            maskExtraHeight: 0.0
          }
        }
      },
      content: {
        title: {
          mainTitle: this.appName.length > 0 ? this.appName : this.appId
        },
        // 右上角全屏入口
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
